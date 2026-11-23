#!/usr/bin/env python3
"""PostToolUse / PreInvocation hook: report defensive, explanatory and disclaimer wording in artifacts just written.

Standard library only. Artifacts are `.svg`, `.pptx` and `.html`. File tools and Codex apply_patch name their targets;
a shell command may write anywhere, so its output options and redirects are read the way protect_sources reads them,
and the project root is scanned for artifacts modified in the last few minutes. The wording list is `artifact_text.json`.
On Antigravity, PostToolUse cannot return feedback to the model, so reports are queued and injected on the next PreInvocation.
"""

import html
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True  # importing the sibling hooks must not leave __pycache__ in the plugin
from _harness import (  # noqa: E402
    drain_pending, enqueue_pending, event_name, inject_message, is_antigravity,
    payload_cwd, session_id, tool_call, write_json,
)
from inject_style import project_root  # noqa: E402
from protect_sources import POWERSHELL_TOOLS, SHELL_TOOLS, shell_cd_dirs, write_targets  # noqa: E402

LIST_FILE = Path(__file__).with_name("artifact_text.json")
SUFFIXES = {".svg", ".pptx", ".html", ".htm"}
MAX_BYTES = 64 * 1024 * 1024

# The shell scan: bounded in age, depth, entries and time so a Bash call stays fast.
SCAN_WINDOW = 15 * 60
SCAN_DEPTH = 8
SCAN_ENTRIES = 20000
SCAN_SECONDS = 1.5
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "venv", "env", "Library"}  # and every dot directory
STATE_TTL = 7 * 86400

NOTE = "图上、页面上只放内容本身；解释、免责、核查用语不进产物，必要的说明放交付说明或讲稿备注。"


def load_rules(path=LIST_FILE):
    doc = json.loads(path.read_text(encoding="utf-8"))
    rules = [(cat["name"], re.compile(p)) for cat in doc["categories"] for p in cat["patterns"]]
    return rules, re.compile(doc["attribution"])


# --- text extraction: each returns [(line, where)] -------------------------------------------------------------

TEXT_EL = re.compile(r"<(?:\w+:)?text\b([^>]*)>(.*?)</(?:\w+:)?text\s*>", re.S)
TSPAN_EL = re.compile(r"<(?:\w+:)?tspan\b[^>]*>(.*?)</(?:\w+:)?tspan\s*>", re.S)
CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _plain(fragment):
    fragment = CDATA.sub(lambda m: html.escape(m.group(1), quote=False), fragment)
    return html.unescape(re.sub(r"<[^>]*>", "", fragment))


def _attr(attrs, name):
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs) or re.search(rf"\b{name}\s*=\s*'([^']*)'", attrs)
    return m.group(1) if m else None


def svg_lines(source):
    """Each <text>, and each <tspan> in it, is a line; a text's lines are also read together. Runs of
    single-character <text> (vertical labels) are read together too."""
    items = []
    for i, m in enumerate(TEXT_EL.finditer(source), 1):
        attrs, body = m.group(1), m.group(2)
        where = f"第 {i} 个 <text>"
        if _attr(attrs, "x") is not None:
            where += f"（x={_attr(attrs, 'x')}, y={_attr(attrs, 'y')}）"
        elif _attr(attrs, "transform"):
            where += f"（{_attr(attrs, 'transform')}）"
        spans = [_plain(t) for t in TSPAN_EL.findall(body)]
        items.append((spans or [_plain(body)], where))
    out = []
    for lines, where in items:
        out += [(line, where) for line in lines]
        if len(lines) > 1:
            out.append(("".join(lines), where + "（各行连读）"))
    i = 0
    while i < len(items):
        j = i
        while j < len(items) and len(items[j][0]) == 1 and len(items[j][0][0].strip()) == 1:
            j += 1
        if j - i > 1:
            out.append(("".join(items[k][0][0].strip() for k in range(i, j)), f"{items[i][1]} 起的 {j - i} 个单字（竖排连读）"))
        i = max(j, i + 1)
    return out


TX_BODY = re.compile(r"<(\w+):txBody\b.*?</\1:txBody>", re.S)
PARA = re.compile(r"<a:p\b[^>]*>.*?</a:p>|<a:p\s*/>", re.S)
RUN_OR_BREAK = re.compile(r"<a:t(?:\s[^>]*)?>(.*?)</a:t>|<a:br\b", re.S)


