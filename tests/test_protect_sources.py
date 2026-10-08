import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "protect_sources.py"

spec = importlib.util.spec_from_file_location("protect_sources", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class ProtectSources(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-")).resolve()
        self.data = self.tmp / "project" / "data"
        (self.data / ".gis").mkdir(parents=True)
        (self.data / "raw").mkdir()
        self.register(["raw/**", "dem/srtm.tif", "roads.shp", "parcels.gdb"])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def register(self, patterns, **extra):
        doc = {"contract": "sources", "schema_version": 1, "protected": patterns, **extra}
        (self.data / ".gis" / "sources.json").write_text(json.dumps(doc), encoding="utf-8")

    def denied(self, tool, tool_input, cwd=None):
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.data)}
        return bool(hook.decide(payload))

    def test_file_tools_across_harnesses(self):
        target = str(self.data / "raw" / "a.gpkg")
        self.assertTrue(self.denied("Write", {"file_path": target}))      # Claude Code
        self.assertTrue(self.denied("Edit", {"file_path": target}))
        self.assertTrue(self.denied("edit", {"file_path": target}))      # dsh bridge
        self.assertTrue(self.denied("NotebookEdit", {"notebook_path": str(self.data / "raw" / "n.ipynb")}))
        self.assertFalse(self.denied("Write", {"file_path": str(self.data / "out" / "a.gpkg")}))
        self.assertFalse(self.denied("Read", {"file_path": target}))

    def test_relative_paths_use_cwd_and_workdir(self):
        self.assertTrue(self.denied("Write", {"file_path": "raw/a.csv"}))
        self.assertTrue(self.denied("bash", {"command": "echo x > a.csv", "workdir": str(self.data / "raw")}, cwd=self.tmp))
        self.assertFalse(self.denied("Write", {"file_path": "raw/a.csv"}, cwd=self.tmp))

    def test_codex_apply_patch(self):
        def patch(kind, path):
            return {"command": f"*** Begin Patch\n*** {kind}: {path}\n+x\n*** End Patch"}
        self.assertTrue(self.denied("apply_patch", patch("Update File", self.data / "raw" / "a.csv")))
        self.assertTrue(self.denied("apply_patch", patch("Add File", self.data / "raw" / "new.csv")))
        self.assertTrue(self.denied("apply_patch", patch("Delete File", self.data / "roads.shp")))
        moved = {"command": f"*** Begin Patch\n*** Update File: {self.data}/out.csv\n*** Move to: {self.data}/raw/out.csv\n*** End Patch"}
        self.assertTrue(self.denied("apply_patch", moved))
        self.assertFalse(self.denied("apply_patch", patch("Add File", self.data / "out.csv")))

    def test_shell_writes(self):
        for command in [
            "echo x > raw/a.csv",
            "echo x >> raw/a.csv",
            "cat a | tee raw/b.csv",
            "rm -f raw/a.csv",
            "mv raw/a.csv done/",
            "cp new.tif dem/srtm.tif",
            "sed -i '' 's/a/b/' raw/a.csv",
            "ogr2ogr -update raw/a.gpkg new.geojson",
            "gdalwarp -t_srs EPSG:3857 in.tif dem/srtm.tif",
            "gdal_edit.py -a_srs EPSG:4326 dem/srtm.tif",
            "gdaladdo dem/srtm.tif 2 4",
            "dd if=/dev/zero of=dem/srtm.tif",
            "ls && sudo rm -rf raw",
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.denied("Bash", {"command": command}))

    def test_shell_reads_allowed(self):
        for command in [
            "ogrinfo -so raw/a.gpkg",
            "cat raw/a.csv > out/a.csv",
            "cp raw/a.csv out/a.csv",
            "gdalwarp dem/srtm.tif out/warped.tif",
            "ogr2ogr out/a.gpkg raw/a.gpkg",
            "python3 -c 'print(1)' 2>/dev/null",
            "echo 'unbalanced",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.denied("Bash", {"command": command}))

    def test_sidecars_and_directories(self):
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "roads.dbf")}))
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "roads.shp.xml")}))
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "dem" / "srtm.tif.aux.xml")}))
        self.assertTrue(self.denied("Bash", {"command": "touch parcels.gdb/a0000001.gdbtable"}))
        self.assertFalse(self.denied("Write", {"file_path": str(self.data / "rivers.dbf")}))

    def test_invalid_registry_fails_closed_in_its_tree_only(self):
        (self.data / ".gis" / "sources.json").write_text("{", encoding="utf-8")
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "anything.csv")}))
        self.assertFalse(self.denied("Write", {"file_path": str(self.tmp / "elsewhere.csv")}))
        for patterns in (["/abs/**"], ["../up"], [], [1]):
            with self.subTest(patterns=patterns):
                self.register(patterns)
                self.assertTrue(self.denied("Write", {"file_path": str(self.data / "x.csv")}))

    def test_cli_output_and_resilience(self):
        def run(stdin):
            return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, text=True, capture_output=True)
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(self.data / "raw" / "a.csv")}, "cwd": str(self.data)}
        result = run(json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("raw/**", out["permissionDecisionReason"])
        allowed = run(json.dumps({**payload, "tool_input": {"file_path": str(self.tmp / "ok.csv")}}))
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))
        broken = run("not json")
        self.assertEqual((broken.returncode, broken.stdout), (0, ""))
        self.assertIn("protect_sources", broken.stderr)


if __name__ == "__main__":
    unittest.main()
