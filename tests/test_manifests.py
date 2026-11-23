import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


ALLOWED_AGY_FIELDS = {
    "name", "description", "logo", "suggestedPrompts", "displayName",
    "version", "author", "homepage", "repository", "disabled",
}


class Manifests(unittest.TestCase):
    def test_versions_match(self):
        cc = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        agy = json.loads((ROOT / ".antigravity-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(cc["version"], codex["version"])
        self.assertEqual(cc["version"], agy["version"])
        self.assertRegex(cc["version"], r"^\d+\.\d+\.\d+$")

    def test_antigravity_manifest_uses_only_supported_fields(self):
        agy = json.loads((ROOT / ".antigravity-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(agy["name"], "gis-plugin")
        self.assertTrue(set(agy) <= ALLOWED_AGY_FIELDS, set(agy) - ALLOWED_AGY_FIELDS)


if __name__ == "__main__":
    unittest.main()
