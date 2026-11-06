import importlib.util
import os
import shutil
import stat
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
VIEW_SKILL = (
    "---\nname: gis-view\ndescription: x\n---\n\n# 查看\n\n"
    "`GV` 为本 skill 的实际目录（即 gis-view 仓库），解释器为其中的 `.venv`：\n"
)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


def remove_tree(path):
    """Git leaves its objects read-only, and on Windows that stops rmtree."""
    for parent, _, files in os.walk(path):
        for name in files:
            target = Path(parent) / name
            if not target.is_symlink():
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
    shutil.rmtree(path)


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
        self.view = self.tmp / "src" / "gis-view"
        (self.view / ".venv" / "bin").mkdir(parents=True)
        (self.view / "scripts").mkdir()
        (self.view / "SKILL.md").write_text(VIEW_SKILL, encoding="utf-8")
        (self.view / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (self.view / "scripts" / "gis-view.py").write_text("", encoding="utf-8")
        config = self.home / ".config" / "gis-plugin"
        config.mkdir(parents=True)
        (config / "engines.env").write_text(
            f'GIS_KIT_CMD="python3 {self.kit}/scripts/gis.py"\n'
            f'GIS_COMPOSER_CMD="node {self.composer}/src/agent-entry.js"\n'
            f'GIS_VIEW_CMD="{self.view}/.venv/bin/python {self.view}/scripts/gis-view.py"\n', encoding="utf-8")
        self.environ = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "")}

    def tearDown(self):
        remove_tree(self.tmp)

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

    def test_view_codex_entry_is_rebuilt(self):
        entry = self.skills(".codex") / "gis-view"
        entry.mkdir()
        target = entry / "SKILL.md"
        target.write_text("old\n", encoding="utf-8")
        item = self.result(updater.run(self.environ), "gis-view", "Codex")
        self.assertEqual(item["status"], "ok")
        text = target.read_text(encoding="utf-8")
        self.assertIn(f"`GV` 为 gis-view 仓库 `{self.view}`（本 skill 目录只是 Codex 入口，不含运行时），解释器为其中的 `.venv`：", text)
        self.assertNotIn("本 skill 的实际目录", text)
        self.assertEqual(self.result(updater.run(self.environ), "gis-view", "Codex")["message"], "已是最新")

    def test_dry_run_writes_nothing(self):
        target = self.codex_entry()
        item = self.result(updater.run(self.environ, dry_run=True), "gis-composer", "Codex")
        self.assertIn("需要", item["message"])
        self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_series_members_follow_the_same_rules(self):
        deck = self.tmp / "src" / "plan-deck"
        deck.mkdir(parents=True)
        (deck / "SKILL.md").write_text("---\nname: plan-deck\n---\n", encoding="utf-8")
        git(deck, "init", "-q", "-b", "main")
        git(deck, "add", ".")
        git(deck, "commit", "-q", "-m", "one")
        with (self.home / ".config" / "gis-plugin" / "engines.env").open("a", encoding="utf-8") as handle:
            handle.write(f'GIS_PLAN_DECK_REPO="{deck}"\n')
        (self.skills(".claude") / "plan-deck").symlink_to(deck)
        clone = self.skills(".codex") / "plan-deck"
        git(self.tmp, "clone", "-q", str(deck), str(clone))
        (deck / "NEW.md").write_text("", encoding="utf-8")
        git(deck, "add", ".")
        git(deck, "commit", "-q", "-m", "two")
        plain = self.skills(".dsh") / "plan-diagram"  # a copied directory, not a clone
        plain.mkdir()
        (plain / "SKILL.md").write_text("", encoding="utf-8")
        (plain / "refs").mkdir()
        dry = updater.run(self.environ, dry_run=True)
        self.assertIn("落后上游 1 个提交", self.result(dry, "plan-deck", "Codex")["message"])
        self.assertFalse((clone / "NEW.md").exists())
        results = updater.run(self.environ)
        self.assertEqual(self.result(results, "plan-deck", "CC")["status"], "skip")
        self.assertTrue((clone / "NEW.md").exists())
        self.assertEqual(self.result(results, "house-style", "CC")["message"], "未安装")
        item = self.result(results, "plan-diagram", "dsh")
        self.assertEqual(item["status"], "error")
        self.assertIn("复制的目录", item["message"])
        self.assertEqual({r["skill"] for r in results},
                         {"gis-kit", "gis-composer", "gis-view", "plan-deck", "chart-forms", "plan-diagram", "house-style"})

    def test_entry_line_missing_is_an_error(self):
        (self.composer / "SKILL.md").write_text("---\nname: gis-composer\n---\n改过的说明\n", encoding="utf-8")
        target = self.codex_entry()
        item = self.result(updater.run(self.environ), "gis-composer", "Codex")
        self.assertEqual(item["status"], "error")
        self.assertEqual(target.read_text(encoding="utf-8"), "old\n")


if __name__ == "__main__":
    unittest.main()
