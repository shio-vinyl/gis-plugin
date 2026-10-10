import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Manifests(unittest.TestCase):
    def test_versions_match(self):
        cc = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(cc["version"], codex["version"])
        self.assertRegex(cc["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
