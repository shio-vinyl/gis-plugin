#!/usr/bin/env python3
"""UserPromptSubmit hook: say once per session where the project's style is recorded. Standard library only.

The project root is the nearest directory at or above the session's working directory that holds
`gis-project.json` or `style/STYLE.md`. When that root has `style/STYLE.md`, one line of fact is added;
otherwise nothing is printed. The file is only checked for existence, never read.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

STYLE = Path("style") / "STYLE.md"
MARKERS = ("gis-project.json", STYLE)
STATE_TTL = 7 * 86400


def project_root(cwd):
    """The nearest directory at or above `cwd` holding a project marker, or None."""
    for base in [cwd, *cwd.parents]:
        if any((base / marker).is_file() for marker in MARKERS):
            return base
    return None


def _state_file(session, environ):
    root = Path(environ.get("GIS_PLUGIN_STATE") or Path.home() / ".cache" / "gis-plugin") / "style-seen"
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in root.glob("*.json"):
        if now - old.stat().st_mtime > STATE_TTL:
            old.unlink(missing_ok=True)
    return root / (re.sub(r"[^A-Za-z0-9_.-]", "_", session) + ".json")


def run(payload, environ):
    cwd = Path(os.path.abspath(payload.get("cwd") or os.getcwd()))
    root = project_root(cwd)
    if root is None or not (root / STYLE).is_file():
        return None
    session = payload.get("session_id")
    if session:  # without a session id there is nothing to remember it by; say it every time rather than never
        state_path = _state_file(str(session), environ)
        try:
            seen = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = []
        if str(root) in seen:
            return None
        state_path.write_text(json.dumps(seen + [str(root)], ensure_ascii=False), encoding="utf-8")
    return (f"本项目（{root}）的样式记录在 style/STYLE.md：颜色、字体，以及它们写到了哪些工具文件。"
            "来源：gis-plugin hook，只检查了这个文件存在，没有读内容；每个会话只说一次。")


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")  # never the Windows code page
        context = run(payload, os.environ)
    except Exception as exc:  # a broken hook must not disturb the session
        print(f"gis-plugin inject_style: {exc}", file=sys.stderr)
        return 0
    if context:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": payload.get("hook_event_name", "UserPromptSubmit"),
            "additionalContext": context,
        }}))  # ASCII escapes: Chinese text survives whatever code page a Windows hook's stdout uses
    return 0


if __name__ == "__main__":
    sys.exit(main())
