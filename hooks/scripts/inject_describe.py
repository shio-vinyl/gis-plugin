#!/usr/bin/env python3
"""UserPromptSubmit / PostToolUse hook: add metadata cards for GIS files mentioned. Standard library only.

The shell never reads GIS data: cards come from `$GIS_KIT_CMD describe <path> --json`, plus the user's
declarations in the nearest `.gis/semantics.json`. Each file is carded once per session until the file or
its declarations change. Cards state facts, never instructions.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing the shared module must not leave __pycache__ in the plugin
from _patterns import glob_regex  # noqa: E402

SUFFIXES = ("gpkg", "shp", "geojson", "fgb", "gml", "kml", "gdb", "tif", "tiff", "vrt", "img", "asc", "jp2", "nc")
PATH_RE = re.compile(r"([^\s\"'`<>|;,，。、：:（）()\[\]{}]+\.(?:" + "|".join(SUFFIXES) + r"))(?![A-Za-z0-9_])", re.I)
MAX_FILES = 3
DESCRIBE_TIMEOUT = 8
FIELD_LIMIT = 30
LAYER_LIMIT = 10
STATE_TTL = 7 * 86400
# Hosts may show additionalContext without saying where it came from; state the source as a fact.
SOURCE_LINE = ("来源：gis-plugin hook。`[gis-kit describe]` 段是在本机对文件实际运行 `gis-kit describe --json` 得到的元数据；"
               "`[semantics]` 段转述用户在 `.gis/semantics.json` 中的声明。每个文件在会话中只注入一次，文件或声明变化后重新注入。")
SEMANTICS = Path(".gis") / "semantics.json"
KINDS = {"total": "总量", "density": "密度", "ratio": "比率", "category": "类别"}


def _texts(payload):
    if payload.get("hook_event_name") == "UserPromptSubmit":
        return [str(payload.get("prompt") or "")]
    tool_input = payload.get("tool_input") or {}
    return [v for v in tool_input.values() if isinstance(v, str)]


def engine_settings(environ):
    """GIS_* settings: environment variables win over the shared file ~/.config/gis-plugin/engines.env."""
    path = environ.get("GIS_PLUGIN_CONFIG") or os.path.join(
        environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gis-plugin", "engines.env")
    settings = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                key, value = key.strip(), value.strip()
                if sep and key.startswith("GIS_"):
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    settings[key] = value
    except OSError:
        pass
    settings.update({k: v for k, v in environ.items() if k.startswith("GIS_") and v.strip()})
    return settings


def candidates(payload):
    """Existing GIS paths in the prompt or tool input, in order of appearance."""
    tool_input = payload.get("tool_input") or {}
    cwd = Path(tool_input.get("workdir") or payload.get("cwd") or os.getcwd())
    found = []
    for text in _texts(payload):
        for match in PATH_RE.finditer(text):
            raw = match.group(1)
            # Prose may run straight into a path ("看看data/a.shp"): drop leading characters until it exists.
            for start in range(len(raw)):
                piece = os.path.expanduser(raw[start:])
                path = Path(os.path.normpath(piece if os.path.isabs(piece) else cwd / piece))
                if path.exists():
                    if path not in found:
                        found.append(path)
                    break
                if raw[start] == "/":
                    break
    return found


def _state_file(session):
    root = Path(os.environ.get("GIS_PLUGIN_STATE") or Path.home() / ".cache" / "gis-plugin") / "describe-seen"
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in root.glob("*.json"):
        if now - old.stat().st_mtime > STATE_TTL:
            old.unlink(missing_ok=True)
    return root / (re.sub(r"[^A-Za-z0-9_.-]", "_", session) + ".json")


def _revision(path):
    stat = path.stat()
    return [stat.st_size if path.is_file() else None, stat.st_mtime]


def _number(value):
    return f"{value:.12g}" if isinstance(value, float) else str(value)  # no 2.9988e+06 for projected coordinates


def _crs(crs):
    if not crs:
        return "无 CRS"
    kind = "地理" if crs.get("geographic") else "投影"
    return f"CRS {crs.get('id') or '无代码'} {crs.get('name', '')}（{kind}，单位 {crs.get('units') or '未知'}）"


def _extent(extent):
    return "范围 [" + ", ".join(_number(v) for v in extent) + "]" if extent else "范围未知"


def render(card):
    head = f"[gis-kit describe] {card['path']} — {card.get('driver', '?')}，"
    lines = []
    if card.get("kind") == "raster":
        r = card.get("raster") or {}
        dtypes = sorted(set(r.get("dtypes") or []))
        nodata = sorted({"未设置" if v is None else _number(v) for v in (r.get("nodata") or [])})
        res = r.get("resolution")
        lines.append(head + "栅格")
        lines.append(f"· {r.get('width')}×{r.get('height')}，{r.get('band_count')} 个波段 {'/'.join(dtypes)}；"
                     f"NoData {'/'.join(nodata) or '未设置'}；"
                     f"分辨率 {('×'.join(_number(v) for v in res)) if res else '非规则网格'}；"
                     f"{_crs(r.get('crs'))}；{_extent(r.get('extent'))}")
    else:
        layers = card.get("layers") or []
        total = card.get("layer_count", len(layers))
        lines.append(head + f"矢量，图层 {total} 个")
        for layer in layers[:LAYER_LIMIT]:
            count = layer.get("feature_count")
            lines.append(f"· {layer['name']}：{layer.get('geometry_type') or '无几何'}，"
                         f"{'要素数未知' if count is None else f'{count} 个要素'}；"
                         f"{_crs(layer.get('crs'))}；{_extent(layer.get('extent'))}")
            fields = layer.get("fields") or []
            shown = ", ".join(f"{f['name']} {f['type']}" for f in fields[:FIELD_LIMIT])
            more = layer.get("field_count", len(fields)) - min(len(fields), FIELD_LIMIT)
            lines.append(f"  字段 {layer.get('field_count', len(fields))} 个：{shown}" + (f" 等（另 {more} 个未列出）" if more > 0 else ""))
        if total > min(len(layers), LAYER_LIMIT):
            lines.append(f"· 另有 {total - min(len(layers), LAYER_LIMIT)} 个图层未列出")
    for warning in card.get("warnings") or []:
        lines.append(f"注意：{warning.get('message', warning.get('code'))}")
    return "\n".join(lines)


class SemanticsError(Exception):
    pass


def find_semantics(path):
    """The nearest `.gis/semantics.json` above a data path, or None."""
    for base in path.parents:
        if (base / SEMANTICS).is_file():
            return base / SEMANTICS
    return None


def _meanings(table, where, bands=False):
    if not isinstance(table, dict) or not table:
        raise SemanticsError(f"{where} 须为非空对象")
    for key, meaning in table.items():
        if bands and not re.fullmatch(r"[1-9][0-9]*", key):
            raise SemanticsError(f"{where} 的键须为从 1 开始的波段号：{key}")
        if not isinstance(meaning, dict) or meaning.get("kind") not in KINDS:
            raise SemanticsError(f"{where}.{key}.kind 须为 {'/'.join(KINDS)} 之一")
        for name in ("unit", "note"):
            if name in meaning and not (isinstance(meaning[name], str) and meaning[name].strip()):
                raise SemanticsError(f"{where}.{key}.{name} 须为非空字符串")
    return table


def load_semantics(registry):
    try:
        doc = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SemanticsError(f"无法读取：{exc}") from None
    if not isinstance(doc, dict) or doc.get("contract") != "semantics" or doc.get("schema_version") != 1:
        raise SemanticsError("须为 contract=semantics、schema_version=1 的对象")
    datasets = doc.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise SemanticsError("datasets 须为非空数组")
    entries = []
    for i, entry in enumerate(datasets):
        where = f"datasets[{i}]"
        match = entry.get("match") if isinstance(entry, dict) else None
        if not isinstance(match, str) or not match.strip() or match.startswith("/") or ".." in Path(match).parts:
            raise SemanticsError(f"{where}.match 须为相对路径模式且不含 ..")
        if "fields" not in entry and "bands" not in entry:
            raise SemanticsError(f"{where} 须含 fields 或 bands")
        layer = entry.get("layer")
        if layer is not None and not (isinstance(layer, str) and layer.strip()):
            raise SemanticsError(f"{where}.layer 须为非空字符串")
        fields = _meanings(entry["fields"], f"{where}.fields") if "fields" in entry else {}
        bands = _meanings(entry["bands"], f"{where}.bands", bands=True) if "bands" in entry else {}
        entries.append((glob_regex(match.rstrip("/")), layer, fields, bands))
    return entries


def _meaning(meaning):
    text = KINDS[meaning["kind"]] + f"（{meaning['kind']}）"
    if meaning.get("unit"):
        text += f"，单位 {meaning['unit']}"
    if meaning.get("note"):
        text += f"；用户备注“{meaning['note'][:200]}”"
    return text


def semantics_card(path, registry):
    """Declarations matching one data path, later entries overriding earlier ones; None when nothing matches."""
    try:
        entries = load_semantics(registry)
    except SemanticsError as exc:
        return f"[semantics] {path} — {registry} 无效：{exc}"
    rel = path.relative_to(registry.parent.parent).as_posix()
    declared = {}
    for regex, layer, fields, bands in entries:
        if not regex.match(rel):
            continue
        for name, meaning in fields.items():
            declared[("field", layer, name)] = meaning
        for band, meaning in bands.items():
            declared[("band", None, int(band))] = meaning
    if not declared:
        return None
    lines = [f"[semantics] {path} — 用户声明于 {registry}"]
    for (what, layer, name), meaning in sorted(declared.items(), key=lambda item: (item[0][0], item[0][1] or "", str(item[0][2]))):
        if what == "band":
            lines.append(f"· 波段 {name}：{_meaning(meaning)}")
        else:
            lines.append(f"· {f'图层 {layer} ' if layer else ''}字段 {name}：{_meaning(meaning)}")
    return "\n".join(lines)


def describe(command, path):
    try:
        proc = subprocess.run(command + ["describe", str(path), "--json"], capture_output=True, text=True,
                              timeout=DESCRIBE_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        message = (proc.stderr.strip().splitlines() or ["未知错误"])[-1]
        return f"[gis-kit describe] {path} — 无法读取：{message[:300]}"
    card = json.loads(proc.stdout)
    if card.get("contract") != "describe" or card.get("schema_version") != 1:
        return None
    return render(card)


def run(payload, environ):
    raw = engine_settings(environ).get("GIS_KIT_CMD", "").strip()
    command = shlex.split(raw) if raw else None
    paths = candidates(payload)
    if not paths:
        return None
    state_path = _state_file(str(payload.get("session_id") or "no-session"))
    try:
        seen = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    cards = []
    for path in paths:
        if len(cards) >= MAX_FILES:
            break
        registry = find_semantics(path)
        revision = [_revision(path), _revision(registry) if registry else None]
        if seen.get(str(path)) == revision:
            continue
        parts = [describe(command, path) if command else None, semantics_card(path, registry) if registry else None]
        parts = [part for part in parts if part]
        if parts:
            cards.append("\n".join(parts))
            seen[str(path)] = revision
    if not cards:
        return None
    state_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return SOURCE_LINE + "\n\n" + "\n\n".join(cards)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        context = run(payload, os.environ)
    except Exception as exc:  # a broken hook must not disturb the session
        print(f"gis-plugin inject_describe: {exc}", file=sys.stderr)
        return 0
    if context:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": payload.get("hook_event_name", "PostToolUse"),
            "additionalContext": context,
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
