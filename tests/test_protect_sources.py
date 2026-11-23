import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "protect_sources.py"

sys.path.insert(0, str(SCRIPT.parent))  # the hooks import their shared `_patterns` module
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

    def test_output_options_of_any_command(self):
        for tool, command in [
            ("Bash", "python3 gis.py convert in.gpkg --output raw/a.gpkg --overwrite"),
            ("Bash", "python3 gis.py convert in.gpkg --output=raw/a.gpkg"),
            ("Bash", "python3 gis.py clip in.gpkg -o raw/a.gpkg"),
            ("Bash", "cd . && env X=1 python3 scripts/buffer.py in.gpkg --output 'raw/b c.gpkg'"),
            ("Bash", "plan-deck render a.pptx --out raw"),
            ("Bash", "tool --output-dir raw/run"),
            ("Bash", "sort -o raw/a.csv in.csv"),
            ("Bash", "curl -o dem/srtm.tif https://example.invalid/x"),
            ("pwsh", r"python gis.py convert in.gpkg --output raw\a.gpkg"),
            ("pwsh", r"& 'C:\py\python.exe' gis.py convert in.gpkg -o raw\a.gpkg"),
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.denied(tool, {"command": command}))
        for tool, command in [
            ("Bash", "python3 gis.py convert raw/a.gpkg --output out/a.gpkg"),
            ("Bash", "python3 gis.py clip raw/a.gpkg -o out/a.gpkg --output-layer raw"),
            ("Bash", "grep -o foo raw/a.csv"),
            ("Bash", "find raw -o -name x"),
            ("Bash", "tool --output"),
            ("pwsh", r"python gis.py convert raw\a.gpkg --output out\a.gpkg"),
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.denied(tool, {"command": command}))

    def test_sidecars_and_directories(self):
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "roads.dbf")}))
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "roads.shp.xml")}))
        self.assertTrue(self.denied("Write", {"file_path": str(self.data / "dem" / "srtm.tif.aux.xml")}))
        self.assertTrue(self.denied("Bash", {"command": "touch parcels.gdb/a0000001.gdbtable"}))
        self.assertFalse(self.denied("Write", {"file_path": str(self.data / "rivers.dbf")}))

    def test_case_follows_the_volume(self):
        spellings = [
            ("Write", {"file_path": str(self.data / "RAW" / "A.CSV")}),
            ("edit", {"file_path": str(self.data / "Raw" / "a.csv")}),
            ("Bash", {"command": "rm RAW/A.CSV"}),
            ("Bash", {"command": "echo x > Raw/a.csv"}),
            ("Bash", {"command": "cp new.csv RAW/A.CSV"}),
            ("apply_patch", {"command": f"*** Begin Patch\n*** Update File: {self.data}/RAW/A.CSV\n*** End Patch"}),
            ("Write", {"file_path": str(self.data / "ROADS.DBF")}),
            ("Write", {"file_path": str(self.data / "DEM" / "SRTM.TIF")}),
        ]
        with mock.patch.object(hook, "_ignores_case", return_value=True):
            for tool, tool_input in spellings:
                with self.subTest(tool=tool, tool_input=tool_input):
                    self.assertTrue(self.denied(tool, tool_input))
            self.assertFalse(self.denied("Write", {"file_path": str(self.data / "RAW2" / "A.CSV")}))
        with mock.patch.object(hook, "_ignores_case", return_value=False):  # RAW/ and raw/ are two directories here
            for tool, tool_input in spellings:
                with self.subTest(tool=tool, tool_input=tool_input):
                    self.assertFalse(self.denied(tool, tool_input))

    def test_case_probe_matches_this_volume(self):
        registry = self.data / ".gis" / "sources.json"
        insensitive = (self.data / ".gis" / "SOURCES.JSON").exists()
        self.assertEqual(hook._ignores_case(registry), insensitive)
        self.assertEqual(self.denied("Write", {"file_path": str(self.data / "RAW" / "A.CSV")}), insensitive)

    def test_powershell_writes(self):
        for command in [
            r"Set-Content raw\a.csv x",
            r"set-content -Path raw\a.csv -Value x",
            r"Set-Content -Path:raw\a.csv -Value x",
            r"Add-Content raw\a.csv 'x'",
            r"Clear-Content raw\a.csv",
            r"'x' | Out-File raw\a.csv",
            r"'x' | Out-File -FilePath raw\a.csv -Encoding utf8",
            r"'x' | Tee-Object raw\a.csv",
            r"Export-Csv -Path raw\a.csv -InputObject $x",
            r"New-Item raw\a.csv",
            r"Remove-Item raw\a.csv",
            r"Remove-Item -Recurse raw",
            r"ri raw\a.csv",
            r"del raw\a.csv",
            r"rm raw\a.csv",
            r"Move-Item raw\a.csv out.csv",
            r"Move-Item b.csv raw\a.csv",
            r"Rename-Item raw\a.csv b.csv",
            r"Copy-Item b.csv raw\a.csv",
            r"Copy-Item -Destination raw\a.csv b.csv",
            r"Copy-Item -Path b.csv -Dest:raw\a.csv",
            r"cp b.csv raw\a.csv",
            r"'x' > raw\a.csv",
            r"'x' >> raw\a.csv",
            r"Get-Date; Set-Content 'raw\b c.csv' x",
        ]:
            for tool in ("pwsh", "PowerShell"):
                with self.subTest(tool=tool, command=command):
                    self.assertTrue(self.denied(tool, {"command": command}))

    def test_powershell_reads_allowed(self):
        for command in [
            r"Get-Content raw\a.csv",
            r"Get-Content raw\a.csv | Set-Content out.csv",
            r"Copy-Item raw\a.csv out.csv",
            r"Copy-Item -Path raw\a.csv -Destination out.csv",
            r"cp raw\a.csv out.csv",
            r"Get-Content raw\a.csv > out.csv",
            r"Set-Content out.csv x",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.denied("pwsh", {"command": command}))

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
        self.assertIn("受保护", out["permissionDecisionReason"])
        self.assertIn("没有执行", out["permissionDecisionReason"])  # a model once reported the blocked command as run
        self.assertTrue(result.stdout.isascii())
        allowed = run(json.dumps({**payload, "tool_input": {"file_path": str(self.tmp / "ok.csv")}}))
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))
        broken = run("not json")
        self.assertEqual((broken.returncode, broken.stdout), (0, ""))
        self.assertIn("protect_sources", broken.stderr)

    def test_stdin_is_utf8_whatever_the_console_uses(self):
        self.register(["原始/**"])
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "原始/a.csv"}, "cwd": str(self.data)}, ensure_ascii=False)
        for raw in (payload.encode("utf-8"), b"\xef\xbb\xbf" + payload.encode("utf-8")):
            result = subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True,
                                    env={**os.environ, "PYTHONIOENCODING": "gbk"})
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny", result.stderr)

    def test_antigravity_tools_cd_and_strict_output(self):
        def ag_payload(name, args, cwd=None, use_workspace=False):
            doc = {"hookEventName": "PreToolUse", "conversationId": "c-1",
                   "toolCall": {"id": "call-1", "name": name, "args": args}}
            if use_workspace:
                doc["workspacePaths"] = [str(cwd or self.data)]
            else:
                doc["cwd"] = str(cwd or self.data)
            return doc

        target = str(self.data / "raw" / "a.gpkg")
        for tool, args in [
            ("write_file", {"Path": target, "Content": "x"}),
            ("edit_file", {"Path": target, "Target": "a", "Replacement": "b"}),
            ("write_to_file", {"TargetFile": target}),
            ("replace_file_content", {"TargetFile": target}),
            ("multi_replace_file_content", {"TargetFile": target}),
            ("notebook_edit", {"Path": str(self.data / "raw" / "n.ipynb")}),
            ("run_command", {"CommandLine": "rm raw/a.gpkg"}),
            ("run_command", {"CommandLine": "cd raw && rm a.gpkg"}),
            ("run_command", {"CommandLine": f"cd '{self.data}' && echo x > raw/a.csv"}),
        ]:
            with self.subTest(tool=tool, args=args):
                cwd = self.tmp if "cd '" in str(args) else self.data
                self.assertTrue(hook.decide(ag_payload(tool, args, cwd=cwd)))

        # workspacePaths fallback when cwd is omitted
        self.assertTrue(hook.decide(ag_payload("run_command", {"CommandLine": "rm raw/a.csv"}, use_workspace=True)))
        # subshell cd does not leak past `)`
        self.assertFalse(hook.decide(ag_payload("run_command", {"CommandLine": "(cd raw && cat a.csv) > out.csv"})))
        self.assertFalse(hook.decide(ag_payload("read_file", {"Path": target})))

        # CLI output uses strict Antigravity protojson: {"decision": "deny", "reason": ...}, empty stdout on allow
        denied = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                input=json.dumps(ag_payload("write_file", {"Path": target})))
        self.assertEqual(denied.returncode, 0, denied.stderr)
        out = json.loads(denied.stdout)
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "deny")
        self.assertIn("raw/**", out["reason"])
        self.assertTrue(denied.stdout.isascii())

        allowed = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                 input=json.dumps(ag_payload("write_file", {"Path": str(self.data / "out" / "ok.csv")})))
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
