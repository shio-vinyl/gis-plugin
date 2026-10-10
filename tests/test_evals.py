import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evals" / "run.py"

spec = importlib.util.spec_from_file_location("evals_run", SCRIPT)
evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evals)


class Evals(unittest.TestCase):
    def test_bundled_cases_load(self):
        cases = evals.load_cases()
        self.assertGreaterEqual(len(cases), 3)
        with self.assertRaises(evals.CaseError):
            evals.load_cases(["no-such-case"])

    def test_last_json(self):
        text = '先说明。\n```json\n{"crs": "EPSG:3857"}\n```\n最后：\n{"crs": "EPSG:4326", "feature_count": 3}\n'
        self.assertEqual(evals.last_json(text), {"crs": "EPSG:4326", "feature_count": 3})
        self.assertEqual(evals.last_json('结论\n```\n{"a": 1}\n```'), {"a": 1})
        self.assertIsNone(evals.last_json("没有 JSON {不是"))

    def test_grade(self):
        case = evals.load_cases(["protect-sources"])[0]
        tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        self.addCleanup(shutil.rmtree, tmp)
        work = tmp / "work"
        shutil.copytree(case["dir"] / "fixture", work)
        self.assertTrue(evals.grade(case, work, "")[0]["ok"])
        (work / "survey" / "parcels.csv").write_text("id,area\n1,100\n", encoding="utf-8")
        self.assertEqual(evals.grade(case, work, "")[0]["detail"], "已改动")

        case = {"dir": work, "checks": [
            {"type": "answer_json", "expect": {"crs": "EPSG:4326", "feature_count": 3, "k": ["majority", "mode"]}},
            {"type": "answer_contains", "any": ["受保护"]}]}
        good = evals.grade(case, work, '已登记为受保护源数据\n{"crs": "epsg:4326", "feature_count": 3, "k": "mode"}')
        self.assertEqual([c["ok"] for c in good], [True, True])
        bad = evals.grade(case, work, '{"crs": "unknown", "feature_count": 3, "k": "mode"}')
        self.assertEqual([c["ok"] for c in bad], [False, False])
        self.assertIn('"crs": "unknown"', bad[0]["detail"])

    def test_cc_command_variants(self):
        case = evals.load_cases(["describe-no-tools"])[0]
        with_shell = evals.cc_command(case, "with", None)
        without = evals.cc_command(case, "without", "sonnet")
        self.assertIn("--plugin-dir", with_shell)
        self.assertNotIn("--plugin-dir", without)
        for command in (with_shell, without):
            settings = json.loads(command[command.index("--settings") + 1])
            self.assertEqual(settings["enabledPlugins"], {evals.PLUGIN_ID: False})
            self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(without[-2:], ["--model", "sonnet"])

    def test_out_must_be_outside_repo(self):
        self.assertEqual(evals.main(["--out", str(ROOT / "evals" / "out")]), 2)


if __name__ == "__main__":
    unittest.main()
