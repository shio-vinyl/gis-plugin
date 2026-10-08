#!/usr/bin/env python3
"""Check GIS engines via `<engine> capabilities --json`. Standard library only."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

ENGINES = (
    # (engine, env var, minimum engine_version)
    ("gis-kit", "GIS_KIT_CMD", (0, 1, 0)),
    ("gis-view", "GIS_VIEW_CMD", (0, 2, 0)),
    ("gis-composer", "GIS_COMPOSER_CMD", (0, 1, 0)),
)
SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 20
STDERR_MAX_CHARS = 500

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
TOP_FIELDS = ("contract", "schema_version", "engine", "engine_version", "commands", "contracts", "features")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_versions(value, where):
    if not isinstance(value, list) or not value:
        return [f"{where} 须为非空数组"]
    if not all(_is_int(v) and v >= 1 for v in value):
        return [f"{where} 只能包含 >= 1 的整数"]
    if len(set(value)) != len(value):
        return [f"{where} 有重复值"]
    return []


def validate_capabilities(doc):
    """Return problems against contracts/capabilities.schema.json (schema_version 1)."""
    if not isinstance(doc, dict):
        return ["输出不是 JSON 对象"]
    problems = [f"缺少字段 {k}" for k in TOP_FIELDS if k not in doc]
    problems += [f"未知字段 {k}" for k in doc if k not in TOP_FIELDS]
    if "contract" in doc and doc["contract"] != "capabilities":
        problems.append("contract 须为 capabilities")
    if "schema_version" in doc and not (_is_int(doc["schema_version"]) and doc["schema_version"] == SCHEMA_VERSION):
        problems.append(f"schema_version 须为 {SCHEMA_VERSION}，实为 {doc['schema_version']!r}")
    if "engine" in doc and not (isinstance(doc["engine"], str) and NAME_RE.match(doc["engine"])):
        problems.append("engine 格式不符")
    if "engine_version" in doc and not (isinstance(doc["engine_version"], str) and SEMVER_RE.match(doc["engine_version"])):
        problems.append("engine_version 不是 SemVer")
    commands = doc.get("commands", [])
    if not isinstance(commands, list) or not all(isinstance(c, str) and NAME_RE.match(c) for c in commands):
        problems.append("commands 须为子命令名数组")
    elif len(set(commands)) != len(commands):
        problems.append("commands 有重复值")
    contracts = doc.get("contracts", {})
    if not isinstance(contracts, dict):
        problems.append("contracts 须为对象")
    else:
        for name, entry in contracts.items():
            if not NAME_RE.match(name):
                problems.append(f"contracts 键 {name!r} 格式不符")
            if not isinstance(entry, dict) or not entry or set(entry) - {"read", "write"}:
                problems.append(f"contracts.{name} 只能含 read/write 且不能为空")
                continue
            for mode, versions in entry.items():
                problems += _check_versions(versions, f"contracts.{name}.{mode}")
    features = doc.get("features", [])
    if not isinstance(features, list):
        problems.append("features 须为数组")
    else:
        for i, feature in enumerate(features):
            where = f"features[{i}]"
            if not isinstance(feature, dict):
                problems.append(f"{where} 须为对象")
                continue
            if set(feature) - {"name", "available", "reason"}:
                problems.append(f"{where} 有未知字段")
            if not (isinstance(feature.get("name"), str) and NAME_RE.match(feature["name"])):
                problems.append(f"{where}.name 格式不符")
            if not isinstance(feature.get("available"), bool):
                problems.append(f"{where}.available 须为布尔值")
            if "reason" in feature and not isinstance(feature["reason"], str):
                problems.append(f"{where}.reason 须为字符串")
    return problems


def _summary(text):
    text = (text or "").strip()
    return text if len(text) <= STDERR_MAX_CHARS else text[:STDERR_MAX_CHARS] + "…"


def check_engine(engine, env_var, min_version, environ):
    result = {"engine": engine, "env": env_var}
    raw = environ.get(env_var, "").strip()
    if not raw:
        result.update(status="not_configured", message=f"未设置 {env_var}")
        return result
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        result.update(status="error", message=f"{env_var} 无法解析：{exc}")
        return result
    try:
        proc = subprocess.run(
            argv + ["capabilities", "--json"],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        result.update(status="error", message=f"找不到可执行文件：{argv[0]}")
        return result
    except PermissionError:
        result.update(status="error", message=f"无执行权限：{argv[0]}")
        return result
    except subprocess.TimeoutExpired:
        result.update(status="error", message=f"capabilities 超过 {TIMEOUT_SECONDS} 秒未返回")
        return result
    if proc.returncode != 0:
        result.update(
            status="error",
            message=f"capabilities --json 退出码 {proc.returncode}（引擎不可用或未提供 capabilities）",
            stderr=_summary(proc.stderr),
        )
        return result
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        result.update(status="error", message=f"stdout 不是合法 JSON：{exc.msg}", stderr=_summary(proc.stderr))
        return result
    problems = validate_capabilities(doc)
    if problems:
        result.update(status="error", message="capabilities 不符合约定", problems=problems)
        return result
    result["capabilities"] = doc
    if doc["engine"] != engine:
        result.update(status="error", message=f"引擎自报为 {doc['engine']}，与 {env_var} 预期的 {engine} 不符")
        return result
    version = tuple(int(x) for x in SEMVER_RE.match(doc["engine_version"]).groups())
    if version < min_version:
        need = ".".join(map(str, min_version))
        result.update(status="error", message=f"版本 {doc['engine_version']} 低于外壳要求的 {need}")
        return result
    missing = [f["name"] for f in doc["features"] if not f["available"]]
    if missing:
        result.update(status="warn", message="可选能力不可用：" + "、".join(missing))
    else:
        result.update(status="ok", message=f"{engine} {doc['engine_version']}")
    return result


def run(environ):
    return {
        "doctor": "gis-plugin",
        "python": sys.version.split()[0],
        "engines": [check_engine(name, var, minimum, environ) for name, var, minimum in ENGINES],
    }


LABELS = {"ok": "正常", "warn": "部分可用", "not_configured": "未配置", "error": "错误"}


def render_text(report):
    lines = [f"gis-doctor（Python {report['python']}）"]
    for item in report["engines"]:
        lines.append(f"- {item['engine']}：{LABELS[item['status']]} — {item['message']}")
        caps = item.get("capabilities")
        if caps and item["status"] in ("ok", "warn"):
            lines.append(f"    commands: {', '.join(caps['commands']) or '（无）'}")
            for feature in caps["features"]:
                if not feature["available"]:
                    lines.append(f"    {feature['name']}: {feature.get('reason', '不可用')}")
        for problem in item.get("problems", []):
            lines.append(f"    {problem}")
        if item.get("stderr"):
            lines.append(f"    stderr: {item['stderr']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="检查 GIS 引擎是否可用、版本是否兼容。")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)
    report = run(os.environ)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 1 if any(item["status"] == "error" for item in report["engines"]) else 0


if __name__ == "__main__":
    sys.exit(main())
