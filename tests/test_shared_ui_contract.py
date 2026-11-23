"""Verify P4's registered headless module against the pinned P1 schemas."""
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


@unittest.skipUnless(HAS_JSONSCHEMA, "Install the pinned MCP SDK candidate, which stages jsonschema, for shared UI schema checks.")
class SharedUiContractTests(unittest.TestCase):
    def read(self, path):
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_p4_contribution_matches_p1_ui_module_contract(self):
        import jsonschema
        schema = self.read("research/p1-suite-ui-reference/suite-ui-module.v1.schema.json")
        contribution = self.read("products/p4/ui_contribution.json")
        jsonschema.Draft202012Validator(schema).validate(contribution)
        self.assertEqual(contribution["route"], "/fab-intelligence/p4")
        self.assertEqual(contribution["module_export"], "P4Panel")
        self.assertEqual(contribution["ownership"]["suite_shell"], "single-suite-host")

    def test_p4_scatter_payload_matches_p1_chart_contract(self):
        import jsonschema
        schema = self.read("research/p1-suite-ui-reference/suite-chart.v1.schema.json")
        model = {"schema_version": "suite-chart.v1", "chart_id": "p4-test", "kind": "scatter",
                 "title": "Observed tradeoff means", "x_label": "yield (maximize)", "y_label": "defect (minimize)",
                 "series": [{"id": "defect", "label": "defect", "style": "markers"}],
                 "points": [{"x": 88.2, "values": {"defect": 1.3}}]}
        jsonschema.Draft202012Validator(schema).validate(model)

    def test_p4_capabilities_are_registered_in_the_shared_module_contract(self):
        product = self.read("product.json")
        contribution = self.read("products/p4/ui_contribution.json")
        self.assertTrue(all(code in " ".join(product["capabilities"]) for code in ("D01", "D02", "D03", "D04", "D05")))
        self.assertEqual(contribution["capabilities"], ["D01", "D02", "D03", "D04", "D05"])
        self.assertTrue((ROOT / "integration/proposals/CHANGE-001-suite-ui-contract.md").is_file())


if __name__ == "__main__":
    unittest.main()
