"""Protocol-level external transport and mapping checks against the bundled mock server."""
import copy
import importlib.util
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


ROOT = Path(__file__).resolve().parent.parent


def mapping_config(transport):
    outputs = {
        "discover": ["tool_versions", "semantic_versions", "limits", "auth_scopes", "audit_support"],
        "semantics": ["column_definitions", "grain", "units", "effectivity", "approval"],
        "relationships": ["approved", "keys", "cardinality", "grain", "effectivity", "source_reference"],
        "read_bounded": ["typed_rows", "audit_id", "source_versions", "truncation"],
        "cancel": ["confirmed_stopped"],
        "audit": ["permission_scope", "sources", "timestamps", "query_hash"],
    }
    names = {operation: f"synthetic.test.{operation}" for operation in outputs}
    return {"config_version": "1.0.0", "environment": "SYNTHETIC_TEST_ONLY", "qualification_status": "PENDING_INTERNAL",
        "approved_source_ids": ["SYNTHETIC-SOURCE-A", "SYNTHETIC-SOURCE-B"],
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
        found = self.adapter.call("discover", {"permission_scope": "SYNTHETIC_READ"})
        self.assertTrue(found["audit_support"])
        self.assertEqual(found["semantic_versions"], ["SYNTHETIC-SEMANTICS-1"])
        semantics = self.adapter.call("semantics", {"approved_source_ids": ["SYNTHETIC-SOURCE-A"],
                                                      "semantic_version": "SYNTHETIC-SEMANTICS-1"})
        self.assertEqual(semantics["grain"], "one synthetic unit row")
        relation = self.adapter.call("relationships", {"typed_entity_ids": ["SYNTHETIC-SOURCE-A", "SYNTHETIC-SOURCE-B"],
                                                        "time_window": {"start": "SYNTHETIC"}})
        self.assertEqual(relation["cardinality"], "one_to_one")
        read = self.adapter.call("read_bounded", {"approved_plan": {"source_ids": ["SYNTHETIC-SOURCE-A"],
            "synthetic_rows": [{"unit_id": "SYNTHETIC-1"}, {"unit_id": "SYNTHETIC-2"}]},
            "permission_context": {"scope": "SYNTHETIC_READ"}, "limits": {"max_rows": 1, "read_only": True}})
        self.assertEqual(read["typed_rows"], [{"unit_id": "SYNTHETIC-1"}])
        self.assertTrue(read["truncation"])
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


if __name__ == "__main__":
    unittest.main()
