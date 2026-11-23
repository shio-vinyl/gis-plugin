import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "inject_style.py"

sys.path.insert(0, str(SCRIPT.parent))  # the hook imports its sibling `_harness` module
spec = importlib.util.spec_from_file_location("inject_style", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class InjectStyle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-")).resolve()
        self.project = self.tmp / "南极 专题"
        (self.project / "maps" / "hero").mkdir(parents=True)
        self.env = {"GIS_PLUGIN_STATE": str(self.tmp / "state")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def style(self, base=None):
        path = (base or self.project) / "style" / "STYLE.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 样式\n", encoding="utf-8")

    def prompt(self, cwd=None, session="s1"):
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "出一张图", "cwd": str(cwd or self.project)}
        if session is not None:
            payload["session_id"] = session
        return payload

    def test_says_where_the_style_is_once_per_session(self):
        self.style()
        context = hook.run(self.prompt(), self.env)
        self.assertIn(f"本项目（{self.project}）的样式记录在 style/STYLE.md", context)
        self.assertIn("gis-plugin hook", context)
        self.assertEqual(context.count("\n"), 0)  # one line
        self.assertIsNone(hook.run(self.prompt(), self.env))
        self.assertIsNotNone(hook.run(self.prompt(session="s2"), self.env))

    def test_found_from_a_subdirectory(self):
        self.style()
        context = hook.run(self.prompt(cwd=self.project / "maps" / "hero"), self.env)
        self.assertIn(str(self.project), context)

    def test_silent_without_style_and_writes_no_state(self):
        (self.project / "gis-project.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(hook.run(self.prompt(cwd=self.project / "maps"), self.env))
        self.assertFalse((self.tmp / "state").exists())

    def test_nearest_project_root_wins(self):
        # An outer project's style does not belong to an inner project that has none of its own.
        self.style(self.tmp)
        (self.project / "gis-project.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(hook.run(self.prompt(cwd=self.project / "maps"), self.env))

    def test_a_project_with_both_markers(self):
        (self.project / "gis-project.json").write_text("{}", encoding="utf-8")
        self.style()
        self.assertIsNotNone(hook.run(self.prompt(cwd=self.project / "maps"), self.env))

    def test_moving_to_another_project_says_it_again(self):
        self.style()
        other = self.tmp / "另一个"
        self.style(other)
        self.assertIsNotNone(hook.run(self.prompt(), self.env))
        context = hook.run(self.prompt(cwd=other), self.env)
        self.assertIn(str(other), context)
        self.assertIsNone(hook.run(self.prompt(), self.env))

    def test_a_directory_named_style_md_is_not_a_style(self):
        (self.project / "style" / "STYLE.md").mkdir(parents=True)
        self.assertIsNone(hook.run(self.prompt(), self.env))

    def test_main_prints_hook_json_and_never_fails(self):
        self.style()
        env = {**self.env, "PYTHONDONTWRITEBYTECODE": "1", "PATH": ""}
        done = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(self.prompt(), ensure_ascii=False).encode("utf-8"),
                              capture_output=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        output = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn("style/STYLE.md", output["additionalContext"])
        done.stdout.decode("ascii")
        broken = subprocess.run([sys.executable, str(SCRIPT)], input=b"not json", capture_output=True, env=env, timeout=30)
        self.assertEqual((broken.returncode, broken.stdout), (0, b""))

    def test_antigravity_pre_invocation_injects_once_with_protojson(self):
        self.style()
        env = {**self.env, "PYTHONDONTWRITEBYTECODE": "1", "PATH": ""}
        payload = {"hookEventName": "PreInvocation", "conversationId": "conv-1",
                   "workspacePaths": [str(self.project / "maps")], "invocationNum": 0, "lastUserInput": "出图"}
        first = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, env=env, timeout=30)
        self.assertEqual(first.returncode, 0, first.stderr)
        out = json.loads(first.stdout.decode("ascii"))
        self.assertEqual(set(out), {"injectSteps"})
        msg = out["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn(f"本项目（{self.project}）的样式记录在 style/STYLE.md", msg)
        second = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({**payload, "invocationNum": 1}).encode("utf-8"),
                                capture_output=True, env=env, timeout=30)
        self.assertEqual((second.returncode, second.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
