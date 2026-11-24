"""Metadata-only discovery must remain authorized, bounded, and non-authorizing."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fabintel.discovery import _operation_proposals, discover_capabilities, load_discovery_config
from fabintel.mcp_client import McpPermissionError


ROOT = Path(__file__).resolve().parent.parent


class DiscoveryProposalTests(unittest.TestCase):
    def test_only_exact_complete_schema_match_is_proposed_and_never_approved(self):
        output_types = {"tool_versions": "object", "semantic_versions": "array", "limits": "object",
                        "auth_scopes": "array", "audit_support": "boolean"}
        tools = [{"name": "fab.discover", "description": "misleading text is ignored",
                  "inputSchema": {"type": "object", "properties": {"permission_scope": {"type": "string"}}},
                  "outputSchema": {"type": "object", "properties": {key: {"type": value} for key, value in
                      output_types.items()}, "required": list(output_types)}}]
        report = _operation_proposals(tools)
        discover = report[0]
        self.assertEqual(discover["status"], "REVIEW_REQUIRED_EXACT_SCHEMA_PROPOSAL")
        self.assertEqual(discover["candidate_tool"], "fab.discover")
        self.assertIn("authorized semantic owner", discover["authority"])
        self.assertEqual(discover["mapping_proposal"]["input_map"], {"permission_scope": "permission_scope"})
        self.assertEqual(set(discover["mapping_proposal"]["result_map"]), set(output_types))
        self.assertEqual(report[1]["status"], "NO_EXACT_MATCH")

    def test_exact_name_does_not_overrule_incompatible_declared_types(self):
        tool = {"name": "fab.discover", "inputSchema": {"properties": {"permission_scope": {"type": "integer"}}},
                "outputSchema": {"properties": {"tool_versions": {"type": "object"},
                    "semantic_versions": {"type": "array"}, "limits": {"type": "object"},
                    "auth_scopes": {"type": "array"}, "audit_support": {"type": "boolean"}},
                    "required": ["tool_versions", "semantic_versions", "limits", "auth_scopes", "audit_support"]}}
        result = _operation_proposals([tool])[0]
        self.assertEqual(result["status"], "REFUSED_SCHEMA_OR_READ_ONLY_MISMATCH")

    def test_read_tool_requires_explicit_non_destructive_read_only_annotation(self):
        op = {"name": "fab.read_bounded", "inputSchema": {"properties": {
            "approved_plan": {}, "permission_context": {}, "limits": {}}},
            "outputSchema": {"properties": {"typed_rows": {}, "audit_id": {}, "source_versions": {}, "truncation": {}}},
            "annotations": {"readOnlyHint": False, "destructiveHint": False}}
        result = next(item for item in _operation_proposals([op]) if item["logical_operation"] == "read_bounded")
        self.assertEqual(result["status"], "REFUSED_SCHEMA_OR_READ_ONLY_MISMATCH")
        self.assertIsNone(result["candidate_tool"])

    def test_ambiguous_exact_tool_matches_are_refused(self):
        base = {"inputSchema": {"properties": {"permission_scope": {"type": "string"}}},
                "outputSchema": {"properties": {"tool_versions": {"type": "object"},
                    "semantic_versions": {"type": "array"}, "limits": {"type": "object"},
                    "auth_scopes": {"type": "array"}, "audit_support": {"type": "boolean"}},
                    "required": ["tool_versions", "semantic_versions", "limits", "auth_scopes", "audit_support"]}}
        tools = [{**base, "name": name} for name in ("a.discover", "b.discover")]
        result = _operation_proposals(tools)[0]
        self.assertEqual(result["status"], "REFUSED_AMBIGUOUS_MATCH")

    def test_missing_owner_approval_refuses_before_opening_transport(self):
        config = {"config_version": "1.0.0", "environment": "INTERNAL_APPROVED_ONLY",
                  "qualification_status": "PENDING_INTERNAL", "site_approval_reference": "SITE-REF",
                  "transport": {"type": "stdio", "command": ["must-not-launch"]}}
        with patch("fabintel.discovery.McpClient") as client:
            with self.assertRaises(McpPermissionError):
                discover_capabilities(config)
            client.assert_not_called()

    def test_discovery_config_rejects_extra_fields(self):
        import tempfile
        config = {"config_version": "1.0.0", "environment": "SYNTHETIC_TEST_ONLY",
                  "qualification_status": "PENDING_INTERNAL", "transport": {"type": "stdio", "command": [sys.executable]},
                  "operations": {"read_bounded": {"tool_name": "unapproved"}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "discovery.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "unsupported fields"):
                load_discovery_config(path)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the pinned offline MCP SDK candidate to run protocol discovery.")
class McpDiscoveryProtocolTests(unittest.TestCase):
    def test_synthetic_stdio_discovers_metadata_without_calling_tools(self):
        config = {"config_version": "1.0.0", "environment": "SYNTHETIC_TEST_ONLY",
                  "qualification_status": "PENDING_INTERNAL",
                  "transport": {"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                                "cwd": str(ROOT), "timeout_seconds": 3}}
        report = discover_capabilities(config, synthetic_test=True)
        self.assertEqual(report["status"], "CAPABILITIES_DISCOVERED_REVIEW_REQUIRED")
        self.assertEqual(report["protocol_operations"], ["initialize", "tools/list"])
        self.assertEqual(report["tool_count"], 6)
        self.assertEqual(report["manufacturing_tool_calls"], 0)
        self.assertTrue(all(item["status"] == "REFUSED_SCHEMA_OR_READ_ONLY_MISMATCH"
                            and item["candidate_tool"] is None for item in report["logical_operation_proposals"]))
        self.assertIn("do not establish manufacturing meaning", report["authority"])

    def test_cli_emits_a_partial_unapproved_draft_and_deterministic_diagnostics(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config_path = directory / "discovery.json"
            report_path = directory / "capabilities.json"
            draft_path = directory / "site-draft.json"
            config = {"config_version": "1.0.0", "environment": "SYNTHETIC_TEST_ONLY",
                      "qualification_status": "PENDING_INTERNAL",
                      "transport": {"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                                    "cwd": str(ROOT), "timeout_seconds": 3}}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "fabintel", "mcp-discover", "--config", str(config_path),
                                  "--synthetic-test", "--draft-config-output", str(draft_path),
                                  "--output", str(report_path)], cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(report["draft_config"]["status"], "PARTIAL_UNAPPROVED_DRAFT_WRITTEN")
            self.assertFalse(report["draft_config"]["workflow_ready"])
            self.assertEqual(draft["qualification_status"], "PENDING_INTERNAL")
            self.assertEqual(draft["operations"], {})
            self.assertEqual(draft["approved_source_ids"], [])


if __name__ == "__main__":
    unittest.main()
