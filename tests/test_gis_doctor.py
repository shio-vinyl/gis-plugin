import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "gis-doctor" / "scripts" / "gis_doctor.py"
SCHEMA = ROOT / "contracts" / "capabilities.schema.json"

spec = importlib.util.spec_from_file_location("gis_doctor", SCRIPT)
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)

updater_spec = importlib.util.spec_from_file_location("update_engine_skills", ROOT / "scripts" / "update_engine_skills.py")
updater = importlib.util.module_from_spec(updater_spec)
updater_spec.loader.exec_module(updater)

sys.path.insert(0, str(ROOT / "hooks" / "scripts"))  # the hook imports its shared `_patterns` module
hook_spec = importlib.util.spec_from_file_location("inject_describe", ROOT / "hooks" / "scripts" / "inject_describe.py")
describe_hook = importlib.util.module_from_spec(hook_spec)
hook_spec.loader.exec_module(describe_hook)


def caps(**overrides):
    doc = {
        "contract": "capabilities",
        "schema_version": 1,
        "engine": "gis-view",
        "engine_version": "0.2.0",
        "commands": ["describe", "open"],
        "contracts": {"selection": {"write": [1]}},
        "features": [{"name": "desktop", "available": True}],
    }
    doc.update(overrides)
    return doc


class FakeEngines(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def engine(self, name, stdout="", code=0, stderr=""):
        path = self.tmp / f"{name}.py"
        path.write_text(
            "import sys\n"
            "assert sys.argv[1:] == ['capabilities', '--json'], sys.argv\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({code})\n",
            encoding="utf-8",
        )
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(path))}"

    def check(self, cmd, engine="gis-view"):
        name, var, minimum = next(e for e in doctor.ENGINES if e[0] == engine)
        return doctor.check_engine(name, var, minimum, {var: cmd})

    def test_ok(self):
        result = self.check(self.engine("ok", json.dumps(caps())))
        self.assertEqual(result["status"], "ok", result)

    def test_not_configured(self):
        report = doctor.run({"GIS_PLUGIN_CONFIG": "/nonexistent/engines.env", "HOME": str(self.tmp)})
        self.assertEqual({e["status"] for e in report["engines"]}, {"not_configured"})

    def test_missing_executable(self):
        result = self.check(str(self.tmp / "nope"))
        self.assertEqual(result["status"], "error")
        self.assertIn("找不到", result["message"])

    def test_nonzero_exit_reports_stderr(self):
        result = self.check(self.engine("fail", code=2, stderr="unknown command: capabilities"))
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown command", result["stderr"])

    def test_invalid_json(self):
        result = self.check(self.engine("bad", "not json"))
        self.assertEqual(result["status"], "error")

    def test_schema_violation(self):
        result = self.check(self.engine("v2", json.dumps(caps(schema_version=2))))
        self.assertEqual(result["status"], "error")
        self.assertIn("schema_version 须为 1，实为 2", result["problems"])

    def test_unknown_fields_are_ignored(self):
        doc = caps(extra=1, features=[{"name": "desktop", "available": True, "since": "0.3"}],
                   contracts={"selection": {"write": [1], "draft": True}})
        self.assertEqual(self.check(self.engine("extra", json.dumps(doc)))["status"], "ok")

    def test_contract_negotiation(self):
        kit = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"describe": {"write": [1]}})}
        view = {"engine": "gis-view", "capabilities": caps(contracts={"selection": {"write": [2]}})}
        reader = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"selection": {"read": [1]}})}
        pairs = doctor.check_contracts([kit, view, reader])
        by_key = {(p["contract"], p["writer"], p["reader"]): p for p in pairs}
        self.assertEqual(by_key[("describe", "gis-kit", "gis-plugin")]["status"], "ok")
        self.assertEqual(by_key[("selection", "gis-view", "gis-kit")]["status"], "error")
        old = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"describe": {"write": [2]}})}
        self.assertEqual(doctor.check_contracts([old])[0]["status"], "error")

    def test_display_contracts_pair_kit_with_composer(self):
        kit = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"class-scheme": {"write": [1]}, "display-raster": {"write": [1]}})}
        composer = {"engine": "gis-composer", "capabilities": caps(engine="gis-composer", contracts={"class-scheme": {"read": [1]}, "display-raster": {"read": [1]}})}
        pairs = {(p["contract"], p["writer"], p["reader"]): p for p in doctor.check_contracts([kit, composer])}
        self.assertEqual(pairs[("class-scheme", "gis-kit", "gis-composer")]["status"], "ok")
        self.assertEqual(pairs[("display-raster", "gis-kit", "gis-composer")]["message"], "v1")
        snapshot_kit = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"tile-snapshot": {"write": [1]}})}
        snapshot_composer = {"engine": "gis-composer", "capabilities": caps(engine="gis-composer", contracts={"tile-snapshot": {"read": [1]}})}
        self.assertEqual(doctor.check_contracts([snapshot_kit, snapshot_composer])[0]["status"], "ok")
        newer = {"engine": "gis-kit", "capabilities": caps(engine="gis-kit", contracts={"class-scheme": {"write": [2]}})}
        self.assertEqual(doctor.check_contracts([newer, composer])[0]["status"], "error")

    def test_engine_mismatch(self):
        result = self.check(self.engine("mismatch", json.dumps(caps(engine="gis-kit"))))
        self.assertEqual(result["status"], "error")

    def test_version_too_old(self):
        result = self.check(self.engine("old", json.dumps(caps(engine_version="0.1.9"))))
        self.assertEqual(result["status"], "error")
        self.assertIn("低于", result["message"])

    def test_unavailable_feature_warns(self):
        doc = caps(features=[{"name": "blender", "available": False, "reason": "not found"}])
        result = self.check(self.engine("warn", json.dumps(doc)))
        self.assertEqual(result["status"], "warn")

    def test_exit_code(self):
        isolated = {"GIS_PLUGIN_CONFIG": "/nonexistent/engines.env", "HOME": str(self.tmp)}
        with mock.patch.dict(os.environ, {"GIS_VIEW_CMD": self.engine("x", "{}"), **isolated}, clear=True), \
                mock.patch("sys.stdout"):
            self.assertEqual(doctor.main([]), 1)
        with mock.patch.dict(os.environ, isolated, clear=True), mock.patch("sys.stdout"):
            self.assertEqual(doctor.main(["--json"]), 0)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


