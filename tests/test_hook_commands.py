"""Run the commands in hooks.json the way each harness does. PowerShell cases need `pwsh` or `powershell`
on PATH, or GIS_TEST_PWSH pointing at one; Git Bash cases need Windows and Git for Windows, or GIS_TEST_GIT_BASH
pointing at a bash. They skip otherwise."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
COMMANDS = {event: groups[0]["hooks"][0]["command"] for event, groups in HOOKS.items()}  # first group per event
ALL_COMMANDS = [hook["command"] for groups in HOOKS.values() for group in groups for hook in group["hooks"]]
STYLE_COMMAND = next(command for command in ALL_COMMANDS if "inject_style.py" in command)
TEXT_COMMAND = next(command for command in ALL_COMMANDS if "check_artifact_text.py" in command)
# What dsh-pwsh-local puts in front of every command (dsh 0.2.1-rc.3).
PREAMBLE = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); ")
PWSH_ARGS = ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]


def posix_shells():
    found = [(name, [path, "-c"]) for name, path in ((n, shutil.which(n)) for n in ("sh", "bash", "dash", "zsh")) if path]
    return found + [(f"{name} -l", [argv[0], "-lc"]) for name, argv in found if name in ("bash", "zsh")]


def powershells():
    paths = [os.environ.get("GIS_TEST_PWSH"), shutil.which("pwsh"), shutil.which("powershell")]
    return [path for path in dict.fromkeys(paths) if path]


def git_bash():
    """The shell CC uses on Windows, in its default location."""
    if os.environ.get("GIS_TEST_GIT_BASH"):
        return os.environ["GIS_TEST_GIT_BASH"]
    path = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    return str(path) if os.name == "nt" and path.is_file() else None


def fake_interpreter(path, marker):
    """An interpreter at `path` that records it ran, then behaves as the real one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = path.with_suffix(".cmd")
        path.write_text(f'@echo ran>"{marker}"\r\n@"{sys.executable}" %*\r\n', encoding="utf-8")
    else:
        path.write_text(f'#!/bin/sh\necho ran > "{marker}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def venv_interpreter(env_dir, marker):
    """A real interpreter at `env_dir` that writes where it started from to `marker`.

    For Git Bash on Windows, which cuts a `.cmd` path at its space and so cannot use fake_interpreter there."""
    venv.create(env_dir, with_pip=False)
    (next(env_dir.rglob("site-packages")) / "sitecustomize.py").write_text(
        f"import sys\nwith open({str(marker)!r}, 'w', encoding='utf-8') as out:\n    out.write(sys.prefix)\n", encoding="utf-8")
    return env_dir / "Scripts" / "python.exe" if os.name == "nt" else env_dir / "bin" / "python"


class Fixture(unittest.TestCase):
    """A plugin copy and registered data, both under paths with Chinese and a space."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-")).resolve()
        self.root = self.tmp / "插件 目录"
        shutil.copytree(ROOT / "hooks", self.root / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        self.data = self.tmp / "数据 目录"
        (self.data / ".gis").mkdir(parents=True)
        (self.data / ".gis" / "sources.json").write_text(json.dumps(
            {"contract": "sources", "schema_version": 1, "protected": ["原始/**"]}, ensure_ascii=False), encoding="utf-8")
        self.marker = self.tmp / "ran"
        self.env = {k: v for k, v in os.environ.items() if k != "GIS_PLUGIN_PYTHON"}
        self.env.update(PYTHONDONTWRITEBYTECODE="1", POWERSHELL_TELEMETRY_OPTOUT="1")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_hook(self, argv, command, payload=None, **env):
        command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(self.root))  # as the CC and dsh substitution does
        payload = payload or {"hook_event_name": "PreToolUse", "tool_name": "write", "cwd": str(self.data),
                              "tool_input": {"file_path": str(self.data / "原始" / "甲.csv")}}
        return subprocess.run([*argv, command], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                              capture_output=True, cwd=self.data, env={**self.env, **env}, timeout=120)

    def style_payload(self):
        """A project with style/STYLE.md; the session works in a subdirectory of it."""
        (self.data / "style").mkdir()
        (self.data / "style" / "STYLE.md").write_text("# 样式\n", encoding="utf-8")
        (self.data / "图").mkdir()
        return {"hook_event_name": "UserPromptSubmit", "prompt": "出图", "cwd": str(self.data / "图"), "session_id": "s-1"}

    def assert_style_said(self, done):
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        output = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn(str(self.data), output["additionalContext"])
        done.stdout.decode("ascii")

    def text_payload(self):
        """A map in the data directory with a disclaimer on it, just written by the Bash tool."""
        (self.data / "图 甲.svg").write_text('<svg><text x="1" y="2">范围示意，仅供参考</text></svg>', encoding="utf-8")
        return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "node draw.js"},
                "cwd": str(self.data), "session_id": "s-1"}

    def assert_text_blocked(self, done):
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        output = json.loads(done.stdout)  # one JSON document: a wrapped line would not parse
        self.assertEqual(output["decision"], "block")
        self.assertIn("范围示意，仅供参考", output["reason"])
        self.assertIn("图 甲.svg", output["reason"])
        done.stdout.decode("ascii")

    def assert_denied(self, done):
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        output = json.loads(done.stdout)["hookSpecificOutput"]  # one JSON document: a wrapped line would not parse
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("原始", output["permissionDecisionReason"])
        done.stdout.decode("ascii")


class Form(unittest.TestCase):
    def test_every_command_has_both_branches(self):
        for command in ALL_COMMANDS:
            with self.subTest(command=command):
                match = re.fullmatch(
                    r'exec "\$\{GIS_PLUGIN_PYTHON:-python3\}" "(\$\{CLAUDE_PLUGIN_ROOT\}/hooks/scripts/\w+\.py)"; '
                    r"\$p = \$env:GIS_PLUGIN_PYTHON, 'python' -match '\.'; \. \$p\[0\] \"\1\"", command)
                self.assertIsNotNone(match, command)
                self.assertTrue((ROOT / match[1].replace("${CLAUDE_PLUGIN_ROOT}/", "")).is_file())

    def test_powershell_does_not_take_over_stdin(self):
        # Naming $input makes PowerShell read stdin itself and re-encode it, which can corrupt a Chinese path.
        for command in ALL_COMMANDS:
            self.assertNotIn("$input", command.lower())

    def test_powershell_branch_is_valid_in_5_1(self):
        # 5.1 has neither `||`, `&&` nor `??`. They would be a parse error before anything ran.
        for command in ALL_COMMANDS:
            for token in ("||", "&&", "??"):
                self.assertNotIn(token, command)


@unittest.skipIf(os.name == "nt", "POSIX shells")
class PosixShells(Fixture):
    def test_protects(self):
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                done = self.run_hook(argv, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=sys.executable)
                self.assert_denied(done)

    def test_the_powershell_half_never_runs(self):
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                # A login shell may print its own noise, so look for what the tail would have complained about.
                stderr = self.run_hook(argv, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=sys.executable).stderr.decode()
                self.assertNotIn("$p", stderr)
                self.assertNotRegex(stderr, r"(?i)not found|syntax error|parse error")

    def test_interpreter_can_be_overridden(self):
        interpreter = fake_interpreter(self.tmp / "我的 解释器" / "python", self.marker)
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                self.marker.unlink(missing_ok=True)
                self.assert_denied(self.run_hook(argv, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(interpreter)))
                self.assertTrue(self.marker.exists())

    def test_default_interpreter_is_python3(self):
        bin_dir = self.tmp / "bin"
        fake_interpreter(bin_dir / "python3", self.marker)
        path = f"{bin_dir}{os.pathsep}{self.env['PATH']}"
        self.assert_denied(self.run_hook([shutil.which("sh"), "-c"], COMMANDS["PreToolUse"], PATH=path))
        self.assertTrue(self.marker.exists())

    def test_missing_interpreter_fails_visibly(self):
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                done = self.run_hook(argv, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(self.tmp / "nope"))
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(done.stdout, b"")

    def test_style_line_reaches_stdout(self):
        payload = self.style_payload()
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                state = self.tmp / f"state {name}"
                self.assert_style_said(self.run_hook(argv, STYLE_COMMAND, payload, GIS_PLUGIN_PYTHON=sys.executable,
                                                     GIS_PLUGIN_STATE=str(state)))
                again = self.run_hook(argv, STYLE_COMMAND, payload, GIS_PLUGIN_PYTHON=sys.executable, GIS_PLUGIN_STATE=str(state))
                self.assertEqual((again.returncode, again.stdout), (0, b""))

    def test_artifact_text_is_blocked(self):
        payload = self.text_payload()
        for name, argv in posix_shells():
            with self.subTest(shell=name):
                self.assert_text_blocked(self.run_hook(argv, TEXT_COMMAND, payload, GIS_PLUGIN_PYTHON=sys.executable,
                                                       GIS_PLUGIN_STATE=str(self.tmp / f"state {name}")))

    def test_the_old_form_still_parses_here(self):
        # The contrast PowerShell lacks: POSIX shells accept the bare quoted form too, so only PowerShell tests catch it.
        old = '"${GIS_PLUGIN_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/protect_sources.py"'
        self.assert_denied(self.run_hook([shutil.which("sh"), "-c"], old, GIS_PLUGIN_PYTHON=sys.executable))


@unittest.skipUnless(git_bash(), "no Git Bash here")
class GitBash(Fixture):
    """Keeps the real HOME, so a startup file that gets in the way shows up here and not only in the doctor."""

    def test_protects_with_override(self):
        self.assert_denied(self.run_hook([git_bash(), "-c"], COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=sys.executable))

    def test_override_path_with_chinese_and_space(self):
        env_dir = self.tmp / "我的 解释器"
        interpreter = venv_interpreter(env_dir, self.marker)
        self.assertTrue(interpreter.is_file(), f"venv made no {interpreter}")
        self.assert_denied(self.run_hook([git_bash(), "-c"], COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(interpreter)))
        self.assertTrue(os.path.samefile(self.marker.read_text(encoding="utf-8"), env_dir))

    def test_missing_interpreter_fails_visibly(self):
        done = self.run_hook([git_bash(), "-c"], COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(self.tmp / "nope"))
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b"")


@unittest.skipUnless(powershells(), "no PowerShell here")
class PowerShell(Fixture):
    """The argv dsh-pwsh-local builds: the command is one argument to -Command, and stdin is piped."""

    def run_pwsh(self, shell, command, payload=None, **env):
        return self.run_hook([shell, *PWSH_ARGS], PREAMBLE + command, payload, **env)

    def test_old_form_is_a_parse_error(self):
        old = '"${GIS_PLUGIN_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/protect_sources.py"'
        for shell in powershells():
            with self.subTest(shell=shell):
                done = self.run_pwsh(shell, old, GIS_PLUGIN_PYTHON=sys.executable)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, b"")

    def test_protects_with_override(self):
        for shell in powershells():
            with self.subTest(shell=shell):
                self.assert_denied(self.run_pwsh(shell, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=sys.executable))

    def test_override_path_with_chinese_and_space(self):
        interpreter = fake_interpreter(self.tmp / "我的 解释器" / "python", self.marker)
        for shell in powershells():
            with self.subTest(shell=shell):
                self.marker.unlink(missing_ok=True)
                self.assert_denied(self.run_pwsh(shell, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(interpreter)))
                self.assertTrue(self.marker.exists())

    def test_default_interpreter_is_python(self):
        bin_dir = self.tmp / "bin"
        fake_interpreter(bin_dir / "python", self.marker)
        path = f"{bin_dir}{os.pathsep}{self.env['PATH']}"
        for shell in powershells():
            for env in ({}, {"GIS_PLUGIN_PYTHON": ""}):
                with self.subTest(shell=shell, env=env):
                    self.marker.unlink(missing_ok=True)
                    self.assert_denied(self.run_pwsh(shell, COMMANDS["PreToolUse"], PATH=path, **env))
                    self.assertTrue(self.marker.exists())

    def test_missing_interpreter_fails_visibly(self):
        for shell in powershells():
            with self.subTest(shell=shell):
                done = self.run_pwsh(shell, COMMANDS["PreToolUse"], GIS_PLUGIN_PYTHON=str(self.tmp / "nope"))
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, b"")

    def test_style_line_reaches_stdout(self):
        payload = self.style_payload()
        for shell in powershells():
            with self.subTest(shell=shell):
                self.assert_style_said(self.run_pwsh(shell, STYLE_COMMAND, payload, GIS_PLUGIN_PYTHON=sys.executable,
                                                     GIS_PLUGIN_STATE=str(self.tmp / f"state {Path(shell).name}")))

    def test_artifact_text_is_blocked(self):
        payload = self.text_payload()
        for shell in powershells():
            with self.subTest(shell=shell):
                self.assert_text_blocked(self.run_pwsh(shell, TEXT_COMMAND, payload, GIS_PLUGIN_PYTHON=sys.executable,
                                                       GIS_PLUGIN_STATE=str(self.tmp / f"state {Path(shell).name}")))

    def test_injection_commands_run(self):
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "看看 原始/甲.csv", "cwd": str(self.data)}
        for event in ("UserPromptSubmit", "PostToolUse"):
            for shell in powershells():
                with self.subTest(event=event, shell=shell):
                    done = self.run_pwsh(shell, COMMANDS[event], {**payload, "hook_event_name": event},
                                         GIS_PLUGIN_PYTHON=sys.executable, GIS_PLUGIN_CONFIG=str(self.tmp / "none.env"))
                    self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))


@unittest.skipIf(os.name == "nt", "Antigravity root hooks.json targets Unix sh -c")
class AntigravityHooks(Fixture):
    """Run the commands in root hooks.json the way Antigravity runs them: sh -c with cwd = plugin root."""

    def setUp(self):
        super().setUp()
        shutil.copy2(ROOT / "hooks.json", self.root / "hooks.json")
        self.ag_hooks = json.loads((self.root / "hooks.json").read_text(encoding="utf-8"))["gis-plugin"]

    def run_ag(self, command, payload, **env):
        return subprocess.run([shutil.which("sh"), "-c", command],
                              input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                              capture_output=True, cwd=self.root, env={**self.env, **env}, timeout=120)

    def test_root_hooks_json_commands_exist_and_use_relative_paths(self):
        commands = [h["command"] for h in self.ag_hooks["PreInvocation"]] + [
            h["command"] for event in ("PreToolUse", "PostToolUse") for g in self.ag_hooks[event] for h in g["hooks"]
        ]
        for command in commands:
            match = re.fullmatch(r'exec "\$\{GIS_PLUGIN_PYTHON:-python3\}" (\./hooks/scripts/\w+\.py)', command)
            self.assertIsNotNone(match, command)
            self.assertTrue((ROOT / match[1]).is_file())

    def test_protect_style_and_artifact_text_end_to_end(self):
        protect = self.ag_hooks["PreToolUse"][0]["hooks"][0]["command"]
        denied = self.run_ag(protect, {
            "hookEventName": "PreToolUse", "conversationId": "c-1", "cwd": str(self.data),
            "toolCall": {"id": "t1", "name": "write_file", "args": {"Path": str(self.data / "原始" / "甲.csv")}},
        }, GIS_PLUGIN_PYTHON=sys.executable)
        self.assertEqual(denied.returncode, 0, denied.stderr.decode())
        out = json.loads(denied.stdout.decode("ascii"))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("原始", out["reason"])

        allowed = self.run_ag(protect, {
            "hookEventName": "PreToolUse", "conversationId": "c-1", "cwd": str(self.data),
            "toolCall": {"id": "t2", "name": "write_file", "args": {"Path": str(self.data / "ok.csv")}},
        }, GIS_PLUGIN_PYTHON=sys.executable)
        self.assertEqual((allowed.returncode, allowed.stdout), (0, b""))

        state = str(self.tmp / "ag-state")
        (self.data / "style").mkdir()
        (self.data / "style" / "STYLE.md").write_text("# 样式\n", encoding="utf-8")
        style_cmd = next(h["command"] for h in self.ag_hooks["PreInvocation"] if "inject_style.py" in h["command"])
        styled = self.run_ag(style_cmd, {
            "hookEventName": "PreInvocation", "conversationId": "c-1", "cwd": str(self.data), "invocationNum": 0,
        }, GIS_PLUGIN_PYTHON=sys.executable, GIS_PLUGIN_STATE=state)
        self.assertIn("style/STYLE.md", json.loads(styled.stdout.decode("ascii"))["injectSteps"][0]["systemMessage"]["systemMessage"])

        (self.data / "图 甲.svg").write_text('<svg><text>范围示意，仅供参考</text></svg>', encoding="utf-8")
        post_cmd = next(h["command"] for g in self.ag_hooks["PostToolUse"] for h in g["hooks"] if "check_artifact_text.py" in h["command"])
        pre_cmd = next(h["command"] for h in self.ag_hooks["PreInvocation"] if "check_artifact_text.py" in h["command"])
        post = self.run_ag(post_cmd, {
            "hookEventName": "PostToolUse", "conversationId": "c-1", "cwd": str(self.data), "error": "",
            "toolCall": {"id": "t3", "name": "write_file", "args": {"Path": str(self.data / "图 甲.svg")}},
        }, GIS_PLUGIN_PYTHON=sys.executable, GIS_PLUGIN_STATE=state)
        self.assertEqual((post.returncode, json.loads(post.stdout)), (0, {}))
        pre = self.run_ag(pre_cmd, {
            "hookEventName": "PreInvocation", "conversationId": "c-1", "cwd": str(self.data), "invocationNum": 1,
        }, GIS_PLUGIN_PYTHON=sys.executable, GIS_PLUGIN_STATE=state)
        self.assertIn("范围示意，仅供参考", json.loads(pre.stdout.decode("ascii"))["injectSteps"][0]["systemMessage"]["systemMessage"])


if __name__ == "__main__":
    unittest.main()
