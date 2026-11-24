"""Offline, non-authorizing checks for P4 site-owned MCP configuration."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fabintel.site_config import validate_site_config


ROOT = Path(__file__).resolve().parents[1]


def valid_config():
    config = json.loads((ROOT / "requirements" / "synthetic-mcp-mapping.v1.json").read_text())
    window = {"start": "2026-01-01T00:00:00Z", "end": "2026-01-31T23:59:59Z"}
    config["p4_profile"] = {
        "semantic_version": "SYNTHETIC-SEMANTICS-1", "permission_scope": "SYNTHETIC_READ",
        "time_window": window, "approved_plan": {"source_ids": config["approved_source_ids"], "time_window": window},
        "permission_context": {"scope": "SYNTHETIC_READ", "read_only": True}, "max_rows": 500,
        "normalization": {"row_id_field": "row_id", "unit_field": "unit_id", "timestamp_field": "event_ts",
            "factor_fields": {"pressure": "pressure"}, "metric_fields": {"quality": "quality"}},
        "analysis_template": {"objective": "Improve synthetic quality", "context": {"step": "test"},
            "grain": "synthetic-wafer-row", "sampling_unit": "lot", "timestamp_semantics": "UTC event time",
            "constraints_approved": True, "factors": [{"name": "pressure", "unit": "Pa", "bounds": [1, 2], "approved": True}],
            "metrics": [{"name": "quality", "unit": "%", "direction": "maximize"}]}}
    return config


class SiteConfigTests(unittest.TestCase):
    def test_complete_draft_is_structurally_valid_but_never_authenticated(self):
        report = validate_site_config(valid_config())
        self.assertEqual(report["status"], "STRUCTURALLY_VALID_REVIEW_REQUIRED")
        self.assertTrue(report["p4_workflow_ready"])
        self.assertEqual(report["network_requests"], 0)
        self.assertFalse(report["company_authorization_authenticated"])
        self.assertTrue(report["still_requires"])

    def test_static_validation_does_not_require_or_read_secret_environment_values(self):
        config = valid_config()
        config["transport"]["env_from"] = {"MCP_BEARER": "P4_SITE_TEST_SECRET_MUST_NOT_BE_READ"}
        with patch.dict(os.environ, {}, clear=True):
            report = validate_site_config(config)
        self.assertTrue(report["p4_workflow_ready"], report["errors"])
        self.assertEqual(report["network_requests"], 0)

    def test_missing_p4_result_provenance_and_invalid_time_window_require_repair(self):
        config = valid_config()
        del config["operations"]["read_bounded"]["result_map"]["source_hashes"]
        config["p4_profile"]["time_window"]["start"] = "2026-02-01T00:00:00Z"
        report = validate_site_config(config)
        self.assertEqual(report["status"], "CONFIGURATION_REPAIR_REQUIRED")
        self.assertFalse(report["p4_workflow_ready"])
        self.assertTrue(any("source_hashes" in error for error in report["errors"]))
        self.assertTrue(any("time_window" in error for error in report["errors"]))

    def test_plaintext_secret_is_rejected_without_echoing_its_value(self):
        config = valid_config()
        config["transport"]["password"] = "synthetic-never-print-this"
        report = validate_site_config(config)
        self.assertFalse(report["p4_workflow_ready"])
        self.assertTrue(any("plaintext secret-like" in error for error in report["errors"]))
        self.assertNotIn("synthetic-never-print-this", json.dumps(report))

    def test_authorization_reference_is_not_mistaken_for_a_plaintext_credential(self):
        config = valid_config()
        config["p4_profile"]["analysis_template"]["effectiveness"] = {
            "authorization_id": "SYNTHETIC-REVIEW-REFERENCE"}
        report = validate_site_config(config)
        self.assertTrue(report["p4_workflow_ready"], report["errors"])

    def test_malformed_nested_mapping_returns_repair_diagnostics(self):
        config = valid_config()
        config["operations"]["discover"]["input_map"]["permission_scope"] = ["permission_scope"]
        report = validate_site_config(config)
        self.assertEqual(report["status"], "CONFIGURATION_REPAIR_REQUIRED")
        self.assertTrue(any("input_map" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
