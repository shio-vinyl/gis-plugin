"""Host payload normalization and two-stage hook queue shared by gis-plugin hooks. Standard library only."""

import json
import os
import re
import time
from pathlib import Path

STATE_TTL = 7 * 86400


def is_antigravity(payload):
    """Antigravity hook payloads use camelCase keys (`hookEventName`, `toolCall`, `conversationId`)."""
    return isinstance(payload, dict) and any(k in payload for k in ("hookEventName", "toolCall", "conversationId"))


def event_name(payload):
    return str(payload.get("hookEventName") or payload.get("hook_event_name") or "")


def session_id(payload):
    value = payload.get("conversationId") or payload.get("session_id")
    return str(value) if value else ""


def tool_call(payload):
    """Return `(tool_name_lower, args_dict)` across Claude Code, Codex, DeepSeek Harness and Antigravity."""
    tc = payload.get("toolCall")
    if isinstance(tc, dict):
        args = tc.get("args")
        return str(tc.get("name") or "").lower(), args if isinstance(args, dict) else {}
    tool_input = payload.get("tool_input")
    return str(payload.get("tool_name") or "").lower(), tool_input if isinstance(tool_input, dict) else {}


def payload_cwd(payload):
    """Agent working directory for the hook event (never the hook process's plugin root when the payload names one)."""
    _, args = tool_call(payload)
    raw = args.get("workdir") or payload.get("cwd")
    if not raw:
        workspaces = payload.get("workspacePaths")
        if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str):
            raw = workspaces[0]
    return Path(os.path.abspath(raw or os.getcwd()))


def inject_message(text):
    """Antigravity PreInvocation output injecting one systemMessage step."""
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}


def _state_root(environ):
    return Path(environ.get("GIS_PLUGIN_STATE") or Path.home() / ".cache" / "gis-plugin")


def _safe_key(key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:120] or "no-session"


def write_json(path, data):
    """Write JSON atomically so parallel hooks cannot leave a half-written state file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _pending_dir(kind, session, environ):
    root = _state_root(environ) / "pending" / kind
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in root.iterdir():
        try:
            if now - old.stat().st_mtime > STATE_TTL:
                if old.is_dir():
                    for child in old.iterdir():
                        child.unlink(missing_ok=True)
                    old.rmdir()
                else:
                    old.unlink(missing_ok=True)
        except OSError:
            continue
    return root / _safe_key(session)


def enqueue_pending(kind, session, item, environ, tag=""):
    """Queue one item for the next PreInvocation; one file per event avoids races between parallel PostToolUse hooks."""
    directory = _pending_dir(kind, session, environ)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"-{_safe_key(tag)[:40]}" if tag else ""
    name = f"{time.time_ns()}-{os.getpid()}{suffix}"
    tmp = directory / f".{name}.tmp"
    final = directory / f"{name}.json"
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)


def drain_pending(kind, session, environ):
    """Read and remove all pending items queued for `session`, in creation order."""
    directory = _state_root(environ) / "pending" / kind / _safe_key(session)
    if not directory.is_dir():
        return []
    items = []
    for entry in sorted(directory.glob("*.json")):
        try:
            items.append(json.loads(entry.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        entry.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass
    return items
