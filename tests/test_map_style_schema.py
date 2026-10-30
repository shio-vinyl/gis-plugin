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
        }
        for name, sample in cases.items():
            with self.subTest(name):
                self.assertInvalid(sample)
        for name, change in {
            "version 2": lambda d: d.update(schema_version=2),
            "no layers": lambda d: d.update(layers=[]),
            "points units": lambda d: d.update(units={"size": "pt"}),
            "latitude out of range": lambda d: d.update(labelPlacements=[{"text": "x", "position": [114, 95],
                                                                           "style": {"size": 12, "color": "#000000"}}]),
        }.items():
            with self.subTest(name):
                sample = copy.deepcopy(doc())
                change(sample)
                self.assertInvalid(sample)


if __name__ == "__main__":
    unittest.main()
