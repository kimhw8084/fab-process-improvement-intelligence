"""Source checks for P4's shared-workspace contribution."""
import json
import unittest
from pathlib import Path

from qualification.build_transfer_bundle import source_files


ROOT = Path(__file__).resolve().parents[1]


class SourceContractTests(unittest.TestCase):
    def test_schema_files_identify_version(self):
        for name in ("evidence.v1.schema.json", "product-manifest.v1.schema.json"):
            doc = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
            self.assertIn("1.0.0", doc["$id"])

    def test_manifest_declares_candidate_and_supported_capabilities(self):
        manifest = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_state"], "CANDIDATE")
        self.assertEqual(manifest["contract_version"], "1.0.0")
        capabilities = " ".join(manifest["capabilities"])
        self.assertTrue(all(code in capabilities for code in ("D01", "D02", "D03", "D04", "D05")))

    def test_p4_contributes_a_module_without_a_competing_shell(self):
        contribution = json.loads((ROOT / "products" / "p4" / "ui_contribution.json").read_text(encoding="utf-8"))
        self.assertEqual(contribution["status"], "HEADLESS_MODULE")
        self.assertEqual(contribution["ownership"]["suite_shell"], "single-suite-host")
        self.assertTrue((ROOT / contribution["module"]).is_file())
        self.assertFalse((ROOT / "ui" / "index.html").exists())

    def test_module_has_no_remote_asset_dependency_and_keeps_table_alternative(self):
        source = (ROOT / "products" / "p4" / "ui" / "P4Panel.tsx").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?:src|href)=[\"']https?://")
        self.assertNotIn("@import url(http", source)
        self.assertIn("<table>", source)
        self.assertIn("renderChart", source)
        self.assertIn("exact values and setting identifiers are listed in the table", source.lower())

    def test_retired_standalone_shell_is_not_in_the_transfer_bundle(self):
        packaged = {path.relative_to(ROOT).as_posix() for path in source_files()}
        self.assertFalse(any(name.startswith("qualification/evidence/legacy/") for name in packaged))
        self.assertTrue((ROOT / "qualification" / "evidence" / "legacy" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
