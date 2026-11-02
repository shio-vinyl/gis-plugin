import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "inject_describe.py"

sys.path.insert(0, str(SCRIPT.parent))  # the hooks import their shared `_patterns` module
spec = importlib.util.spec_from_file_location("inject_describe", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

FAKE_KIT = r'''
import json, os, sys
from pathlib import Path
log = os.environ["FAKE_KIT_LOG"]
with open(log, "a") as f:
    f.write(sys.argv[2] + "\n")
path = Path(sys.argv[2])
if path.name.startswith("broken"):
    sys.exit("ERROR: cannot describe " + str(path) + ": not recognized as a supported file format")
if path.suffix == ".tif":
    card = {"contract": "describe", "schema_version": 1, "path": str(path), "kind": "raster", "driver": "GTiff",
            "revision": {"size": 1, "mtime": 0}, "raster": {"width": 50, "height": 40, "band_count": 1,
            "dtypes": ["float32"], "nodata": ["nan"], "crs": {"id": "EPSG:32650", "name": "WGS 84 / UTM zone 50N",
            "geographic": False, "units": "metre"}, "resolution": [30.0, 30.0], "extent": [500000.0, 2998800.0, 501500.0, 3000000.0]},
            "warnings": []}
else:
    card = {"contract": "describe", "schema_version": 1, "path": str(path), "kind": "vector", "driver": "GPKG",
            "revision": {"size": 1, "mtime": 0}, "layer_count": 1, "layers": [{"name": "地类图斑",
            "geometry_type": "Polygon", "feature_count": None, "crs": None, "extent": None,
            "fields": [{"name": "f%d" % i, "type": "string"} for i in range(40)], "field_count": 45}],
            "warnings": [{"code": "crs_missing", "message": "图层 地类图斑 没有 CRS"}]}
print(json.dumps(card, ensure_ascii=False))
'''


class InjectDescribe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-")).resolve()
        self.data = self.tmp / "data"
        self.data.mkdir()
        for name in ("地类图斑.gpkg", "dem.tif", "broken.shp", "notes.txt"):
            (self.data / name).write_text("x", encoding="utf-8")
        kit = self.tmp / "fake_kit.py"
        kit.write_text(FAKE_KIT, encoding="utf-8")
        self.log = self.tmp / "calls.log"
        self.env = {"GIS_KIT_CMD": f"{shlex.quote(sys.executable)} {shlex.quote(str(kit))}",
                    "FAKE_KIT_LOG": str(self.log), "GIS_PLUGIN_STATE": str(self.tmp / "state"),
                    "GIS_PLUGIN_CONFIG": str(self.tmp / "engines.env")}
        patcher = mock.patch.dict(os.environ, {"FAKE_KIT_LOG": str(self.log)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def prompt(self, text, session="s1"):
        return {"hook_event_name": "UserPromptSubmit", "prompt": text, "cwd": str(self.tmp), "session_id": session}

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_candidates_from_prose_and_commands(self):
        found = hook.candidates(self.prompt("看看data/地类图斑.gpkg的字段，再和 ./data/dem.tif 比较；missing.shp 不存在"))
        self.assertEqual(found, [self.data / "地类图斑.gpkg", self.data / "dem.tif"])
        bash = {"hook_event_name": "PostToolUse", "cwd": str(self.tmp),
                "tool_input": {"command": "ogrinfo -so '地类图斑.gpkg' && cat notes.txt", "workdir": str(self.data)}}
        self.assertEqual(hook.candidates(bash), [self.data / "地类图斑.gpkg"])

    def test_cards_render_facts(self):
        context = hook.run(self.prompt("data/地类图斑.gpkg 和 data/dem.tif"), self.env)
        self.assertIn("矢量，图层 1 个", context)
        self.assertIn("要素数未知；无 CRS；范围未知", context)
        self.assertIn("字段 45 个", context)
        self.assertIn("另 15 个未列出", context)
        self.assertIn("注意：图层 地类图斑 没有 CRS", context)
        self.assertIn("50×40，1 个波段 float32；NoData nan；分辨率 30×30；CRS EPSG:32650", context)
        self.assertIn("范围 [500000, 2998800, 501500, 3000000]", context)
        self.assertNotRegex(context, "请|应该|建议")

    def test_once_per_session_until_file_changes(self):
        payload = self.prompt("data/dem.tif")
        self.assertIsNotNone(hook.run(payload, self.env))
        self.assertIsNone(hook.run(payload, self.env))
        self.assertIsNotNone(hook.run(self.prompt("data/dem.tif", session="s2"), self.env))
        (self.data / "dem.tif").write_text("changed", encoding="utf-8")
        self.assertIsNotNone(hook.run(payload, self.env))
        self.assertEqual(len(self.calls()), 3)

    def test_state_location_comes_from_the_given_environment(self):
        home = self.tmp / "home"
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            os.environ.pop("GIS_PLUGIN_STATE", None)
            self.assertIsNotNone(hook.run(self.prompt("data/dem.tif"), self.env))
        self.assertFalse(home.exists())
        self.assertEqual([p.name for p in (self.tmp / "state" / "describe-seen").iterdir()], ["s1.json"])

    def test_limits_failures_and_missing_engine(self):
        for i in range(5):
            (self.data / f"l{i}.gpkg").write_text("x", encoding="utf-8")
        context = hook.run(self.prompt(" ".join(f"data/l{i}.gpkg" for i in range(5))), self.env)
        self.assertEqual(context.count("[gis-kit describe] "), hook.MAX_FILES)
        broken = hook.run(self.prompt("data/broken.shp"), self.env)
        self.assertIn("无法读取", broken)
        self.assertIsNone(hook.run(self.prompt("data/dem.tif"), {k: v for k, v in self.env.items() if k != "GIS_KIT_CMD"}))
        self.assertIsNone(hook.run(self.prompt("没有路径"), self.env))

    def write_semantics(self, doc):
        (self.tmp / ".gis").mkdir(exist_ok=True)
        (self.tmp / ".gis" / "semantics.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_semantics_declarations(self):
        self.write_semantics({"contract": "semantics", "schema_version": 1, "datasets": [
            {"match": "data/*.gpkg", "fields": {"f_a": {"kind": "total", "unit": "人"}, "f_b": {"kind": "ratio"}}},
            {"match": "data/地类图斑.gpkg", "layer": "地类图斑",
             "fields": {"f_b": {"kind": "density", "unit": "人/km²", "note": "按图斑面积"}}},
            {"match": "data/dem.tif", "bands": {"1": {"kind": "density", "unit": "mm"}}},
            {"match": "other/**", "fields": {"x": {"kind": "category"}}},
        ]})
        context = hook.run(self.prompt("data/地类图斑.gpkg 和 data/dem.tif"), self.env)
        self.assertIn(f"[semantics] {self.data / '地类图斑.gpkg'} — 用户声明于 {self.tmp / '.gis' / 'semantics.json'}", context)
        self.assertIn("· 字段 f_a：总量（total），单位 人", context)
        self.assertIn("· 字段 f_b：比率（ratio）", context)
        self.assertIn("· 图层 地类图斑 字段 f_b：密度（density），单位 人/km²；用户备注“按图斑面积”", context)
        self.assertIn("· 波段 1：密度（density），单位 mm", context)
        self.assertNotIn("字段 x", context)
        self.assertNotRegex(context.replace("按图斑面积", ""), "请|应该|建议")
        # each file's describe card is followed by its own declarations
        gpkg, tif = context.split("\n\n")[1:]
        self.assertTrue(gpkg.startswith("[gis-kit describe]") and "[semantics]" in gpkg)
        self.assertTrue(tif.startswith("[gis-kit describe]") and "波段 1" in tif)

    def test_semantics_without_engine_and_on_change(self):
        doc = {"contract": "semantics", "schema_version": 1,
               "datasets": [{"match": "data/dem.tif", "bands": {"1": {"kind": "total"}}}]}
        self.write_semantics(doc)
        no_kit = {k: v for k, v in self.env.items() if k != "GIS_KIT_CMD"}
        payload = self.prompt("data/dem.tif")
        context = hook.run(payload, no_kit)
        self.assertIn("[semantics]", context)
        self.assertNotIn("[gis-kit describe] ", context)
        self.assertIsNone(hook.run(payload, no_kit))
        doc["datasets"][0]["bands"]["1"]["unit"] = "t"
        self.write_semantics(doc)
        os.utime(self.tmp / ".gis" / "semantics.json", (1, 1))
        self.assertIn("单位 t", hook.run(payload, no_kit))
        self.assertIsNone(hook.run(self.prompt("data/地类图斑.gpkg"), no_kit))  # nothing declared, no engine

    def test_invalid_semantics_reported(self):
        self.write_semantics({"contract": "semantics", "schema_version": 1,
                              "datasets": [{"match": "../x", "fields": {"a": {"kind": "total"}}}]})
        context = hook.run(self.prompt("data/dem.tif"), self.env)
        self.assertIn("[gis-kit describe] ", context)
        self.assertIn("semantics.json 无效：datasets[0].match 须为相对路径模式且不含 ..", context)
        self.write_semantics({"contract": "semantics", "schema_version": 1,
                              "datasets": [{"match": "data/*", "fields": {"a": {"kind": "mean"}}}]})
        self.assertIn("kind 须为 total/density/ratio/category 之一", hook.run(self.prompt("data/dem.tif", "s9"), self.env))

    def test_cli_output_and_resilience(self):
        def run(stdin):
            return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, text=True, capture_output=True,
                                  env={**os.environ, **self.env})
        result = run(json.dumps(self.prompt("data/dem.tif")))
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertIn("[gis-kit describe]", out["additionalContext"])
        self.assertTrue(out["additionalContext"].startswith(hook.SOURCE_LINE))
        self.assertTrue(result.stdout.isascii())
        broken = run("not json")
        self.assertEqual((broken.returncode, broken.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
