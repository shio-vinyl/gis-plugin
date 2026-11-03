#!/usr/bin/env python3
"""Check GIS engines via `<engine> capabilities --json`, the engine skills installed in each harness against
their source repositories, and whether the hook command runs. Standard library only; never installs or updates anything."""

import argparse
import difflib
import filecmp
import json
import ntpath
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINES = (
    # (engine, env var, minimum engine_version)
    ("gis-kit", "GIS_KIT_CMD", (0, 1, 0)),
    ("gis-view", "GIS_VIEW_CMD", (0, 2, 0)),
    ("gis-composer", "GIS_COMPOSER_CMD", (0, 1, 0)),
)
SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 20
STDERR_MAX_CHARS = 500
# Contract versions the shell itself reads (hooks).
SHELL_READS = {"describe": [1], "semantics": [1], "sources": [1]}

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
TOP_FIELDS = ("contract", "schema_version", "engine", "engine_version", "commands", "contracts", "features")
LIST_MAX = 10
_UPDATER = Path(__file__).resolve().parents[3] / "scripts" / "update_engine_skills.py"
UPDATE_SCRIPT = str(_UPDATER) if _UPDATER.is_file() else "<gis-plugin>/scripts/update_engine_skills.py"
APP_DIRS = (Path("/Applications"), Path.home() / "Applications")
BRIDGE = "@deepseek-ai/dsh-hooks-claude-code"
BRIDGE_PROTOCOL = "@deepseek-ai/dsh-hook-protocol"
BRIDGE_LINE = re.compile(r"^\s*(?:-\s*)?name:\s*['\"]?" + re.escape(BRIDGE) + r"['\"]?\s*(?:#.*)?$", re.M)
HOOKS_FILE = Path(__file__).resolve().parents[3] / "hooks" / "hooks.json"
POWERSHELL_ARGS = ("-NoLogo", "-NoProfile", "-NonInteractive", "-Command")


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
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" and value[0] not in value[1:-1]:
                        value = value[1:-1]
                    settings[key] = value
    except OSError:
        pass
    settings.update({k: v for k, v in environ.items() if k.startswith("GIS_") and v.strip()})
    return settings


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
    """Return problems against contracts/capabilities.schema.json (schema_version 1); unknown fields are ignored."""
    if not isinstance(doc, dict):
        return ["输出不是 JSON 对象"]
    problems = [f"缺少字段 {k}" for k in TOP_FIELDS if k not in doc]
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
            if not isinstance(entry, dict) or not entry:
                problems.append(f"contracts.{name} 须为非空对象")
                continue
            for mode in ("read", "write"):
                if mode in entry:
                    problems += _check_versions(entry[mode], f"contracts.{name}.{mode}")
    features = doc.get("features", [])
    if not isinstance(features, list):
        problems.append("features 须为数组")
    else:
        for i, feature in enumerate(features):
            where = f"features[{i}]"
            if not isinstance(feature, dict):
                problems.append(f"{where} 须为对象")
                continue
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


def split_command(command, windows=os.name == "nt"):
    """Split like a shell; on Windows a backslash is a path separator, not an escape. Quotes go either way."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    if windows:
        lexer.escape = ""
    return list(lexer)


def check_engine(engine, env_var, min_version, environ):
    result = {"engine": engine, "env": env_var}
    raw = environ.get(env_var, "").strip()
    if not raw:
        result.update(status="not_configured", message=f"未设置 {env_var}（环境变量或 engines.env）")
        return result
    try:
        argv = split_command(raw)
    except ValueError as exc:
        result.update(status="error", message=f"{env_var} 无法解析：{exc}")
        return result
    try:
        proc = subprocess.run(
            argv + ["capabilities", "--json"],
            capture_output=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
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


def check_contracts(engines):
    """Pair every writer of a contract with every reader (engines and the shell) and look for a shared version."""
    writers, readers = {}, {name: [("gis-plugin", versions)] for name, versions in SHELL_READS.items()}
    for item in engines:
        for name, entry in (item.get("capabilities") or {}).get("contracts", {}).items():
            if entry.get("write"):
                writers.setdefault(name, []).append((item["engine"], entry["write"]))
            if entry.get("read"):
                readers.setdefault(name, []).append((item["engine"], entry["read"]))
    pairs = []
    for name in sorted(writers):
        for writer, written in writers[name]:
            for reader, read in readers.get(name, []):
                if reader == writer:
                    continue
                shared = sorted(set(written) & set(read))
                pairs.append({"contract": name, "writer": writer, "reader": reader, "versions": shared,
                              "status": "ok" if shared else "error",
                              "message": f"v{shared[-1]}" if shared else f"写 {written}，读 {read}，无共同版本"})
    return pairs


def skill_dirs(environ):
    """Where each harness keeps skills; same list as scripts/update_engine_skills.py."""
    home = Path(environ.get("HOME") or os.path.expanduser("~"))
    return (
        ("CC", Path(environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "skills"),
        ("Codex", Path(environ.get("CODEX_HOME") or home / ".codex") / "skills"),
        ("agents", home / ".agents" / "skills"),
        ("dsh", home / ".dsh" / "skills"),
    )


def source_repo(skill, command):
    """The directory holding `<skill>`'s SKILL.md, found by walking up from the paths in its engine command."""
    try:
        argv = split_command(command)
    except ValueError:
        return None
    for token in argv:
        path = Path(token).expanduser()
        if not path.exists():
            continue
        for parent in [path, *path.parents]:
            entry = parent / "SKILL.md"
            if entry.is_file() and f"name: {skill}\n" in entry.read_text(encoding="utf-8"):
                return parent
    return None