def _text_bodies(xml, where):
    """Each visual line of each text body; a body's lines are also read together."""
    out = []
    for body in TX_BODY.finditer(xml):
        lines = []
        for para in PARA.findall(body.group(0)):
            text = "".join("\n" if m.group(1) is None else html.unescape(m.group(1)) for m in RUN_OR_BREAK.finditer(para))
            lines += text.split("\n")  # <a:br/> is a line break inside the paragraph
        lines = [line for line in lines if line.strip()]
        out += [(line, where) for line in lines]
        if len(lines) > 1:
            out.append(("".join(lines), where + "（同一文本框连读）"))
    return out


def _slide_order(zf, names):
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    try:
        pres = zf.read("ppt/presentation.xml").decode("utf-8", "replace")
        rels = zf.read("ppt/_rels/presentation.xml.rels").decode("utf-8", "replace")
    except KeyError:
        return slides
    targets = {}
    for tag in re.findall(r"<Relationship\b[^>]*>", rels):
        rid, target = _attr(tag, "Id"), _attr(tag, "Target")
        if rid and target:
            targets[rid] = "ppt/" + target.lstrip("/").removeprefix("ppt/")
    ordered = [targets.get(rid) for rid in re.findall(r"<p:sldId\b[^>]*\br:id=\"([^\"]+)\"", pres)]
    ordered = [n for n in ordered if n in names]
    return ordered + [n for n in slides if n not in ordered]


def pptx_lines(path):
    """Slides, charts and SmartArt drawings; never the notes pages, where explanations belong, nor hidden slides."""
    out = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for number, name in enumerate(_slide_order(zf, names), 1):
            xml = zf.read(name).decode("utf-8", "replace")
            if not re.search(r"<p:sld\b[^>]*\bshow=\"(0|false)\"", xml):
                out += _text_bodies(xml, f"第 {number} 页")
        for name in sorted(names):
            if re.fullmatch(r"ppt/(charts/chart|diagrams/drawing)\d+\.xml", name):
                out += _text_bodies(zf.read(name).decode("utf-8", "replace"), name.removeprefix("ppt/"))
    return out


INLINE = {"a", "span", "strong", "em", "b", "i", "u", "s", "small", "sup", "sub", "code", "mark", "abbr", "q",
          "cite", "time", "font", "wbr", "bdi", "bdo", "kbd", "var", "data", "ruby", "rt", "rp"}
HIDDEN = re.compile(r"<!--.*?-->|<(script|style|template)\b.*?</\1\s*>", re.S | re.I)
TAG = re.compile(r"<\s*/?\s*([A-Za-z][\w:-]*)[^>]*>")


def html_lines(source):
    """Visible text: scripts, styles, templates and comments dropped; every non-inline tag breaks a line."""
    text = TAG.sub(lambda m: "" if m.group(1).lower() in INLINE else "\n", HIDDEN.sub("\n", source))
    return [(line, "页面文字") for line in html.unescape(text).split("\n") if line.strip()]


def artifact_lines(path):
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return pptx_lines(path)
    source = path.read_text(encoding="utf-8", errors="replace")
    return svg_lines(source) if suffix == ".svg" else html_lines(source)


def find_hits(lines, rules, attribution):
    hits, seen = [], set()
    for line, where in lines:
        if not line.strip():
            continue
        tested = attribution.sub("", line, count=1)
        for category, regex in rules:
            m = regex.search(tested)
            if m and (line.strip(), where) not in seen:
                seen.add((line.strip(), where))
                hits.append({"text": line.strip(), "where": where, "match": m.group(0), "category": category})
                break
    return hits


# --- which files -----------------------------------------------------------------------------------------------

def _state_file(key, environ):
    root = Path(environ.get("GIS_PLUGIN_STATE") or Path.home() / ".cache" / "gis-plugin") / "artifact-text"
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in root.glob("*.json"):
        if now - old.stat().st_mtime > STATE_TTL:
            old.unlink(missing_ok=True)
    return root / (re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:120] + ".json")


def recent_artifacts(root, now, budget=SCAN_SECONDS):
    """Artifacts under `root` modified within SCAN_WINDOW, newest first, within the scan bounds."""
    cutoff, deadline, visited, found = now - SCAN_WINDOW, time.monotonic() + budget, 0, []
    stack = [(root, 0)]
    while stack and visited < SCAN_ENTRIES and time.monotonic() < deadline:
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    name = entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < SCAN_DEPTH and not name.startswith(".") and name not in SKIP_DIRS:
                                stack.append((entry.path, depth + 1))
                        elif os.path.splitext(name)[1].lower() in SUFFIXES:
                            st = entry.stat()
                            if st.st_mtime >= cutoff:
                                found.append((st.st_mtime, Path(entry.path)))
                    except OSError:
                        continue
        except OSError:
            continue
    return [path for _, path in sorted(found, reverse=True)]


