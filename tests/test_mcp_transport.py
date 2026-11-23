"""Protocol-level external transport and mapping checks against the bundled mock server."""
import copy
import importlib.util
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path

from fabintel.mcp_client import (McpError, McpPermissionError, configured_adapter,
                                 transport_from_config)
from fabintel.mock_mcp_server import Handler
from products.p4.mcp_workflow import run_mcp_investigation
from qualification.site_mcp_qualification import qualify as qualify_site_mcp


ROOT = Path(__file__).resolve().parent.parent


def mapping_config(transport):
    outputs = {
        "discover": ["tool_versions", "semantic_versions", "limits", "auth_scopes", "audit_support"],
        "semantics": ["column_definitions", "grain", "units", "effectivity", "approval", "source_versions", "semantic_version"],
        "relationships": ["approved", "keys", "cardinality", "grain", "effectivity", "source_reference", "relationship_contract"],
        "read_bounded": ["typed_rows", "audit_id", "source_versions", "truncation", "source_hashes"],
        "cancel": ["confirmed_stopped"],
        "audit": ["permission_scope", "sources", "timestamps", "query_hash"],
    }
    names = {operation: f"synthetic.test.{operation}" for operation in outputs}
    return {"config_version": "1.0.0", "environment": "SYNTHETIC_TEST_ONLY", "qualification_status": "PENDING_INTERNAL",
        "approved_source_ids": ["SYN-SOURCE-A", "SYN-SOURCE-B"],
        "approved_semantic_versions": ["SYNTHETIC-SEMANTICS-1"], "transport": transport,
        "operations": {operation: {"tool_name": names[operation],
            "input_map": {key: ("approved_source_ids" if operation == "semantics" and key == "source_ids" else key)
                          for key in ({"discover": ["permission_scope"],
                "semantics": ["source_ids", "semantic_version"],
                "relationships": ["typed_entity_ids", "time_window"],
                "read_bounded": ["approved_plan", "permission_context", "limits"],
                "cancel": ["operation_id"], "audit": ["operation_id"]}[operation])},
            "result_map": {key: key for key in outputs[operation]}}
            for operation in outputs}}


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the pinned offline MCP SDK candidate to run protocol integration cases.")
class McpStdioQualification(unittest.TestCase):
    def setUp(self):
        config = mapping_config({"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                                 "cwd": str(ROOT), "timeout_seconds": 3})
        self.adapter = configured_adapter(config, allow_synthetic_test=True)

    def tearDown(self):
        self.adapter.client.close()

    def test_initialize_pagination_and_all_contract_mappings(self):
        self.assertEqual(len(self.adapter.client.tools), 6)
        self.assertEqual(self.adapter.contract["contract_version"], "1.0.0")
        found = self.adapter.call("discover", {"permission_scope": "SYNTHETIC_READ"})
        self.assertTrue(found["audit_support"])
        self.assertEqual(found["semantic_versions"], ["SYNTHETIC-SEMANTICS-1"])
        semantics = self.adapter.call("semantics", {"approved_source_ids": ["SYN-SOURCE-A"],
                                                      "semantic_version": "SYNTHETIC-SEMANTICS-1"})
        self.assertEqual(semantics["grain"], "one row per synthetic process observation")
        self.assertEqual(semantics["source_versions"]["SYN-SOURCE-A"], "SYN-SOURCE-V1")
        relation = self.adapter.call("relationships", {"typed_entity_ids": ["SYN-SOURCE-A", "SYN-SOURCE-B"],
                                                        "time_window": {"start": "SYNTHETIC"}})
        self.assertEqual(relation["cardinality"], "one_to_one")
        read = self.adapter.call("read_bounded", {"approved_plan": {"source_ids": ["SYN-SOURCE-A"],
            "synthetic_rows": [{"unit_id": "SYNTHETIC-1"}, {"unit_id": "SYNTHETIC-2"}]},
            "permission_context": {"scope": "SYNTHETIC_READ"}, "limits": {"max_rows": 1, "read_only": True}})
        self.assertEqual(read["typed_rows"], [{"unit_id": "SYNTHETIC-1"}])
        self.assertTrue(read["truncation"])
        self.assertEqual(set(read["source_hashes"]), {"SYN-SOURCE-A"})
        self.assertTrue(self.adapter.call("cancel", {"operation_id": "SYN-OP-STOPPED"})["confirmed_stopped"])
        self.assertEqual(len(self.adapter.call("audit", {"operation_id": "SYN-OP-1"})["query_hash"]), 64)

    def test_unapproved_semantics_source_and_oversized_or_write_read_are_blocked(self):
        with self.assertRaises(McpPermissionError):
            self.adapter.call("semantics", {"approved_source_ids": ["COMPANY-TOOL-GUESS"],
                                              "semantic_version": "SYNTHETIC-SEMANTICS-1"})
        payload = {"approved_plan": {}, "permission_context": {},
                   "limits": {"max_rows": 1001, "read_only": True}}
        with self.assertRaises(McpPermissionError):
            self.adapter.call("read_bounded", payload)
        payload["limits"] = {"max_rows": 10, "read_only": False}
        with self.assertRaises(McpPermissionError):
            self.adapter.call("read_bounded", payload)

    def test_missing_discovered_mapping_and_missing_result_mapping_fail_closed(self):
        broken = mapping_config({"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"], "cwd": str(ROOT)})
        broken["operations"]["discover"]["tool_name"] = "synthetic.unknown.tool"
        adapter = configured_adapter(broken, allow_synthetic_test=True)
        try:
            with self.assertRaises(McpError):
                adapter.call("discover", {"permission_scope": "SYNTHETIC_READ"})
        finally:
            adapter.client.close()

    def test_company_pending_config_is_rejected_before_any_transport_is_started(self):
        config = mapping_config({"type": "stdio", "command": ["definitely-not-a-real-program"]})
        config["environment"] = "INTERNAL_APPROVED_ONLY"
        config["qualification_status"] = "PENDING_INTERNAL"
        with self.assertRaises(McpPermissionError):
            configured_adapter(config)

    def test_sdk_stdio_configuration_forwards_only_explicit_environment_mappings(self):
        config = mapping_config({"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                                 "env_from": {"SITE_TOKEN": "P4_SITE_TEST_SECRET"}})
        with patch.dict(os.environ, {"P4_SITE_TEST_SECRET": "synthetic-token-value",
                                     "P4_UNRELATED_SECRET": "must-not-be-forwarded"}):
            sdk_transport = transport_from_config(config)
        self.assertEqual(sdk_transport["env"], {"SITE_TOKEN": "synthetic-token-value"})
        self.assertNotIn("P4_SITE_TEST_SECRET", sdk_transport["env"])
        self.assertNotIn("P4_UNRELATED_SECRET", sdk_transport["env"])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(McpPermissionError, "environment source is unset"):
                transport_from_config(mapping_config({"type": "stdio", "command": [sys.executable],
                                                     "env_from": {"SITE_TOKEN": "NOT_SET"}}))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the pinned offline MCP SDK candidate to run protocol integration cases.")
class McpHttpQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)

    def test_streamable_http_sse_handshake_and_mapping(self):
        port = self.server.server_address[1]
        config = mapping_config({"type": "streamable_http", "endpoint": f"http://127.0.0.1:{port}/mcp",
                                 "allowed_hosts": ["127.0.0.1"], "timeout_seconds": 3})
        adapter = configured_adapter(config, allow_synthetic_test=True)
        try:
            result = adapter.call("discover", {"permission_scope": "SYNTHETIC_READ"})
            self.assertTrue(result["audit_support"])
            self.assertEqual(adapter.client.negotiated_version, "2025-11-25")
        finally:
            adapter.client.close()

    def test_endpoint_allowlist_and_cleartext_network_policy(self):
        with self.assertRaises(McpPermissionError):
            transport_from_config(mapping_config({"type": "streamable_http", "endpoint": "http://127.0.0.1:9999/mcp",
                                                   "allowed_hosts": ["example.com"]}))
        with self.assertRaises(McpPermissionError):
            transport_from_config(mapping_config({"type": "streamable_http", "endpoint": "http://example.com/mcp",
                                                   "allowed_hosts": ["example.com"]}))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the pinned offline MCP SDK candidate to run protocol integration cases.")
class McpToP4WorkflowQualification(unittest.TestCase):
    @staticmethod
    def request():
        template = json.loads((ROOT/"fixtures"/"full_workflow_demo.json").read_text(encoding="utf-8"))
        source_observations = template.pop("observations")
        template.pop("sources", None)
        template.pop("linkage", None)
        template["grain"] = "one row per synthetic process observation"
        template["sampling_unit"] = "synthetic independent lot"
        template["timestamp_semantics"] = "UTC-offset ISO-8601 event timestamp"
        for factor in template["factors"]:
            factor["unit"] = "SYNTHETIC-PRESSURE" if factor["name"] == "pressure" else "SYNTHETIC-TEMPERATURE"
        for metric in template["metrics"]:
            metric["unit"] = "SYNTHETIC-INDEX" if metric["name"] == "yield_index" else "SYNTHETIC-RATE"
        time_window = {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"}
        rows = []
        for item in source_observations:
            row_id = item["id"]
            rows.append({"row_id": row_id, "unit_id": row_id, "upstream_unit_id": row_id,
                "downstream_unit_id": row_id, "event_ts": item["event_ts"],
                "upstream_event_ts": item["event_ts"], "downstream_event_ts": item["event_ts"],
                "population_id": "SYNTHETIC-POPULATION-1",
                "pressure": item["factors"]["pressure"], "temperature": item["factors"]["temperature"],
                "response_primary": item["metrics"]["yield_index"],
                "response_secondary": item["metrics"]["defect_rate"], "synthetic_value": 0.0,
                "lot_id": item["lot_id"], "wafer_id": item["wafer_id"], "chamber": item["chamber"],
                "analysis_partition": item["analysis_partition"]})
        source_ids = ["SYN-SOURCE-A", "SYN-SOURCE-B"]
        return {"approved_source_ids": source_ids, "semantic_version": "SYNTHETIC-SEMANTICS-1",
            "permission_scope": "SYNTHETIC_READ", "time_window": time_window,
            "approved_plan": {"source_ids": source_ids, "time_window": time_window, "synthetic_rows": rows},
            "permission_context": {"scope": "SYNTHETIC_READ", "read_only": True},
            "max_rows": len(rows),
            "normalization": {"row_id_field": "row_id", "unit_field": "unit_id", "timestamp_field": "event_ts",
                "factor_fields": {"pressure": "pressure", "temperature": "temperature"},
                "metric_fields": {"yield_index": "response_primary", "defect_rate": "response_secondary"},
                "passthrough_fields": ["lot_id", "wafer_id", "chamber", "analysis_partition"]},
            "analysis_template": template}

    @staticmethod
    def _adapter(scenario="normal"):
        config = mapping_config({"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server",
            "--scenario", scenario], "cwd": str(ROOT), "timeout_seconds": 5})
        return configured_adapter(config, allow_synthetic_test=True)

    def test_real_sdk_read_relationship_normalization_and_d01_d05_evidence_flow(self):
        adapter = self._adapter()
        try:
            result = run_mcp_investigation(adapter, self.request())
        finally:
            adapter.client.close()
        self.assertIn(result["status"], ("VALID", "PARTIAL"))
        self.assertEqual(result["product_id"], "p4")
        acquisition = result["provenance"]["mcp_acquisition"]
        self.assertEqual(acquisition["status"], "ANALYSIS_COMPLETED")
        self.assertEqual(acquisition["logical_contract_version"], "1.0.0")
        self.assertEqual(acquisition["row_count"], 900)
        self.assertFalse(acquisition["truncation"])
        self.assertTrue(acquisition["read_only"])
        self.assertEqual(set(acquisition["source_hashes"]), {"SYN-SOURCE-A", "SYN-SOURCE-B"})
        dossier = result["artifacts"][0]
        self.assertEqual(dossier["D01_sensitivity"]["status"], "VALID")
        self.assertIn(dossier["D02_supported_region"]["status"], ("VALID", "INCONCLUSIVE"))
        self.assertIn(dossier["D03_tradeoffs"]["status"], ("VALID", "LIMITED_SCOPE"))
        self.assertEqual(dossier["D04_experiment_proposal"]["status"], "PROPOSED")
        self.assertEqual(dossier["D05_effectiveness"]["status"], "ESTIMATED")
        self.assertEqual({source["id"] for source in result["sources"]},
                         {"SYN-SOURCE-A", "SYN-SOURCE-B"})

    def test_semantic_and_source_version_drift_refuse_after_auditing_the_read(self):
        for scenario, expected in (("semantic_schema_drift", "semantic schema drift"),
                                   ("source_version_drift", "source versions")):
            with self.subTest(scenario=scenario):
                adapter = self._adapter(scenario)
                try:
                    result = run_mcp_investigation(adapter, self.request())
                finally:
                    adapter.client.close()
                self.assertEqual(result["status"], "REFUSED")
                self.assertIn(expected, " ".join(result["limitations"]))
                self.assertEqual(result["provenance"]["mcp_acquisition"]["status"], "AUDITED_READ_COMPLETED")
                self.assertEqual(result["provenance"]["mcp_acquisition"]["audit_id"], "SYN-AUDIT-READ-1")

    def test_p4_evidence_extensions_fail_closed_without_mutating_logical_contract_v1(self):
        for scenario, expected in (("missing_semantic_evidence", "semantic_version"),
                                   ("missing_semantic_source_versions", "source_versions"),
                                   ("missing_relationship_evidence", "relationship_contract"),
                                   ("missing_read_hashes", "source_hashes")):
            with self.subTest(scenario=scenario):
                adapter = self._adapter(scenario)
                try:
                    result = run_mcp_investigation(adapter, self.request())
                finally:
                    adapter.client.close()
                self.assertEqual(result["status"], "REFUSED")
                self.assertIn(expected, " ".join(result["limitations"]))
                self.assertEqual(result["provenance"]["mcp_acquisition"]["status"], "NOT_STARTED")

    def test_permission_relationship_time_grain_limit_and_audit_failures_are_refused(self):
        invalid_cases = (("permission_denied", None, "does not qualify"),
                         ("relationship_unapproved", None, "not approved"),
                         ("relationship_many_to_many", None, "not approved"),
                         ("server_truncated", None, "truncated or oversized"),
                         ("audit_invalid", None, "audit query hash"))
        for scenario, mutation, expected in invalid_cases:
            with self.subTest(scenario=scenario):
                adapter = self._adapter(scenario)
                try:
                    result = run_mcp_investigation(adapter, self.request())
                finally:
                    adapter.client.close()
                self.assertEqual(result["status"], "REFUSED")
                self.assertIn(expected, " ".join(result["limitations"]))
        for mutation, expected in (("outside_window", "outside the exact requested time window"),
                                   ("join_mismatch", "relationship key equality"),
                                   ("duplicate_unit", "one-to-one relationship grain")):
            request = self.request()
            if mutation == "outside_window":
                request["approved_plan"]["synthetic_rows"][0]["event_ts"] = "2025-12-31T23:59:00Z"
            elif mutation == "join_mismatch":
                request["approved_plan"]["synthetic_rows"][0]["downstream_unit_id"] = "SYN-OTHER-ROW"
            else:
                request["approved_plan"]["synthetic_rows"][1]["unit_id"] = request["approved_plan"]["synthetic_rows"][0]["unit_id"]
                request["approved_plan"]["synthetic_rows"][1]["upstream_unit_id"] = request["approved_plan"]["synthetic_rows"][0]["upstream_unit_id"]
                request["approved_plan"]["synthetic_rows"][1]["downstream_unit_id"] = request["approved_plan"]["synthetic_rows"][0]["downstream_unit_id"]
            adapter = self._adapter()
            try:
                result = run_mcp_investigation(adapter, request)
            finally:
                adapter.client.close()
            self.assertEqual(result["status"], "REFUSED")
            self.assertIn(expected, " ".join(result["limitations"]))

    def test_bounded_read_request_and_cancellation_stop_before_analysis(self):
        request = self.request()
        request["max_rows"] = 1001
        adapter = self._adapter()
        try:
            oversized = run_mcp_investigation(adapter, request)
        finally:
            adapter.client.close()
        self.assertEqual(oversized["status"], "REFUSED")
        self.assertIn("bounded acquisition", " ".join(oversized["limitations"]))

        adapter = self._adapter()
        try:
            cancelled = run_mcp_investigation(adapter, self.request(), cancel=lambda: True)
        finally:
            adapter.client.close()
        self.assertEqual(cancelled["status"], "REFUSED")
        self.assertEqual(cancelled["provenance"]["mcp_acquisition"]["status"], "NOT_STARTED")

    def test_cancel_after_read_audits_receipt_and_withholds_analysis(self):
        adapter = self._adapter()
        cancelled = {"value": False}
        original_call = adapter.call
        def tracked_call(operation, payload):
            result = original_call(operation, payload)
            if operation == "read_bounded":
                cancelled["value"] = True
            return result
        adapter.call = tracked_call
        try:
            result = run_mcp_investigation(adapter, self.request(), cancel=lambda: cancelled["value"])
        finally:
            adapter.client.close()
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("cancelled after read", " ".join(result["limitations"]))
        self.assertEqual(result["provenance"]["mcp_acquisition"]["status"], "CANCELLED_AFTER_AUDITED_READ")
        self.assertEqual(result["provenance"]["mcp_acquisition"]["audit_id"], "SYN-AUDIT-READ-1")

    def test_internal_configuration_mock_qualification_stays_pending_signoff(self):
        sources = ["SYN-SOURCE-A", "SYN-SOURCE-B"]
        time_window = {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"}
        config = mapping_config({"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                                 "cwd": str(ROOT), "timeout_seconds": 5})
        config["environment"] = "INTERNAL_APPROVED_ONLY"
        config["qualification_status"] = "PENDING_INTERNAL"
        config["site_approval_reference"] = "SYNTHETIC-TEST-APPROVAL-ONLY"
        config["qualification_inputs"] = {"semantic_version": "SYNTHETIC-SEMANTICS-1",
            "permission_scope": "SYNTHETIC_READ", "typed_entity_ids": sources,
            "time_window": time_window, "approved_plan": {"source_ids": sources, "time_window": time_window,
                "synthetic_rows": []}, "permission_context": {"scope": "SYNTHETIC_READ", "read_only": True},
            "limits": {"max_rows": 1, "read_only": True}, "cancel_operation_id": "SYN-OP-STOPPED"}
        result = qualify_site_mcp(config, site_approval_reference="SYNTHETIC-TEST-APPROVAL-ONLY")
        self.assertEqual(result["status"], "SITE_TESTS_COMPLETED_PENDING_SIGNOFF")
        self.assertEqual(result["qualification_status"], "PENDING_INTERNAL")
        self.assertTrue(all(result["operation_checks"].values()))
        self.assertEqual(result["source_ids_tested"], sources)
        self.assertEqual(set(result["source_hashes_tested"]), set(sources))
        self.assertIn("not company qualification", result["warning"])


if __name__ == "__main__":
    unittest.main()