def _tracked_files(repo):
    """Files tracked by git in the source repository that exist in its work tree, or None."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True,
                              timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode:
        return None
    names = [n for n in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
    return [n for n in names if (repo / n).is_file()]


def _entry_matches(entry, source):
    """A Codex entry is the source SKILL.md with at most one line (where the runtime lives) rewritten."""
    ops = [op for op in difflib.SequenceMatcher(None, entry, source, autojunk=False).get_opcodes() if op[0] != "equal"]
    return not ops or (len(ops) == 1 and ops[0][0] == "replace" and ops[0][2] - ops[0][1] == 1 == ops[0][4] - ops[0][3])


def check_skill(skill, path, repo):
    """Is the installed skill at `path` a link, or a copy in step with its source repository?"""
    if path.is_symlink():
        return {"kind": "link", "status": "ok", "message": f"软链 → {os.readlink(path)}"}
    if [p.name for p in path.iterdir() if p.name != ".DS_Store"] == ["SKILL.md"]:
        result = {"kind": "entry"}
        if repo is None:
            return {**result, "status": "unknown", "message": "找不到源仓库，未对比（检查 engines.env 中的引擎命令）"}
        entry = (path / "SKILL.md").read_text(encoding="utf-8").splitlines()
        if _entry_matches(entry, (repo / "SKILL.md").read_text(encoding="utf-8").splitlines()):
            return {**result, "status": "ok", "message": "单文件入口，与源 SKILL.md 一致"}
        return {**result, "status": "warn", "message": f"单文件入口与 {repo / 'SKILL.md'} 不同（不止运行时位置那一行）",
                "different": ["SKILL.md"]}
    result = {"kind": "copy"}
    if repo is None:
        return {**result, "status": "unknown", "message": "找不到源仓库，未对比（检查 engines.env 中的引擎命令）"}
    files = _tracked_files(repo)
    if files is None:
        return {**result, "status": "unknown", "message": f"无法列出 {repo} 的 git 文件，未对比"}
    missing = [n for n in files if not (path / n).is_file()]
    different = [n for n in files if n not in missing and not filecmp.cmp(repo / n, path / n, shallow=False)]
    if not missing and not different:
        return {**result, "status": "ok", "message": f"副本，与 {repo} 一致"}
    return {**result, "status": "warn", "message": f"副本落后于 {repo}：缺少 {len(missing)} 个、不同 {len(different)} 个文件",
            "missing": missing, "different": different}


def check_skills(settings, environ):
    """Every engine skill installed in a harness; links and copies in step with the source come back as ok."""
    results = []
    for engine, env_var, _ in ENGINES:
        repo = source_repo(engine, settings.get(env_var, ""))
        for harness, base in skill_dirs(environ):
            path = base / engine
            if not (path.is_symlink() or path.is_dir()):
                continue
            results.append({"skill": engine, "harness": harness, "path": str(path), **check_skill(engine, path, repo)})
    return results


def dsh_app_version():
    """The DeepSeek Harness App's version from its Info.plist; None where it cannot be found (other platforms too)."""
    for apps in APP_DIRS:
        try:
            with open(apps / "DeepSeek Harness.app" / "Contents" / "Info.plist", "rb") as handle:
                return plistlib.load(handle).get("CFBundleShortVersionString")
        except (OSError, ValueError):
            continue
    return None


