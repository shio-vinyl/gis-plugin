import importlib.util
import json
import os
import shlex
import shutil
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
        report = doctor.run({"GIS_PLUGIN_CONFIG": "/nonexistent/engines.env"})
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
        with mock.patch.dict(os.environ, {"GIS_VIEW_CMD": self.engine("x", "{}"), "GIS_PLUGIN_CONFIG": "/nonexistent/engines.env"}, clear=True), \
                mock.patch("sys.stdout"):
            self.assertEqual(doctor.main([]), 1)
        with mock.patch.dict(os.environ, {"GIS_PLUGIN_CONFIG": "/nonexistent/engines.env"}, clear=True), mock.patch("sys.stdout"):
            self.assertEqual(doctor.main(["--json"]), 0)


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


if __name__ == "__main__":
    unittest.main()
