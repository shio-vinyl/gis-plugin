#!/usr/bin/env python3
"""Run gis-plugin evals: each case with and without the shell, then grade the outcome. Standard library only.

Every run copies the case fixture into a fresh directory under --out (outside the repo), runs the harness
there, grades it and removes the directory unless --keep. The report is written to <out>/report.json.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).resolve().parent / "cases"
PLUGIN_ID = "gis-plugin@gis-plugin"
VARIANTS = ("with", "without")
CHECKS = ("file_unchanged", "answer_json", "answer_contains")
TIMEOUT = 600


class CaseError(Exception):
    pass


def load_case(directory):
    try:
        case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CaseError(f"{directory.name}: 无法读取 case.json：{exc}") from None
    for key in ("id", "prompt", "checks"):
        if key not in case:
            raise CaseError(f"{directory.name}: 缺少 {key}")
    if case["id"] != directory.name:
        raise CaseError(f"{directory.name}: id 须与目录名一致")
    if not isinstance(case["checks"], list) or not case["checks"]:
        raise CaseError(f"{case['id']}: checks 须为非空数组")
    for check in case["checks"]:
        if check.get("type") not in CHECKS:
            raise CaseError(f"{case['id']}: 未知检查 {check.get('type')!r}")
        if check["type"] == "file_unchanged" and not (directory / "fixture" / check.get("path", "")).is_file():
            raise CaseError(f"{case['id']}: file_unchanged 指向的夹具文件不存在：{check.get('path')}")
    if "tools" in case and not isinstance(case["tools"], list):
        raise CaseError(f"{case['id']}: tools 须为数组")
    case["dir"] = directory
    return case


def load_cases(names=None):
    found = [load_case(d) for d in sorted(CASES.iterdir()) if d.is_dir()]
    if names:
        unknown = set(names) - {c["id"] for c in found}
        if unknown:
            raise CaseError(f"没有这些用例：{', '.join(sorted(unknown))}")
        found = [c for c in found if c["id"] in names]
    return found


def last_json(text):
    """The last JSON object in an answer: a fenced block or a bare `{...}` line."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) + re.findall(r"^\s*(\{.*\})\s*$", text, re.M)
    for raw in sorted(candidates, key=text.rfind, reverse=True):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _same(actual, expected):
    options = expected if isinstance(expected, list) else [expected]
    return any(str(actual).strip().lower() == str(option).strip().lower() for option in options)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def grade(case, workdir, answer):
    results = []
    for check in case["checks"]:
        kind = check["type"]
        if kind == "file_unchanged":
            before = digest(case["dir"] / "fixture" / check["path"])
            after = digest(workdir / check["path"])
            ok, detail = before == after, "未改动" if before == after else ("已删除" if after is None else "已改动")
        elif kind == "answer_json":
            got = last_json(answer)
            if got is None:
                ok, detail = False, "答案中没有 JSON 对象"
            else:
                wrong = {k: got.get(k) for k, v in check["expect"].items() if not _same(got.get(k), v)}
                ok, detail = not wrong, "一致" if not wrong else f"不符：{json.dumps(wrong, ensure_ascii=False)}"
        else:
            hits = [s for s in check["any"] if s.lower() in answer.lower()]
            ok, detail = bool(hits), f"命中 {hits}" if hits else "均未出现"
        results.append({"type": kind, "ok": ok, "detail": detail})
    return results


def cc_command(case, variant, model):
    """`claude -p` with the installed copy of the plugin disabled; `with` loads this checkout instead."""
    command = ["claude", "-p", case["prompt"], "--output-format", "json", "--no-session-persistence",
               "--settings", json.dumps({"enabledPlugins": {PLUGIN_ID: False}})]
    if "tools" in case:
        command += ["--tools", ",".join(case["tools"])]
    else:
        command += ["--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep"]
    if variant == "with":
        command += ["--plugin-dir", str(ROOT)]
    if model:
        command += ["--model", model]
    return command


def run_once(case, variant, workdir, model):
    shutil.copytree(case["dir"] / "fixture", workdir)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    start = time.time()
    try:
        proc = subprocess.run(cc_command(case, variant, model), cwd=workdir, env=env, capture_output=True,
                              text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"error": f"超时（{TIMEOUT}s）", "seconds": round(time.time() - start, 1)}
    record = {"seconds": round(time.time() - start, 1), "exit": proc.returncode}
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        record["error"] = (proc.stderr.strip() or proc.stdout.strip())[-500:] or "无输出"
        return record
    answer = str(out.get("result") or "")
    record.update(answer=answer, turns=out.get("num_turns"), cost_usd=out.get("total_cost_usd"),
                  checks=grade(case, workdir, answer))
    record["passed"] = all(c["ok"] for c in record["checks"])
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="报告与临时工作目录（须在仓库外）")
    parser.add_argument("--case", action="append", help="只跑指定用例，可重复")
    parser.add_argument("--variant", choices=VARIANTS, action="append", help="默认两种都跑")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model")
    parser.add_argument("--keep", action="store_true", help="保留工作目录")
    parser.add_argument("--list", action="store_true", help="只列出用例")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.case)
    except CaseError as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for case in cases:
            print(f"{case['id']}\t{case.get('title', '')}")
        return 0
    out = Path(args.out).expanduser().resolve()
    if out == ROOT or ROOT in out.parents:
        print("evals: --out 须在仓库外", file=sys.stderr)
        return 2
    if not shutil.which("claude"):
        print("evals: 找不到 claude 命令", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for case in cases:
        for variant in args.variant or VARIANTS:
            for n in range(1, args.repeat + 1):
                workdir = out / "work" / f"{case['id']}-{variant}-{n}"
                shutil.rmtree(workdir, ignore_errors=True)
                record = {"case": case["id"], "variant": variant, "repeat": n, **run_once(case, variant, workdir, args.model)}
                runs.append(record)
                status = "PASS" if record.get("passed") else ("ERROR" if "error" in record else "FAIL")
                print(f"{status}\t{case['id']}\t{variant}#{n}\t{record['seconds']}s", flush=True)
                if not args.keep:
                    shutil.rmtree(workdir, ignore_errors=True)
    summary = {}
    for record in runs:
        cell = summary.setdefault(record["case"], {}).setdefault(record["variant"], [0, 0])
        cell[0] += bool(record.get("passed"))
        cell[1] += 1
    report = {"harness": "cc", "model": args.model, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "summary": {case: {v: f"{p}/{t}" for v, (p, t) in cells.items()} for case, cells in summary.items()},
              "runs": runs}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not args.keep:
        shutil.rmtree(out / "work", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