def _package_version(profile, package):
    """The version of a package a profile resolves: its own node_modules, then the one shared under profiles/."""
    for base in (profile, profile.parent):
        try:
            manifest = json.loads((base / "node_modules" / package / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return str(manifest.get("version"))
    return None


def check_dsh_hooks(environ):
    """Profiles attaching the hook bridge: are it and the peer the App lacks there, at the App's version?

    Static only. A bad result proves the hooks cannot run; a good one does not prove they ran."""
    home = Path(environ.get("HOME") or os.path.expanduser("~"))
    results, app = [], dsh_app_version()
    for patch in sorted((Path(environ.get("DSH_HOME") or home / ".dsh") / "profiles").glob("*/cordis.patch.yml")):
        try:
            attached = BRIDGE_LINE.search(patch.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not attached:
            continue
        version = _package_version(patch.parent, BRIDGE)
        protocol = _package_version(patch.parent, BRIDGE_PROTOCOL)
        result = {"harness": "dsh", "profile": patch.parent.name, "bridge": version, "protocol": protocol, "app": app}
        if version is None:
            result.update(status="warn", message=f"cordis.patch.yml 挂了 {BRIDGE}，但没装这个包，这个 profile 的 hook 不会运行")
        elif protocol is None:
            result.update(status="warn", message=f"桥接 {version} 已装，但缺 peer {BRIDGE_PROTOCOL}，启动时加载失败，这个 profile 的 hook 不会运行")
        elif app is None:
            result.update(status="unknown", message=f"桥接 {version} 已装；找不到 App 版本，未对比")
        elif version != app or protocol != app:
            result.update(status="warn", message=f"桥接 {version}、{BRIDGE_PROTOCOL} {protocol} 与 App {app} 版本不同；桥接的 peer 依赖锁定同版本，hook 可能不会运行")
        else:
            result.update(status="ok", message=f"桥接 {version}，与 App 版本一致（只查了包和版本，不代表 hook 已运行）")
        results.append(result)
    return results


def cc_present(environ):
    """CC loads this plugin from its config directory, so without one no hook of ours runs in CC here."""
    return bool(environ.get("CLAUDE_CODE_GIT_BASH_PATH")) or skill_dirs(environ)[0][1].parent.is_dir()


def hook_shells(environ, windows=os.name == "nt"):
    """(label, argv prefix) of the shells harnesses on this platform run hook commands in, where they exist."""
    shells = []
    if windows:
        program_files = environ.get("ProgramFiles", r"C:\Program Files")
        pwsh = ntpath.join(program_files, "PowerShell", "7", "pwsh.exe")
        pwsh = pwsh if os.path.isfile(pwsh) else shutil.which("pwsh", path=environ.get("PATH"))
        if pwsh:
            shells.append(("PowerShell 7，dsh 优先用", [pwsh, *POWERSHELL_ARGS]))
        legacy = ntpath.join(environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(legacy):
            shells.append(("Windows PowerShell 5.1，dsh 没有 pwsh 时用", [legacy, *POWERSHELL_ARGS]))
        git_bash = environ.get("CLAUDE_CODE_GIT_BASH_PATH") or ntpath.join(program_files, "Git", "bin", "bash.exe")
        if os.path.isfile(git_bash) and cc_present(environ):
            shells.append(("Git Bash，CC", [git_bash, "-c"]))
        return shells
    if os.path.isfile("/bin/sh"):
        shells.append(("sh，CC", ["/bin/sh", "-c"]))
    bash = shutil.which("bash", path=environ.get("PATH"))
    if bash:
        shells.append(("bash，dsh", [bash, "-c"]))
    if environ.get("SHELL"):
        shells.append((f"{Path(environ['SHELL']).name} -lc，Codex", [environ["SHELL"], "-lc"]))
    return shells


def probe_hook_command(command, argv, environ):
    """Run the protection hook in one shell against a throwaway registered path. Only a deny proves it worked."""
    with tempfile.TemporaryDirectory(prefix="gis-doctor-hook-") as tmp:
        data = Path(tmp) / "探针 目录"
        (data / ".gis").mkdir(parents=True)
        registry = {"contract": "sources", "schema_version": 1, "protected": ["原始/**"]}
        (data / ".gis" / "sources.json").write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
        payload = {"hook_event_name": "PreToolUse", "tool_name": "write", "cwd": str(data),
                   "tool_input": {"file_path": str(data / "原始" / "甲.csv")}}
        try:
            done = subprocess.run([*argv, command], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                  capture_output=True, cwd=data, env=dict(environ), timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "warn", "message": f"hook 没运行（{exc}），受保护文件照样能写"}
    try:
        denied = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    except (ValueError, KeyError, TypeError):
        denied = False
    if denied:
        return {"status": "ok", "message": "探针写入被拒绝（用的是 doctor 的环境变量，宿主的可能不同）"}
    # The tail: under PowerShell the head is always the harmless complaint about `exec`.
    stderr = done.stderr.decode("utf-8", "replace").strip()[-STDERR_MAX_CHARS:]
    if done.returncode:
        return {"status": "warn", "message": f"hook 没运行（退出码 {done.returncode}），受保护文件照样能写", "stderr": stderr}
    return {"status": "warn", "message": "命令跑完了但没有拒绝探针写入，受保护文件可能照样能写；探针路径带中文，可能没有原样传到 hook", "stderr": stderr}


def check_hook_commands(environ):
    """Does the command in hooks.json run here? A parse error or a missing interpreter is otherwise silent."""
    try:
        command = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return [{"shell": "未检查", "status": "unknown", "message": f"读不到 {HOOKS_FILE}"}]
    command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(HOOKS_FILE.parents[1]))
    return [{"shell": label, **probe_hook_command(command, argv, environ)} for label, argv in hook_shells(environ)]


def run(environ):
    settings = engine_settings(environ)
    engines = [check_engine(name, var, minimum, settings) for name, var, minimum in ENGINES]
    return {
        "doctor": "gis-plugin",
        "python": sys.version.split()[0],
        "engines": engines,
        "contracts": check_contracts(engines),
        "skills": check_skills(settings, environ),
        "hooks": check_dsh_hooks(environ),
        "hook_commands": check_hook_commands(environ),
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
    for pair in report.get("contracts", []):
        lines.append(f"- 约定 {pair['contract']}：{pair['writer']} → {pair['reader']}，"
                     f"{'兼容' if pair['status'] == 'ok' else '不兼容'}（{pair['message']}）")
    stale = [item for item in report.get("skills", []) if item["status"] != "ok"]
    for item in stale:
        lines.append(f"- skill {item['skill']}（{item['harness']}，{item['path']}）："
                     f"{'落后' if item['status'] == 'warn' else '未对比'} — {item['message']}")
        for key, label in (("missing", "缺少"), ("different", "不同")):
            names = item.get(key, [])
            if names:
                shown = "、".join(names[:LIST_MAX]) + (f" 等 {len(names)} 个" if len(names) > LIST_MAX else "")
                lines.append(f"    {label}：{shown}")
    if any(item["status"] == "warn" for item in stale):
        lines.append(f"  已装的 skill 落后时，模型读到的说明和脚本与引擎实际不符。是否更新由用户决定："
                     f"python3 {UPDATE_SCRIPT} --dry-run 先看会做什么")
    hooks = report.get("hooks", [])
    for item in hooks:
        lines.append(f"- dsh hooks（{item['profile']}）：{item['message']}")
    if any(item["status"] == "warn" for item in hooks):
        lines.append("  dsh 的桥接须与 App 同版本；是否安装由用户决定，步骤见 gis-plugin 的 docs/harnesses.md §4")
    commands = report.get("hook_commands", [])
    for item in commands:
        lines.append(f"- hook 命令（{item['shell']}）：{item['message']}")
        if item.get("stderr"):
            lines.append(f"    stderr: {item['stderr']}")
    if any(item["status"] == "warn" for item in commands):
        lines.append("  解释器不对时用环境变量 GIS_PLUGIN_PYTHON 指定完整路径，见 gis-plugin 的 docs/harnesses.md §4")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="检查 GIS 引擎是否可用、版本是否兼容。")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    report = run(os.environ)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 1 if any(item["status"] == "error" for item in report["engines"] + report["contracts"]) else 0


if __name__ == "__main__":
    sys.exit(main())