class InstalledSkills(unittest.TestCase):
    """Installed engine skills: links and copies in step say nothing; stale copies warn and list files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        self.home = self.tmp / "home"
        self.kit = self.tmp / "src" / "gis-kit"
        (self.kit / "scripts").mkdir(parents=True)
        (self.kit / "SKILL.md").write_text("---\nname: gis-kit\n---\n", encoding="utf-8")
        (self.kit / "scripts" / "gis.py").write_text("print('v1')\n", encoding="utf-8")
        (self.kit / "scripts" / "package.py").write_text("", encoding="utf-8")
        (self.kit / "notes.tmp").write_text("untracked\n", encoding="utf-8")
        git(self.kit, "init", "-q", "-b", "main")
        git(self.kit, "add", "SKILL.md", "scripts")
        git(self.kit, "commit", "-q", "-m", "one")
        self.composer = self.tmp / "src" / "gis-composer"
        (self.composer / "src").mkdir(parents=True)
        (self.composer / "SKILL.md").write_text(
            "---\nname: gis-composer\n---\n\n本 skill 的目录即运行时仓库。\n\n用法。\n", encoding="utf-8")
        (self.composer / "src" / "agent-entry.js").write_text("", encoding="utf-8")
        self.environ = {
            "HOME": str(self.home),
            "GIS_PLUGIN_CONFIG": str(self.tmp / "none.env"),
            "GIS_KIT_CMD": f"python3 {self.kit}/scripts/gis.py",
            "GIS_COMPOSER_CMD": f"node {self.composer}/src/agent-entry.js",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def install(self, harness, skill):
        path = self.home / harness / "skills" / skill
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def skills(self):
        return {(s["skill"], s["harness"]): s for s in doctor.check_skills(doctor.engine_settings(self.environ), self.environ)}

    def test_link_is_ok(self):
        self.install(".dsh", "gis-kit").symlink_to(self.kit)
        item = self.skills()[("gis-kit", "dsh")]
        self.assertEqual((item["kind"], item["status"]), ("link", "ok"))

    def test_copy_in_step_is_ok(self):
        shutil.copytree(self.kit, self.install(".claude", "gis-kit"), ignore=shutil.ignore_patterns("notes.tmp"))
        (self.install(".claude", "gis-kit") / "extra.txt").write_text("", encoding="utf-8")
        item = self.skills()[("gis-kit", "CC")]
        self.assertEqual((item["kind"], item["status"]), ("copy", "ok"), item)

    def test_stale_copy_warns_with_files(self):
        copy = self.install(".claude", "gis-kit")
        shutil.copytree(self.kit, copy)
        (copy / "scripts" / "package.py").unlink()
        (copy / "scripts" / "gis.py").write_text("print('v0')\n", encoding="utf-8")
        item = self.skills()[("gis-kit", "CC")]
        self.assertEqual((item["kind"], item["status"]), ("copy", "warn"))
        self.assertEqual(item["missing"], ["scripts/package.py"])
        self.assertEqual(item["different"], ["scripts/gis.py"])
        text = doctor.render_text({"python": "3", "engines": [], "skills": [item]})
        self.assertIn("scripts/package.py", text)
        self.assertIn("update_engine_skills.py", text)

    def test_entry_with_runtime_line_rewritten_is_ok(self):
        entry = self.install(".codex", "gis-composer")
        entry.mkdir()
        (entry / "SKILL.md").write_text(
            f"---\nname: gis-composer\n---\n\n运行时仓库在 `{self.composer}`。\n\n用法。\n", encoding="utf-8")
        item = self.skills()[("gis-composer", "Codex")]
        self.assertEqual((item["kind"], item["status"]), ("entry", "ok"), item)
        (entry / "SKILL.md").write_text(
            f"---\nname: gis-composer\n---\n\n运行时仓库在 `{self.composer}`。\n\n旧用法。\n", encoding="utf-8")
        item = self.skills()[("gis-composer", "Codex")]
        self.assertEqual((item["status"], item["different"]), ("warn", ["SKILL.md"]))

    def test_only_installed_skills_are_listed_and_quiet_when_ok(self):
        self.install(".dsh", "gis-kit").symlink_to(self.kit)
        report = doctor.run(self.environ)
        self.assertEqual([(s["skill"], s["harness"]) for s in report["skills"]], [("gis-kit", "dsh")])
        self.assertNotIn("skill gis-kit", doctor.render_text(report))

    def test_unknown_source_is_reported(self):
        shutil.copytree(self.kit, self.install(".claude", "gis-kit"))
        del self.environ["GIS_KIT_CMD"]
        self.assertEqual(self.skills()[("gis-kit", "CC")]["status"], "unknown")


class ValidatorMatchesSchema(unittest.TestCase):
    """The stdlib validator must agree with the JSON Schema."""

    SAMPLES = [
        caps(),
        caps(extra=1),
        caps(features=[{"name": "x", "available": True, "since": "1"}]),
        caps(schema_version=2),
        caps(schema_version=True),
        caps(engine="Gis_View"),
        caps(engine_version="0.2"),
        caps(commands=["open", "open"]),
        caps(contracts={"selection": {}}),
        caps(contracts={"selection": {"write": [0]}}),
        caps(contracts={"selection": {"edit": [1]}}),
        caps(features=[{"name": "x", "available": "yes"}]),
        caps(features=[{"name": "x", "available": False, "reason": 3}]),
        {k: v for k, v in caps().items() if k != "features"},
    ]

    def test_agreement(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for sample in self.SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(validator.is_valid(sample), not doctor.validate_capabilities(sample))


class EnginesFile(unittest.TestCase):
    def test_outer_quotes_go_only_when_they_wrap_the_whole_value(self):
        with tempfile.TemporaryDirectory(prefix="gis-plugin-test-") as tmp:
            path = Path(tmp) / "engines.env"
            for raw, expected in [
                ('"/a b/python" "/c d/gis.py"', ["/a b/python", "/c d/gis.py"]),
                ("'/a b/python' '/c d/gis.py'", ["/a b/python", "/c d/gis.py"]),
                ('python "/c d/gis.py"', ["python", "/c d/gis.py"]),
                ('"python /c/gis.py"', ["python", "/c/gis.py"]),
                ("python /c/gis.py", ["python", "/c/gis.py"]),
            ]:
                path.write_text(f"GIS_KIT_CMD={raw}\n", encoding="utf-8")
                for module in (doctor, updater, describe_hook):
                    with self.subTest(raw=raw, module=module.__name__):
                        value = module.engine_settings({"GIS_PLUGIN_CONFIG": str(path)})["GIS_KIT_CMD"]
                        self.assertEqual(module.split_command(value, windows=False), expected)


class WindowsCommands(unittest.TestCase):
    def test_backslashes_survive_on_windows(self):
        for module in (doctor, updater):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.split_command(r"node C:\repo\src\entry.js", windows=True), ["node", r"C:\repo\src\entry.js"])
                self.assertEqual(module.split_command(r'"C:\Program Files\py.exe" x', windows=True), [r"C:\Program Files\py.exe", "x"])
                self.assertEqual(module.split_command(r"node 'a b.js'", windows=False), ["node", "a b.js"])


class DshHooks(unittest.TestCase):
    PATCH = "- insert:\n    - id: gis-plugin-hooks\n      name: '@deepseek-ai/dsh-hooks-claude-code'\n"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        self.addCleanup(shutil.rmtree, self.home)
        self.profiles = self.home / ".dsh" / "profiles"
        patcher = mock.patch.object(doctor, "dsh_app_version", return_value="0.2.1-rc.3")
        self.app = patcher.start()
        self.addCleanup(patcher.stop)

    def profile(self, name, patch=PATCH, bridge=None):
        path = self.profiles / name
        path.mkdir(parents=True)
        (path / "cordis.patch.yml").write_text(patch, encoding="utf-8")
        if bridge:
            self.install(path, bridge)
        return path

    def install(self, base, version):
        package = base / "node_modules" / doctor.BRIDGE
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")

    def check(self, **environ):
        return doctor.check_dsh_hooks({"HOME": str(self.home), **environ})

    def test_no_dsh_or_no_bridge_is_silent(self):
        self.assertEqual(self.check(), [])
        self.profile("web", "- id: other\n  name: '@deepseek-ai/dsh-mcp-client'\n")
        self.profile("old", "# name: '@deepseek-ai/dsh-hooks-claude-code'\n")
        self.assertEqual(self.check(), [])

    def test_attached_but_not_installed(self):
        self.profile("desktop")
        [item] = self.check()
        self.assertEqual((item["profile"], item["status"], item["bridge"]), ("desktop", "warn", None))
        self.assertIn("hook 不会运行", item["message"])

    def test_version_against_app(self):
        self.profile("same", bridge="0.2.1-rc.3")
        self.profile("older", bridge="0.2.0-rc.2")
        same, older = sorted(self.check(), key=lambda item: item["profile"], reverse=True)
        self.assertEqual(same["status"], "ok")
        self.assertIn("不代表 hook 已运行", same["message"])
        self.assertEqual(older["status"], "warn")
        self.assertIn("0.2.0-rc.2", older["message"])
        self.app.return_value = None
        self.assertEqual({item["status"] for item in self.check()}, {"unknown"})

    def test_shared_node_modules_and_dsh_home(self):
        self.profile("desktop")
        self.install(self.profiles, "0.2.1-rc.3")
        self.assertEqual(self.check()[0]["status"], "ok")
        other = self.home / "elsewhere"
        (other / "profiles" / "p").mkdir(parents=True)
        (other / "profiles" / "p" / "cordis.patch.yml").write_text(self.PATCH, encoding="utf-8")
        self.assertEqual(self.check(DSH_HOME=str(other))[0]["profile"], "p")

    def test_report_text_and_exit_code(self):
        self.profile("desktop")
        env = {"HOME": str(self.home), "GIS_PLUGIN_CONFIG": str(self.home / "none.env")}
        report = doctor.run(env)
        text = doctor.render_text(report)
        self.assertIn("dsh hooks（desktop）", text)
        self.assertIn("docs/harnesses.md §4", text)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("sys.stdout"):
            self.assertEqual(doctor.main([]), 0)

    def test_app_version_from_info_plist(self):
        mock.patch.stopall()
        contents =self.home / "DeepSeek Harness.app" / "Contents"
        contents.mkdir(parents=True)
        (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "9.9.9"}))
        with mock.patch.object(doctor, "APP_DIRS", (self.home / "missing", self.home)):
            self.assertEqual(doctor.dsh_app_version(), "9.9.9")
        with mock.patch.object(doctor, "APP_DIRS", (self.home / "missing",)):
            self.assertIsNone(doctor.dsh_app_version())


if __name__ == "__main__":
    unittest.main()