def candidates(payload, environ, now):
    """Artifacts to check: (path, explicit). Explicit targets are always checked; scanned ones once per version."""
    cwd = payload_cwd(payload)
    tool, _ = tool_call(payload)
    if is_antigravity(payload) and payload.get("error") and tool not in SHELL_TOOLS and tool not in POWERSHELL_TOOLS:
        return [], []
    paths = []
    for raw in write_targets(payload):
        path = Path(os.path.expanduser(raw))
        path = Path(os.path.normpath(path if path.is_absolute() else cwd / path))
        if path.suffix.lower() in SUFFIXES and path not in paths:
            paths.append(path)
    scanned = []
    if tool in SHELL_TOOLS or tool in POWERSHELL_TOOLS:
        roots = []
        for directory in [cwd, *shell_cd_dirs(payload)]:
            if not directory.is_dir():
                continue
            root = project_root(directory) or directory
            if root not in (Path.home(), Path(root.anchor)) and root not in roots:  # never walk a whole home directory or disk
                roots.append(root)
        for root in roots:
            for found in recent_artifacts(root, now):
                if found not in paths and found not in scanned:
                    scanned.append(found)
    return paths, scanned


def run(payload, environ, now=None):
    ag = is_antigravity(payload)
    ev = event_name(payload)
    key = session_id(payload)
    if not key:
        key = "cwd-" + re.sub(r"[^A-Za-z0-9]", "_", str(payload_cwd(payload)))[-100:]
    if ag and ev == "PreInvocation":
        pending = [item for item in drain_pending("artifact-text", key, environ) if isinstance(item, str) and item.strip()]
        return "\n\n".join(dict.fromkeys(pending)) if pending else None
    now = time.time() if now is None else now
    explicit, scanned = candidates(payload, environ, now)
    if not explicit and not scanned:
        return None
    state_path = _state_file(key, environ)
    try:
        seen = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    rules, attribution = load_rules()
    report = []
    for path, is_explicit in [(p, True) for p in explicit] + [(p, False) for p in scanned]:
        try:
            st = path.stat()
        except OSError:
            continue  # removed, or never written
        version = f"{st.st_mtime_ns}:{st.st_size}"
        if not path.is_file() or st.st_size > MAX_BYTES or (not is_explicit and seen.get(str(path)) == version):
            continue
        seen[str(path)] = version
        try:
            hits = find_hits(artifact_lines(path), rules, attribution)
        except (OSError, zipfile.BadZipFile, KeyError, ValueError):
            continue  # not a readable artifact (still being written, or misnamed)
        if hits:
            report.append((path, hits))
    cutoff = (now - STATE_TTL) * 1e9
    seen = {p: v for p, v in seen.items() if float(v.split(":")[0]) >= cutoff}
    write_json(state_path, seen)
    formatted = format_report(report) if report else None
    if ag and ev == "PostToolUse":
        if formatted:
            tag = str((payload.get("toolCall") or {}).get("id") or "")
            enqueue_pending("artifact-text", key, formatted, environ, tag=tag)
        return None
    return formatted


def format_report(report, limit=20):
    lines = ["gis-plugin hook 检查了刚写出的产物，下面的文字不该出现在产物里。文件已经写出，改掉这些文字后重新生成或保存："]
    for path, hits in report:
        lines.append(str(path))
        for hit in hits[:limit]:
            lines.append(f"  - “{hit['text']}”（{hit['where']}）：命中“{hit['match']}”，{hit['category']}")
        if len(hits) > limit:
            lines.append(f"  - 另有 {len(hits) - limit} 处")
    lines += [NOTE, f"用语清单：{LIST_FILE}（GIS 系列共用）。"]
    return "\n".join(lines)


def main():
    payload = {}
    reason = None
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")  # never the Windows code page
        reason = run(payload, os.environ)
    except Exception as exc:  # a broken hook must not disturb the session
        print(f"gis-plugin check_artifact_text: {exc}", file=sys.stderr)
    if is_antigravity(payload):
        if event_name(payload) == "PostToolUse":
            print("{}")
        elif reason:
            print(json.dumps(inject_message(reason)))
    elif reason:
        print(json.dumps({"decision": "block", "reason": reason}))  # ASCII escapes survive any Windows code page
    return 0


if __name__ == "__main__":
    sys.exit(main())
