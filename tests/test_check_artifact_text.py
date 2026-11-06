import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "check_artifact_text.py"

sys.path.insert(0, str(SCRIPT.parent))  # the hook imports its sibling hooks
spec = importlib.util.spec_from_file_location("check_artifact_text", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

RULES, ATTRIBUTION = hook.load_rules()


def svg(*texts):
    return '<svg xmlns="http://www.w3.org/2000/svg">' + "".join(texts) + "</svg>"


def pptx(path, slides, notes=(), order=None, hidden=()):
    """A minimal deck: `slides` are lists of paragraphs; `order` lists slide numbers as presented."""
    order = order or list(range(1, len(slides) + 1))
    body = lambda paras, show="": (f"<p:sld xmlns:p='p' xmlns:a='a'{show}><p:cSld><p:spTree><p:sp><p:txBody>"
                          + "".join(f"<a:p><a:r><a:t>{p}</a:t></a:r></a:p>" for p in paras)
                          + "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/presentation.xml", "<p:presentation><p:sldIdLst>" + "".join(
            f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order) + "</p:sldIdLst></p:presentation>")
        zf.writestr("ppt/_rels/presentation.xml.rels", "<Relationships>" + "".join(
            f'<Relationship Id="rId{n}" Type="slide" Target="slides/slide{n}.xml"/>' for n in range(1, len(slides) + 1))
            + "</Relationships>")
        for n, paras in enumerate(slides, 1):
            zf.writestr(f"ppt/slides/slide{n}.xml", body(paras, ' show="0"' if n in hidden else ""))
        for n, paras in enumerate(notes, 1):
            zf.writestr(f"ppt/notesSlides/notesSlide{n}.xml", body(paras))


class Wording(unittest.TestCase):
    def hit(self, line):
        hits = hook.find_hits([(line, "")], RULES, ATTRIBUTION)
        return hits[0]["category"] if hits else None

    def test_banned_lines(self):
        for line, category in [
            ("范围示意，非权属边界", "免责、口径"),
            ("仅供参考", "免责、口径"),
            ("面积以最终批复为准", "免责、口径"),
            ("红线不代表法定边界", "免责、口径"),
            ("不作审批依据", "免责、口径"),
            ("岸线经简化处理", "免责、口径"),
            ("坐标未经核实", "免责、口径"),
            ("数据精度有限", "免责、口径"),
            ("二期用地待定", "待定、核查"),
            ("暂不讨论", "待定、核查"),
            ("范围以批复为准", "免责、口径"),
            ("两组数字不冲突", "解说、自我澄清"),
            ("这不是年度的数字", "解说、自我澄清"),
            ("注：面积为估算", "解说、自我澄清"),
            ("说明: 见附表", "解说、自我澄清"),
            ("本图按 2024 年现状绘制", "解说、自我澄清"),
            ("图中虚线表示规划路", "解说、自我澄清"),
            ("数据来源：自然资源部，仅供参考", "免责、口径"),  # an attribution line is still read after its opening
        ]:
            with self.subTest(line=line):
                self.assertEqual(self.hit(line), category)

    def test_content_and_attribution_pass(self):
        for line in ["滨江公园 12.5 公顷", "示意图", "该图斑面积 3.2 公顷", "© OpenStreetMap contributors",
                     "数据来源：自然资源部标准地图服务", "底图来源：天地图", "注重慢行连续", "为准备期预留",
                     "暂不推荐", "不以申请人自报为准", "以人为本"]:
            with self.subTest(line=line):
                self.assertIsNone(self.hit(line))

    def test_patterns_are_plain_regex(self):
        doc = json.loads(hook.LIST_FILE.read_text(encoding="utf-8"))
        self.assertEqual([c["name"] for c in doc["categories"]], ["免责、口径", "待定、核查", "解说、自我澄清"])
        for category in doc["categories"]:
            for pattern in category["patterns"]:
                self.assertNotRegex(pattern, r"\(\?[P<]", "named groups and lookbehind differ between Python and JS")


class Extraction(unittest.TestCase):
    def test_svg_text_tspan_and_vertical_runs(self):
        lines = dict((w, t) for t, w in hook.svg_lines(svg(
            '<text x="10" y="20">滨江<tspan>公园</tspan></text>',
            '<text x="1" y="2"><tspan x="1">岸线经</tspan><tspan x="1" dy="1">简化</tspan></text>',
            '<text x="5" y="1">本</text><text x="5" y="2">图</text>',
            "<text>&#x4ED3;&amp;库</text>")))
        self.assertIn("第 2 个 <text>（x=1, y=2）（各行连读）", lines)
        self.assertEqual(lines["第 2 个 <text>（x=1, y=2）（各行连读）"], "岸线经简化")
        self.assertEqual(lines["第 3 个 <text>（x=5, y=1） 起的 2 个单字（竖排连读）"], "本图")
        self.assertEqual(lines["第 5 个 <text>"], "仓&库")

    def test_pptx_slides_in_presented_order_without_notes_or_hidden_slides(self):
        tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-"))
        try:
            deck = tmp / "汇报.pptx"
            pptx(deck, [["岸线经简化"], ["标题"], ["待补草稿"]], notes=[["注：口径见附表"]], order=[2, 1, 3], hidden=[3])
            lines = hook.pptx_lines(deck)
            self.assertFalse(any("待补" in t for t, _ in lines))
            self.assertIn(("岸线经简化", "第 2 页"), lines)
            self.assertIn(("标题", "第 1 页"), lines)
            self.assertFalse(any("口径" in t for t, _ in lines))
        finally:
            shutil.rmtree(tmp)

    def test_pptx_line_breaks_and_runs(self):
        xml = ("<p:txBody><a:p><a:r><a:t>二期</a:t></a:r><a:r><a:t>用地待定</a:t></a:r><a:br/>"
               "<a:r><a:t>另起一行</a:t></a:r></a:p></p:txBody>")
        lines = [t for t, _ in hook._text_bodies(xml, "第 1 页")]
        self.assertEqual(lines, ["二期用地待定", "另起一行", "二期用地待定另起一行"])

    def test_html_visible_text_only(self):
        lines = [t for t, _ in hook.html_lines(
            "<html><head><title>滨江</title><style>.a{content:'仅供参考'}</style>"
            "<script>alert('暂不支持')</script></head><body><!-- 待补 --><p>岸线<b>经简化</b></p><div>公园</div></body></html>")]
        self.assertEqual(lines, ["滨江", "岸线经简化", "公园"])


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gis-plugin-test-")).resolve()
        self.project = self.tmp / "项目 甲"
        (self.project / "out").mkdir(parents=True)
        self.env = {"GIS_PLUGIN_STATE": str(self.tmp / "state")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def payload(self, tool, tool_input, session="s1"):
        return {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input,
                "cwd": str(self.project), "session_id": session}

    def write(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def test_write_tools_across_harnesses(self):
        bad = self.write("out/a.svg", svg('<text x="1" y="2">范围示意，以批复为准</text>'))
        for tool in ("Write", "Edit", "MultiEdit", "write", "edit"):
            with self.subTest(tool=tool):
                reason = hook.run(self.payload(tool, {"file_path": str(bad)}), self.env)
                self.assertIn(str(bad), reason)
                self.assertIn("“范围示意，以批复为准”（第 1 个 <text>（x=1, y=2））", reason)
                self.assertIn("免责、口径", reason)
                self.assertIn(hook.NOTE, reason)
        patch = {"command": f"*** Begin Patch\n*** Add File: {bad}\n+x\n*** End Patch"}
        self.assertIn(str(bad), hook.run(self.payload("apply_patch", patch), self.env))  # Codex

    def test_clean_and_non_artifact_files_pass(self):
        good = self.write("out/a.svg", svg("<text>滨江公园</text>", "<text>© OpenStreetMap contributors</text>",
                                           "<text>数据来源：天地图</text>"))
        self.assertIsNone(hook.run(self.payload("Write", {"file_path": str(good)}), self.env))
        script = self.write("make.py", "LABEL = '仅供参考'\n")
        self.assertIsNone(hook.run(self.payload("Write", {"file_path": str(script)}), self.env))
        self.assertIsNone(hook.run(self.payload("Read", {"file_path": str(good)}), self.env))

    def test_pptx_hit_and_notes_pass(self):
        deck = self.project / "out" / "汇报.pptx"
        pptx(deck, [["滨江公园"], ["二期用地待定"]], notes=[["说明：口径以统计年鉴为准"]])
        reason = hook.run(self.payload("Write", {"file_path": str(deck)}), self.env)
        self.assertIn("“二期用地待定”（第 2 页）：命中“待定”，待定、核查", reason)
        pptx(deck, [["滨江公园"]], notes=[["说明：口径以统计年鉴为准"]])
        self.assertIsNone(hook.run(self.payload("Write", {"file_path": str(deck)}), self.env))

    def test_bash_finds_recent_artifacts_once_per_version(self):
        bash = self.payload("Bash", {"command": "python3 make.py"})
        deck = self.project / "out" / "汇报.pptx"
        pptx(deck, [["本图据 2024 年现状编制"]])
        reason = hook.run(bash, self.env)
        self.assertIn(str(deck), reason)
        self.assertIn("解说、自我澄清", reason)
        self.assertIsNone(hook.run(bash, self.env))  # already reported, unchanged
        pptx(deck, [["本图据 2024 年现状编制", "待补"]])
        os.utime(deck, (time.time() + 2, time.time() + 2))
        self.assertIn("待定、核查", hook.run(bash, self.env))  # rewritten: checked again
        self.assertIn(str(deck), hook.run({**bash, "session_id": "s2"}, self.env))  # another session

    def test_bash_scan_bounds(self):
        old = self.write("out/old.svg", svg("<text>仅供参考</text>"))
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        self.write("node_modules/pkg/a.html", "<p>仅供参考</p>")
        self.write(".cache/a.svg", svg("<text>仅供参考</text>"))
        self.write("notes.md", "仅供参考")
        bash = self.payload("bash", {"command": "make"})
        self.assertIsNone(hook.run(bash, self.env))
        page = self.write("site/index.html", "<p>注：数据未经核实</p>")
        self.assertIn(str(page), hook.run({**bash, "tool_name": "pwsh"}, self.env))

    def test_bash_output_outside_the_project(self):
        elsewhere = self.tmp / "别处" / "图.svg"
        elsewhere.parent.mkdir()
        elsewhere.write_text(svg("<text>此图仅示意</text>"), encoding="utf-8")
        reason = hook.run(self.payload("Bash", {"command": f"node draw.js -o '{elsewhere}'"}), self.env)
        self.assertIn(str(elsewhere), reason)

    def test_bash_does_not_walk_the_home_directory(self):
        payload = self.payload("Bash", {"command": "ls"})
        payload["cwd"] = str(Path.home())
        self.assertEqual(hook.candidates(payload, self.env, time.time()), ([], []))

    def test_main_blocks_with_ascii_json(self):
        bad = self.write("out/a.svg", svg("<text>岸线经简化</text>"))
        done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, timeout=60,
                              input=json.dumps(self.payload("Write", {"file_path": str(bad)}), ensure_ascii=False).encode(),
                              env={**os.environ, **self.env, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        out = json.loads(done.stdout.decode("ascii"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("岸线经简化", out["reason"])

    def test_broken_input_never_blocks(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], input=b"not json", capture_output=True, timeout=60,
                              env={**os.environ, **self.env, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual((done.returncode, done.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
