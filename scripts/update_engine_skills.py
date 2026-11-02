#!/usr/bin/env python3
"""Update the GIS engine skills installed in each harness (CC, Codex, dsh). Standard library only.

Each install is handled by how it was made:
- symlink: follows its source repository; nothing to do here.
- git clone: `git pull --ff-only`, only when the work tree is clean.
- Codex entry file (a lone SKILL.md): rebuilt from the source SKILL.md with the one line that
  says where the runtime lives rewritten; if that line is not found exactly once, nothing is written.
Skills that are not installed are reported, never installed.
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ENGINES = (
    # (skill, env var with the engine command).
    ("gis-kit", "GIS_KIT_CMD"),
    ("gis-composer", "GIS_COMPOSER_CMD"),
    ("gis-view", "GIS_VIEW_CMD"),
)
# Codex entry files: (line prefix in the source SKILL.md, replacement); {repo} is the source repository.
# The prefix stops before the punctuation that follows `$R`, so rewording the rest of the sentence does not break it.
ENTRY_LINES = {
    "gis-composer": (
        "本 skill 的目录即 gis-composer 运行时仓库，下文记为 `$R`",
        "gis-composer 运行时仓库在 `{repo}`，下文记为 `$R`（本 skill 目录只是 Codex 入口，不含运行时）",
    ),
    "gis-view": (
        "`GV` 为本 skill 的实际目录（即 gis-view 仓库）",
        "`GV` 为 gis-view 仓库 `{repo}`（本 skill 目录只是 Codex 入口，不含运行时）",
    ),
}
TIMEOUT_SECONDS = 120


def skill_dirs(environ):
    home = Path(environ.get("HOME") or os.path.expanduser("~"))
    return (
        ("CC", Path(environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "skills"),
        ("Codex", Path(environ.get("CODEX_HOME") or home / ".codex") / "skills"),
        ("agents", home / ".agents" / "skills"),
        ("dsh", home / ".dsh" / "skills"),
    )


def engine_settings(environ):
    """GIS_* settings: environment variables win over the shared file ~/.config/gis-plugin/engines.env."""
    home = environ.get("HOME") or os.path.expanduser("~")
    path = environ.get("GIS_PLUGIN_CONFIG") or os.path.join(
        environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "gis-plugin", "engines.env")
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


def split_command(command, windows=os.name == "nt"):
    """Split like a shell; on Windows a backslash is a path separator, not an escape. Quotes go either way."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    if windows:
        lexer.escape = ""
    return list(lexer)


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


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)


def update_clone(path, dry_run):
    if _git(path, "status", "--porcelain").stdout.strip():
        return "error", "工作区有改动，跳过"
    before = _git(path, "rev-parse", "--short", "HEAD").stdout.strip()
    if dry_run:
        fetch = _git(path, "fetch", "-q")
        if fetch.returncode:
            return "error", f"fetch 失败：{fetch.stderr.strip()}"
        behind = _git(path, "rev-list", "--count", "HEAD..@{upstream}").stdout.strip() or "?"
        return "ok", f"{before}，落后上游 {behind} 个提交"
    pull = _git(path, "pull", "-q", "--ff-only")
    if pull.returncode:
        return "error", f"pull --ff-only 失败：{pull.stderr.strip()}"
    after = _git(path, "rev-parse", "--short", "HEAD").stdout.strip()
    return "ok", f"已是最新 {after}" if before == after else f"{before} → {after}"


def build_entry(skill, repo):
    """Source SKILL.md with the runtime-location line rewritten for a Codex entry file."""
    if skill not in ENTRY_LINES:
        raise ValueError(f"没有 {skill} 的入口改写规则")
    prefix, replacement = ENTRY_LINES[skill]
    lines = (repo / "SKILL.md").read_text(encoding="utf-8").splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if len(hits) != 1:
        raise ValueError(f"源 SKILL.md 中以“{prefix}”开头的行有 {len(hits)} 处，应为 1 处")
    lines[hits[0]] = replacement.format(repo=repo) + lines[hits[0]][len(prefix):]
    return "".join(lines)


def update_entry(skill, path, repo, dry_run):
    if repo is None:
        return "error", "找不到源仓库（检查 engines.env 中的引擎命令）"
    try:
        content = build_entry(skill, repo)
    except (OSError, ValueError) as exc:
        return "error", str(exc)
    target = path / "SKILL.md"
    if target.read_text(encoding="utf-8") == content:
        return "ok", "已是最新"
    if not dry_run:
        target.write_text(content, encoding="utf-8")
    return "ok", f"{'需要' if dry_run else '已'}按 {repo / 'SKILL.md'} 重建"


def update_skill(skill, path, repo, dry_run):
    if path.is_symlink():
        return "skip", f"软链 → {os.readlink(path)}，随源仓库"
    if not path.exists():
        return "skip", "未安装"
    if (path / ".git").exists():
        return update_clone(path, dry_run)
    if [p.name for p in path.iterdir()] == ["SKILL.md"]:
        return update_entry(skill, path, repo, dry_run)
    return "error", "不认识的安装方式（不是软链、git clone 或单个 SKILL.md）"


def run(environ, dry_run=False):
    settings = engine_settings(environ)
    results = []
    for skill, env_var in ENGINES:
        repo = source_repo(skill, settings.get(env_var, ""))
        for harness, base in skill_dirs(environ):
            status, message = update_skill(skill, base / skill, repo, dry_run)
            results.append({"skill": skill, "harness": harness, "path": str(base / skill),
                            "status": status, "message": message})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="更新各宿主（CC、Codex、dsh）中安装的 GIS 引擎 skill。")
    parser.add_argument("--dry-run", action="store_true", help="只报告要做什么，不改文件")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    results = run(os.environ, dry_run=args.dry_run)
    home = os.path.expanduser("~")
    for item in results:
        line = f"{item['skill']:<13} {item['harness']:<7} {item['path']}：{item['message']}"
        print(line.replace(home, "~"))
    return 1 if any(item["status"] == "error" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
