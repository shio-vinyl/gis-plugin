import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update_engine_skills.py"

spec = importlib.util.spec_from_file_location("update_engine_skills", SCRIPT)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

COMPOSER_SKILL = (
    "---\nname: gis-composer\ndescription: x\n---\n\n# 地图\n\n"
    "本 skill 的目录即 gis-composer 运行时仓库，下文记为 `$R`。引擎随仓库维护。\n"
)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


class UpdateEngineSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        self.home = self.tmp / "home"
        # Source repositories, located through engines.env.
        self.kit = self.tmp / "src" / "gis-kit"
        (self.kit / "scripts").mkdir(parents=True)
        (self.kit / "SKILL.md").write_text("---\nname: gis-kit\n---\n", encoding="utf-8")
        (self.kit / "scripts" / "gis.py").write_text("", encoding="utf-8")
        git(self.kit, "init", "-q", "-b", "main")
        git(self.kit, "add", ".")
        git(self.kit, "commit", "-q", "-m", "one")
        self.composer = self.tmp / "src" / "gis-composer"
        (self.composer / "src").mkdir(parents=True)
        (self.composer / "SKILL.md").write_text(COMPOSER_SKILL, encoding="utf-8")
        (self.composer / "src" / "agent-entry.js").write_text("", encoding="utf-8")
        config = self.home / ".config" / "gis-plugin"
        config.mkdir(parents=True)
        (config / "engines.env").write_text(
            f'GIS_KIT_CMD="python3 {self.kit}/scripts/gis.py"\n'
            f'GIS_COMPOSER_CMD="node {self.composer}/src/agent-entry.js"\n', encoding="utf-8")
        self.environ = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def skills(self, harness):
        path = self.home / harness / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def result(self, results, skill, harness):
        return next(r for r in results if r["skill"] == skill and r["harness"] == harness)

    def codex_entry(self):
        entry = self.skills(".codex") / "gis-composer"
        entry.mkdir()
        (entry / "SKILL.md").write_text("old\n", encoding="utf-8")
        return entry / "SKILL.md"

    def test_clone_fast_forwards(self):
        clone = self.skills(".claude") / "gis-kit"
        git(self.tmp, "clone", "-q", str(self.kit), str(clone))
        (self.kit / "NEW.md").write_text("", encoding="utf-8")
        git(self.kit, "add", ".")
        git(self.kit, "commit", "-q", "-m", "two")
        item = self.result(updater.run(self.environ), "gis-kit", "CC")
        self.assertEqual(item["status"], "ok")
        self.assertIn("→", item["message"])
        self.assertTrue((clone / "NEW.md").exists())

    def test_dirty_clone_is_skipped(self):
        clone = self.skills(".claude") / "gis-kit"
        git(self.tmp, "clone", "-q", str(self.kit), str(clone))
        (clone / "SKILL.md").write_text("local edit\n", encoding="utf-8")
        item = self.result(updater.run(self.environ), "gis-kit", "CC")
        self.assertEqual(item["status"], "error")
        self.assertEqual((clone / "SKILL.md").read_text(encoding="utf-8"), "local edit\n")

    def test_symlink_and_missing_are_left_alone(self):
        (self.skills(".dsh") / "gis-composer").symlink_to(self.composer)
        results = updater.run(self.environ)
        self.assertEqual(self.result(results, "gis-composer", "dsh")["status"], "skip")
        self.assertEqual(self.result(results, "gis-composer", "CC")["message"], "未安装")
        self.assertFalse((self.home / ".claude" / "skills" / "gis-composer").exists())

    def test_codex_entry_is_rebuilt(self):
        target = self.codex_entry()
        item = self.result(updater.run(self.environ), "gis-composer", "Codex")
        self.assertEqual(item["status"], "ok")
        text = target.read_text(encoding="utf-8")
        self.assertIn(f"gis-composer 运行时仓库在 `{self.composer}`", text)
        self.assertIn("（本 skill 目录只是 Codex 入口，不含运行时）。引擎随仓库维护。", text)
        self.assertNotIn("本 skill 的目录即", text)
        self.assertEqual(self.result(updater.run(self.environ), "gis-composer", "Codex")["message"], "已是最新")

    def test_dry_run_writes_nothing(self):
        target = self.codex_entry()
        item = self.result(updater.run(self.environ, dry_run=True), "gis-composer", "Codex")
        self.assertIn("需要", item["message"])
        self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_entry_line_missing_is_an_error(self):
        (self.composer / "SKILL.md").write_text("---\nname: gis-composer\n---\n改过的说明\n", encoding="utf-8")
        target = self.codex_entry()
        item = self.result(updater.run(self.environ), "gis-composer", "Codex")
        self.assertEqual(item["status"], "error")
        self.assertEqual(target.read_text(encoding="utf-8"), "old\n")


if __name__ == "__main__":
    unittest.main()
