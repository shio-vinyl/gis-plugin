import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "map-style.schema.json"
README = ROOT / "contracts" / "README.md"


def readme_example():
    """The JSON example under `## map-style` in contracts/README.md, so the documented example stays valid."""
    text = README.read_text(encoding="utf-8")
    section = text[text.index("## map-style"):]
    return json.loads(re.search(r"```json\n(.*?)\n```", section, re.S).group(1))


def doc(**layer):
    base = {"id": "a", "geometry": "polygon", "data": {"path": "inputs/a.geojson"},
            "renderer": {"type": "single", "symbol": {"fill": {"color": "#112233"}}}}
    return {"contract": "map-style", "schema_version": 1, "id": "m", "units": {"size": "px"}, "layers": [{**base, **layer}]}


class MapStyleSchema(unittest.TestCase):
    def setUp(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        self.validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def assertValid(self, sample):
        errors = [e.message for e in self.validator.iter_errors(sample)]
        self.assertEqual(errors, [])

    def assertInvalid(self, sample):
        self.assertFalse(self.validator.is_valid(sample))

    def test_schema_is_valid(self):
        self.validator.check_schema(self.validator.schema)

    def test_readme_example(self):
        self.assertValid(readme_example())

    def test_renderers(self):
        stroke = {"stroke": {"color": "#FFFFFF", "width": 0.8, "dash": [5, 1.5, 1, 1.5], "cap": "round"}}
        for renderer in [
            {"type": "graduated", "field": "far", "method": "quantile",
             "classes": [{"range": [0, 1.5], "label": "≤1.5", "symbol": {"fill": {"color": "#EEEEEE"}}}], "default": None},
            {"type": "rule", "rules": [{"filter": {"all": [{"field": "s", "op": "in", "value": ["a", "b"]},
                                                           {"not": {"field": "k", "op": "isNull"}}]}, "symbol": stroke}]},
            {"type": "rule", "rules": [{"filter": {"expression": "\"s\" LIKE 'a%'", "dialect": "qgis"}, "symbol": stroke}]},
        ]:
            with self.subTest(renderer=renderer["type"]):
                self.assertValid(doc(renderer=renderer))
        raster = {"type": "pseudocolor", "band": 1, "stretch": {"method": "percentile", "low": 2, "high": 98},
                  "interpolation": "linear", "stops": [{"value": 0, "color": "#000000"}, {"value": 1, "color": "#FFFFFF"}]}
        self.assertValid(doc(geometry="raster", data={"path": "@dem/a.tif"}, renderer=raster))
        circles = doc(geometry="point", renderer={"type": "categorized", "field": "phase", "classes": [
            {"value": "built", "symbol": {"marker": {"shape": "circle", "size": 6}, "fill": {"color": "#9DC3E6"}}}]},
            size={"field": "amount", "scale": "sqrt", "domain": [0, 16], "range": [3, 10], "clamp": True},
            sortBy={"field": "amount", "order": "desc"})
        self.assertValid(circles)

    def test_panels_background_notes_and_text(self):
        sample = doc(panel="main", data={"path": "inputs/a.geojson", "kind": "vector"},
                     labels={"field": "n", "enabled": True,
                             "text": {"font": "GC Sans", "size": 12, "color": "#333333", "opacity": 0.9, "letterSpacing": 0.08,
                                      "halo": {"color": "#FFFFFF", "width": 2, "opacity": 0.78, "blur": 0.6},
                                      "box": {"fill": {"color": "#FFFFFF", "opacity": 0.8}, "padding": 2}}})
        sample["background"] = {"color": "#B4D6E2"}
        sample["extent"] = {"bbox": [114.0, 22.5, 114.1, 22.6], "panels": [{"id": "main", "bbox": [114.0, 22.5, 114.1, 22.6]}]}
        sample["notes"] = [{"kind": "approximated", "panel": "main", "layer": "a", "property": "text-halo-blur", "reason": "no field"}]
        sample["labelPlacements"] = [{"text": "x", "position": [114.05, 22.55], "rotation": 15,
                                      "leader": [[114.06, 22.54], [114.05, 22.55]], "leaderStroke": {"color": "#666666", "width": 0.8},
                                      "style": {"size": 12, "color": "#000000"}}]
        self.assertValid(sample)
        self.assertValid(doc(geometry="point", renderer={"type": "single", "symbol": {
            "marker": {"shape": "arrow", "size": 8, "rotation": 90}, "fill": {"color": "#000000"}}}))

    def test_markers_patterns_and_weights(self):
        svg = {"path": "assets/icons/a.svg", "sha256": "0" * 64}
        line = lambda marker: doc(geometry="line", renderer={"type": "single", "symbol": {
            "stroke": {"color": "#000000", "width": 1}, "marker": marker}})
        point = lambda marker: doc(geometry="point", renderer={"type": "single", "symbol": {"marker": marker}})
        hatch = lambda pattern: doc(renderer={"type": "single", "symbol": {"fill": {"color": "#FFFFFF", "opacity": 0, "pattern": pattern}}})
        text = lambda **style: doc(labels={"field": "n", "text": {"size": 12, "color": "#000000", **style}})
        for name, sample in {
            "along line": line({"shape": "chevron", "size": 7, "placement": "line", "spacing": 80, "alongLine": True, "rotation": 90}),
            "along line, upright": line({"shape": "arrow", "size": 7, "placement": "line", "spacing": 40, "alongLine": False}),
            "svg": point({"shape": "svg", "size": 12, "svg": svg}),
            "svg in external root": point({"shape": "svg", "size": 12, "svg": {**svg, "path": "@icons/a.svg"}}),
            "rotation field": point({"shape": "arrow", "size": 8, "rotation": 90, "rotationField": "angle"}),
            "hatch": hatch({"kind": "hatch", "angle": 45, "spacing": 6, "width": 0.8, "color": "#333333", "opacity": 0.6}),
            "cross hatch": hatch({"kind": "crossHatch", "spacing": 4, "width": 0.5, "color": "#333333"}),
            "padding": text(box={"padding": 2}),
            "padding vertical, horizontal": text(box={"padding": [3, 6]}),
            "padding four sides": text(box={"padding": [3, 6, 3, 6]}),
            "text weight": text(font="GC Sans", weight=500),
            "text weight string": text(font="GC Sans", weight="700"),
        }.items():
            with self.subTest(name):
                self.assertValid(sample)
        for name, sample in {
            "along line without spacing": line({"shape": "chevron", "size": 7, "placement": "line"}),
            "zero spacing": line({"shape": "chevron", "size": 7, "placement": "line", "spacing": 0}),
            "unknown placement": line({"shape": "chevron", "size": 7, "placement": "vertex", "spacing": 10}),
            "alongLine not boolean": line({"shape": "chevron", "size": 7, "placement": "line", "spacing": 10, "alongLine": "yes"}),
            "svg without image": point({"shape": "svg", "size": 12}),
            "svg without hash": point({"shape": "svg", "size": 12, "svg": {"path": "assets/icons/a.svg"}}),
            "svg absolute path": point({"shape": "svg", "size": 12, "svg": {**svg, "path": "/icons/a.svg"}}),
            "svg climbs out": point({"shape": "svg", "size": 12, "svg": {**svg, "path": "../icons/a.svg"}}),
            "empty rotation field": point({"shape": "arrow", "size": 8, "rotationField": ""}),
            "unknown pattern": hatch({"kind": "dots", "spacing": 6, "width": 0.8, "color": "#333333"}),
            "pattern without spacing": hatch({"kind": "hatch", "width": 0.8, "color": "#333333"}),
            "pattern zero spacing": hatch({"kind": "hatch", "spacing": 0, "width": 0.8, "color": "#333333"}),
            "pattern colour with alpha": hatch({"kind": "hatch", "spacing": 6, "width": 0.8, "color": "#33333380"}),
            "padding three numbers": text(box={"padding": [3, 6, 3]}),
            "negative padding": text(box={"padding": [3, -1]}),
            "weight too heavy": text(weight=950),
            "weight too light": text(weight=50),
            "weight keyword": text(weight="bold"),
            "weight with unit": text(weight="500px"),
        }.items():
            with self.subTest(name):
                self.assertInvalid(sample)

    def test_fonts_panels_and_frames(self):
        sample = doc(panel="inset")
        sample["fonts"] = [{"family": "GC Sans", "weight": 400}, {"family": "GC Sans", "weight": "500"}]
        sample["extent"] = {"bbox": [114.0, 22.5, 114.1, 22.6], "print": {"widthCm": 20, "heightCm": 14, "dpi": 300},
                            "panels": [{"id": "main", "bbox": [114.0, 22.5, 114.1, 22.6],
                                        "frame": {"x": 0, "y": 0, "width": 20, "height": 14}},
                                       {"id": "inset", "bbox": [114.0, 22.5, 114.02, 22.52],
                                        "frame": {"x": 14.5, "y": 0.5, "width": 5, "height": 4}}]}
        sample["labelPlacements"] = [{"panel": "inset", "text": "x", "position": [114.01, 22.51], "style": {"size": 12, "color": "#000000"}}]
        self.assertValid(sample)
        for name, change in {
            "font weight too heavy": lambda d: d["fonts"][0].update(weight=1000),
            "font weight keyword": lambda d: d["fonts"][0].update(weight="medium"),
            "empty placement panel": lambda d: d["labelPlacements"][0].update(panel=""),
            "frame without height": lambda d: d["extent"]["panels"][1]["frame"].pop("height"),
            "frame zero width": lambda d: d["extent"]["panels"][1]["frame"].update(width=0),
            "frame off the page": lambda d: d["extent"]["panels"][1]["frame"].update(x=-1),
        }.items():
            with self.subTest(name):
                broken = copy.deepcopy(sample)
                change(broken)
                self.assertInvalid(broken)

    def test_data_kind_and_geometry(self):
        rgb = {"type": "rgb", "bands": [1, 2, 3]}
        lines = {"type": "single", "symbol": {"stroke": {"color": "#000000", "width": 1}}}
        for kind, geometry, renderer in [("raster", "raster", rgb), ("rasterTiles", "raster", rgb),
                                         ("vector", "point", lines), ("vector", "polygon", lines),
                                         ("vectorTiles", "line", lines), ("vectorTiles", "polygon", lines)]:
            with self.subTest(kind=kind, geometry=geometry):
                self.assertValid(doc(geometry=geometry, data={"path": "@basemap/a", "kind": kind}, renderer=renderer))
        for kind, geometry, renderer in [("raster", "polygon", lines), ("rasterTiles", "point", lines),
                                         ("vector", "raster", rgb), ("vectorTiles", "raster", rgb)]:
            with self.subTest(kind=kind, geometry=geometry):
                self.assertInvalid(doc(geometry=geometry, data={"path": "@basemap/a", "kind": kind}, renderer=renderer))

    def test_unknown_fields_are_allowed(self):
        sample = doc()
        sample["futureField"] = {"x": 1}
        sample["layers"][0]["futureLayerField"] = True
        self.assertValid(sample)

    def test_rejections(self):
        cases = {
            "absolute path": doc(data={"path": "/Users/a/data.geojson"}),
            "windows path": doc(data={"path": "C:\\data\\a.shp"}),
            "home path": doc(data={"path": "~/data/a.shp"}),
            "climbs out": doc(data={"path": "inputs/../../a.shp"}),
            "colour with alpha": doc(renderer={"type": "single", "symbol": {"fill": {"color": "#11223344"}}}),
            "raster renderer on vector": doc(renderer={"type": "rgb", "bands": [1, 2, 3]}),
            "vector renderer on raster": doc(geometry="raster"),
            "in without list": doc(filter={"field": "s", "op": "in", "value": "a"}),
            "compare without value": doc(filter={"field": "s", "op": "=="}),
            "empty symbol": doc(renderer={"type": "single", "symbol": {}}),
            "labels with field and template": doc(labels={"field": "n", "template": "{n}", "text": {"size": 12, "color": "#000000"}}),
            "unknown marker shape": doc(geometry="point", renderer={"type": "single", "symbol": {"marker": {"shape": "airport", "size": 6}}}),
            "unknown data kind": doc(data={"path": "inputs/a.geojson", "kind": "database"}),
            "empty panel": doc(panel=""),
        }
        for name, sample in cases.items():
            with self.subTest(name):
                self.assertInvalid(sample)
        for name, change in {
            "version 2": lambda d: d.update(schema_version=2),
            "no layers": lambda d: d.update(layers=[]),
            "points units": lambda d: d.update(units={"size": "pt"}),
            "note without reason": lambda d: d.update(notes=[{"kind": "approximated"}]),
            "unknown note kind": lambda d: d.update(notes=[{"kind": "lost", "reason": "x"}]),
            "background with alpha": lambda d: d.update(background={"color": "#B4D6E2CC"}),
            "latitude out of range": lambda d: d.update(labelPlacements=[{"text": "x", "position": [114, 95],
                                                                           "style": {"size": 12, "color": "#000000"}}]),
        }.items():
            with self.subTest(name):
                sample = copy.deepcopy(doc())
                change(sample)
                self.assertInvalid(sample)


if __name__ == "__main__":
    unittest.main()
