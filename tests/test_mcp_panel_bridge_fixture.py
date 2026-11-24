"""Verify the exact official-SDK synthetic MCP result remains UI/schema ready."""
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "mcp_p4_panel_bridge.json"


class McpPanelBridgeFixtureTests(unittest.TestCase):
    def test_mcp_success_envelope_has_all_five_capabilities_and_exact_source_provenance(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        evidence = fixture["analysis_evidence"]
        self.assertEqual(fixture["source"], "official-mcp-sdk-synthetic-mock")
        self.assertEqual(fixture["source_preview"]["status"], "SYNTHETIC_ONLY")
        self.assertIn("no company source permission", fixture["source_preview"]["permission"])
        self.assertEqual(evidence["status"], "PARTIAL")
        acquisition = evidence["provenance"]["mcp_acquisition"]
        self.assertEqual(acquisition["status"], "ANALYSIS_COMPLETED")
        self.assertEqual(acquisition["normalized_rows"], 900)
        self.assertEqual(acquisition["row_count"], 900)
        self.assertFalse(acquisition["truncation"])
        self.assertTrue(acquisition["read_only"])
        self.assertEqual({source["id"] for source in evidence["sources"]},
                         {"SYN-SOURCE-A", "SYN-SOURCE-B"})
        dossier = next(artifact for artifact in evidence["artifacts"]
                       if artifact.get("type") == "p4_decision_dossier")
        self.assertTrue(all(key in dossier for key in (
            "D01_sensitivity", "D02_supported_region", "D03_tradeoffs",
            "D04_experiment_proposal", "D05_effectiveness")))

        window = dossier["D02_supported_region"]
        self.assertEqual(window["candidate_count"], 76)
        self.assertEqual(window["candidate_scope"], "MODEL_BASED_ADVISORY_SCREENING_ONLY")
        self.assertIn("does not validate model form", window["candidate_count_semantics"])
        self.assertGreater(window["screened_candidate_counts_by_region"]["interpolated"], 0)
        interpolated = next(cell for cell in window["grid"] if cell.get("screened_candidate"))
        self.assertEqual(interpolated["candidate_review_status"],
                         "MODEL_INTERPOLATION_ADVISORY_REQUIRES_EXACT_CONFIRMATION")
        self.assertEqual(interpolated["required_engineer_action"],
                         "PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS")
        self.assertEqual(interpolated["independent_evaluation"]["status"],
                         "NO_EXACT_SETTING_EVALUATION_DATA")

        proposal = dossier["D04_experiment_proposal"]
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertFalse(proposal["executed"])
        self.assertEqual(proposal["actuation"], "none")
        self.assertTrue(proposal["objective_statement"])
        self.assertTrue(proposal["factor_definitions"])
        self.assertIn(proposal["information_value"]["status"], ("APPROXIMATE", "NOT_ESTIMATED"))
        self.assertEqual(proposal["pre_execution_uncertainty"]["status"],
                         "NOT_ESTIMATED_FOR_NEW_RUNS")
        self.assertTrue(proposal["required_engineer_review"])
        self.assertTrue(proposal["evidence_required_before_next_iteration"])

    def test_mcp_permission_refusal_is_empty_and_bridge_sources_match_fingerprints(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        evidence = fixture["refusal_evidence"]
        self.assertEqual(evidence["status"], "REFUSED")
        self.assertEqual(evidence["claims"], [])
        self.assertEqual(evidence["sources"], [])
        self.assertEqual(evidence.get("artifacts", []), [])
        self.assertEqual(evidence["provenance"]["mcp_acquisition"]["status"], "NOT_STARTED")
        self.assertEqual(fixture["source_preview"]["status"], "SYNTHETIC_ONLY")
        for relative, expected in fixture["source_fingerprint"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)


if __name__ == "__main__":
    unittest.main()
