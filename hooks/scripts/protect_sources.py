#!/usr/bin/env python3
"""PreToolUse hook: deny writes to source data registered in `.gis/sources.json`. Standard library only.

Reads one hook payload (Claude Code, Codex or dsh bridge) on stdin. Write targets come from
file-editing tools, Codex apply_patch, and a best-effort scan of shell commands.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing the shared module must not leave __pycache__ in the plugin
from _patterns import glob_regex  # noqa: E402

REGISTRY = Path(".gis") / "sources.json"
SCHEMA_VERSION = 1

FILE_TOOLS = {"write": "file_path", "edit": "file_path", "multiedit": "file_path", "notebookedit": "notebook_path"}
SHELL_TOOLS = {"bash"}
POWERSHELL_TOOLS = {"powershell", "pwsh"}
PATCH_TOOLS = {"apply_patch"}

# A write to a sidecar counts as a write to the dataset it belongs to.
SHAPEFILE_SIDECARS = {".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix", ".shp.xml"}
SIDECAR_SUFFIXES = (".aux.xml", ".ovr", ".msk")

PATCH_LINE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "1>", "2>", "1>>", "2>>"}
# command -> how its write targets are found: "all" args, "last" arg, "first" positional
WRITERS = {
    "rm": "all", "mv": "all", "truncate": "all", "tee": "all", "touch": "all", "unlink": "all",
    "shred": "all", "gdal_edit.py": "all", "gdal_edit": "all",
    "cp": "last", "gdal_translate": "last", "gdalwarp": "last", "rsync": "last", "install": "last",
    "ogr2ogr": "first", "gdaladdo": "first",
}
# PowerShell cmdlets and aliases, lowercase; "copy" writes only to its destination.
POWERSHELL_WRITERS = {
    "set-content": "all", "sc": "all", "add-content": "all", "ac": "all", "clear-content": "all", "clc": "all",
    "out-file": "all", "tee-object": "all", "export-csv": "all", "new-item": "all", "ni": "all",
    "remove-item": "all", "ri": "all", "del": "all", "erase": "all", "rd": "all", "rmdir": "all",
    "move-item": "all", "mi": "all", "move": "all", "rename-item": "all", "rni": "all", "ren": "all",
    "copy-item": "copy", "cpi": "copy", "copy": "copy", "cp": "copy",
}


class RegistryError(Exception):
    pass


def load_registry(path):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"无法读取：{exc}") from None
    if not isinstance(doc, dict) or doc.get("contract") != "sources" or doc.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"须为 contract=sources、schema_version={SCHEMA_VERSION} 的对象")
    patterns = doc.get("protected")
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p.strip() for p in patterns):
        raise RegistryError("protected 须为非空字符串数组")
    for p in patterns:
        if p.startswith("/") or ".." in Path(p).parts:
            raise RegistryError(f"模式须为相对路径且不含 ..：{p}")
    flags = re.IGNORECASE if _ignores_case(path) else 0
    return [(p, glob_regex(p.rstrip("/"), flags)) for p in patterns]


def _ignores_case(registry):
    """On a case-insensitive volume RAW/A.CSV is raw/a.csv. The registry exists, so try it under another spelling."""
    try:
        return os.path.samefile(registry, registry.with_name(registry.name.upper()))
    except OSError:
        return False


def _candidates(rel):
    """The relative path itself, the dataset it is a sidecar of, and every ancestor directory."""
    names = {rel}
    lower = rel.lower()
    for suffix in SHAPEFILE_SIDECARS:
        if lower.endswith(suffix):
            names.add(rel[: -len(suffix)] + ".shp")
    for suffix in SIDECAR_SUFFIXES:
        if lower.endswith(suffix):
            names.add(rel[: -len(suffix)])
    parts = rel.split("/")
    names.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return names


def check_target(target, cache):
    """Return a denial reason for one absolute path, or None."""
    for base in [target.parent, *target.parent.parents]:
        registry = base / REGISTRY
        if not registry.is_file():
            continue
        if registry not in cache:
            try:
                cache[registry] = load_registry(registry)
            except RegistryError as exc:
                cache[registry] = exc
        entry = cache[registry]
        if isinstance(entry, RegistryError):
            return f"{target} 位于 {registry} 管辖的目录，但该登记文件无效（{entry}）；修正登记后再写入。"
        rel = target.relative_to(base).as_posix()
        for name in _candidates(rel):
            for pattern, regex in entry:
                if regex.match(name):
                    return (f"{target} 已在 {registry} 登记为受保护源数据（匹配 `{pattern}`）。"
                            "请把结果写到其它路径；确需改动源数据时由用户修改登记。")
    return None


def _copy_destination(words):
    """PowerShell copy: the -Destination value (any unambiguous abbreviation, `-Dest x` or `-Dest:x`), or the last argument."""
    for i, word in enumerate(words[1:], 1):
        key, colon, value = word.partition(":")
        if len(key) > 3 and "-destination".startswith(key.lower()):
            return value if colon else (words[i + 1] if i + 1 < len(words) else None)
    positional = [w for w in words[1:] if not w.startswith("-")]
    return positional[-1] if positional else None


def _shell_targets(command, powershell=False):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    if powershell or os.name == "nt":
        lexer.escape = ""  # a backslash here separates path parts
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    targets, words, expect_redirect = [], [], False

    def flush():
        if not words:
            return
        name = os.path.basename(words[0])
        if name in ("sudo", "command", "env") and len(words) > 1:
            words.pop(0)
            name = os.path.basename(words[0])
        args = [w for w in words[1:] if not w.startswith("-")]
        how = WRITERS.get(name)
        if powershell:
            how = POWERSHELL_WRITERS.get(name.lower(), WRITERS.get(name.lower()))
            args += [w.partition(":")[2] for w in words[1:] if w.startswith("-") and w.partition(":")[2]]  # -Path:x
        if how == "copy":
            targets.append(_copy_destination(words))
        elif name == "sed" and any(w == "-i" or w.startswith("-i") or w == "--in-place" for w in words[1:]):
            targets.extend(args[1:])
        elif name == "dd":
            targets.extend(w[3:] for w in words[1:] if w.startswith("of="))
        elif how == "all":
            targets.extend(args)
        elif how == "last" and args:
            targets.append(args[-1])
        elif how == "first" and args:
            targets.append(args[0])
        words.clear()

    for token in tokens:
        if expect_redirect:
            targets.append(token)
            expect_redirect = False
        elif token in REDIRECTS or (token.endswith(">") and set(token) <= set("&>|0123456789")):
            expect_redirect = True
        elif token and (token in SEPARATORS or set(token) <= set(";&|()<")):
            flush()
        else:
            words.append(token)
    flush()
    found = [t for t in targets if t and t != "/dev/null" and not t.startswith("&")]
    return [t.replace("\\", "/") for t in found] if powershell else found


def write_targets(payload):
    tool = str(payload.get("tool_name", "")).lower()
    tool_input = payload.get("tool_input") or {}
    if tool in FILE_TOOLS:
        value = tool_input.get(FILE_TOOLS[tool])
        return [value] if isinstance(value, str) else []
    if tool in PATCH_TOOLS:
        return PATCH_LINE.findall(str(tool_input.get("command") or tool_input.get("patch") or ""))
    if tool in SHELL_TOOLS or tool in POWERSHELL_TOOLS:
        return _shell_targets(str(tool_input.get("command", "")), tool in POWERSHELL_TOOLS)
    return []


def decide(payload):
    tool_input = payload.get("tool_input") or {}
    cwd = Path(tool_input.get("workdir") or payload.get("cwd") or os.getcwd())
    cache, reasons = {}, []
    for raw in write_targets(payload):
        path = Path(os.path.expanduser(raw))
        target = Path(os.path.normpath(path if path.is_absolute() else cwd / path))
        reason = check_target(target, cache)
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")  # never the Windows code page
        reasons = decide(payload)
    except Exception as exc:  # a broken hook must not block unrelated work
        print(f"gis-plugin protect_sources: {exc}", file=sys.stderr)
        return 0
    if reasons:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "\n".join(reasons),
        }}))  # ASCII escapes: Chinese text survives whatever code page a Windows hook's stdout uses
    return 0


if __name__ == "__main__":
    sys.exit(main())
