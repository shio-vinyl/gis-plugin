#!/usr/bin/env python3
"""UserPromptSubmit / PostToolUse hook: add gis-kit describe cards for GIS files mentioned. Standard library only.

The shell never reads GIS data: cards come from `$GIS_KIT_CMD describe <path> --json`. Each file is
described once per session until its size or mtime changes. Cards state facts, never instructions.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

SUFFIXES = ("gpkg", "shp", "geojson", "fgb", "gml", "kml", "gdb", "tif", "tiff", "vrt", "img", "asc", "jp2", "nc")
PATH_RE = re.compile(r"([^\s\"'`<>|;,，。、：:（）()\[\]{}]+\.(?:" + "|".join(SUFFIXES) + r"))(?![A-Za-z0-9_])", re.I)
MAX_FILES = 3
DESCRIBE_TIMEOUT = 8
FIELD_LIMIT = 30
LAYER_LIMIT = 10
STATE_TTL = 7 * 86400


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
    if not raw:
        return None
    paths = candidates(payload)
    if not paths:
        return None
    state_path = _state_file(str(payload.get("session_id") or "no-session"))
    try:
        seen = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    command, cards = shlex.split(raw), []
    for path in paths:
        if len(cards) >= MAX_FILES:
            break
        revision = _revision(path)
        if seen.get(str(path)) == revision:
            continue
        card = describe(command, path)
        if card:
            cards.append(card)
            seen[str(path)] = revision
    if not cards:
        return None
    state_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return "\n\n".join(cards)


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
