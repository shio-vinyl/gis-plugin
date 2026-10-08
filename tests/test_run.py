import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIES = sorted(ROOT.glob("skills/*/scripts/run.py"))


class EngineLauncher(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        fake = self.tmp / "fake engine.py"
        fake.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        self.cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(fake))}"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_launcher(self, *args, **env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("GIS_")}
        base["GIS_PLUGIN_CONFIG"] = str(self.tmp / "engines.env")
        return subprocess.run([sys.executable, str(COPIES[0]), *args], env={**base, **env},
                              text=True, capture_output=True)

    def test_copies_are_identical(self):
        self.assertGreaterEqual(len(COPIES), 2)
        texts = {p.read_bytes() for p in COPIES}
        self.assertEqual(len(texts), 1, [str(p) for p in COPIES])

    def test_passes_arguments_through(self):
        result = self.run_launcher("gis-view", "open", "/data/with space", "--json", GIS_VIEW_CMD=self.cmd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["open", "/data/with space", "--json"])

    def test_unset_variable(self):
        result = self.run_launcher("gis-composer", "describe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GIS_COMPOSER_CMD", result.stderr)
        self.assertIn("gis-doctor", result.stderr)

    def test_unknown_engine_and_missing_executable(self):
        self.assertNotEqual(self.run_launcher("other").returncode, 0)
        result = self.run_launcher("gis-kit", "list", GIS_KIT_CMD=str(self.tmp / "missing"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gis-doctor", result.stderr)

    def test_shared_config_file_and_precedence(self):
        config = self.tmp / "engines.env"
        config.write_text("# comment\nGIS_VIEW_CMD=\"" + self.cmd.replace('"', '\\"') + "\"\nOTHER=1\n", encoding="utf-8")
        result = self.run_launcher("gis-view", "status")
        self.assertEqual(json.loads(result.stdout), ["status"], result.stderr)
        overridden = self.run_launcher("gis-view", "status", GIS_VIEW_CMD=str(self.tmp / "missing"))
        self.assertNotEqual(overridden.returncode, 0)

    def test_loader_is_identical_everywhere(self):
        import ast
        def source(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "engine_settings")
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node)
        files = [*COPIES, ROOT / "skills/gis-doctor/scripts/gis_doctor.py", ROOT / "hooks/scripts/inject_describe.py"]
        self.assertEqual(len({source(p) for p in files}), 1)


if __name__ == "__main__":
    unittest.main()
