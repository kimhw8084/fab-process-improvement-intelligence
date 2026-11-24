"""Authorized, metadata-only MCP capability discovery and exact-schema proposals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fabintel.mcp_client import McpClient, McpError, McpPermissionError, _json_size, transport_from_config


ROOT = Path(__file__).resolve().parent.parent
DISCOVERY_CONFIG_VERSION = "1.0.0"
P4_REQUIRED_OUTPUTS = {
    "semantics": {"source_versions", "semantic_version"},
    "relationships": {"relationship_contract"},
    "read_bounded": {"operation_id", "source_versions", "source_hashes"},
    "audit": {"operation_id"},
}
INPUT_TYPES = {"permission_scope": "string", "approved_source_ids": "array", "semantic_version": "string",
               "typed_entity_ids": "array", "time_window": "object", "approved_plan": "object",
               "permission_context": "object", "limits": "object", "operation_id": "string"}
OUTPUT_TYPES = {"tool_versions": "object", "semantic_versions": "array", "limits": "object",
                "auth_scopes": "array", "audit_support": "boolean", "column_definitions": "array",
                "grain": "string", "units": "object", "effectivity": "object", "approval": "string",
                "source_versions": "object", "semantic_version": "string", "approved": "boolean",
                "keys": "object", "cardinality": "string", "source_reference": "string",
                "relationship_contract": "object", "typed_rows": "array", "audit_id": "string",
                "operation_id": "string", "truncation": "boolean", "source_hashes": "object",
                "confirmed_stopped": "boolean", "permission_scope": "string", "sources": "array",
                "timestamps": "object", "query_hash": "string"}


def load_discovery_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise McpError("MCP discovery config could not be read as JSON") from exc
    if not isinstance(config, dict) or config.get("config_version") != DISCOVERY_CONFIG_VERSION:
        raise McpError("MCP discovery config_version must be 1.0.0")
    allowed = {"config_version", "environment", "qualification_status", "site_approval_reference", "transport"}
    if set(config) - allowed or not {"config_version", "environment", "qualification_status", "transport"}.issubset(config):
        raise McpError("MCP discovery config contains unsupported fields or is missing required fields")
    if config.get("qualification_status") != "PENDING_INTERNAL":
        raise McpError("MCP discovery config must remain PENDING_INTERNAL")
    if "site_approval_reference" in config and not isinstance(config["site_approval_reference"], str):
        raise McpError("site_approval_reference must be a string")
    config["_config_dir"] = str(Path(path).resolve().parent)
    return config


def _operation_proposals(tools):
    contract = json.loads((ROOT / "contracts" / "adapter-operations.v1.json").read_text(encoding="utf-8"))
    proposals = []
    for operation in contract["logical_operations"]:
        name = operation["name"]
        exact_name = [tool for tool in tools if tool["name"].rsplit(".", 1)[-1] == name]
        compatible = []
        for tool in exact_name:
            input_schema = tool.get("inputSchema", {})
            output_schema = tool.get("outputSchema", {})
            inputs = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
            outputs = output_schema.get("properties", {}) if isinstance(output_schema, dict) else {}
            declared_outputs = set(output_schema.get("required", [])) if isinstance(output_schema, dict) else set()
            declared_inputs = set(input_schema.get("required", [])) if isinstance(input_schema, dict) else set()
            if not isinstance(inputs, dict) or not isinstance(outputs, dict):
                continue
            required_outputs = set(operation["returns"]) | P4_REQUIRED_OUTPUTS.get(name, set())
            if (not set(operation["requires"]).issubset(inputs)
                    or not declared_inputs.issubset(operation["requires"])
                    or not required_outputs.issubset(outputs) or not required_outputs.issubset(declared_outputs)):
                continue
            input_types_match = all(isinstance(inputs[field], dict)
                                    and inputs[field].get("type") == INPUT_TYPES[field]
                                    for field in operation["requires"] if field in INPUT_TYPES)
            output_types_match = all(isinstance(outputs[field], dict)
                                     and outputs[field].get("type") == OUTPUT_TYPES[field]
                                     for field in required_outputs if field in OUTPUT_TYPES)
            if not input_types_match or not output_types_match:
                continue
            if name == "read_bounded":
                annotations = tool.get("annotations", {})
                if (not isinstance(annotations, dict) or annotations.get("readOnlyHint") is not True
                        or annotations.get("destructiveHint") is True):
                    continue
            compatible.append(tool["name"])
        if len(compatible) == 1:
            status, tool_name = "REVIEW_REQUIRED_EXACT_SCHEMA_PROPOSAL", compatible[0]
            mapping_proposal = {"tool_name": tool_name,
                                "input_map": {field: field for field in operation["requires"]},
                                "fixed_arguments": {},
                                "result_map": {field: field for field in sorted(required_outputs)}}
        elif len(compatible) > 1:
            status, tool_name = "REFUSED_AMBIGUOUS_MATCH", None
            mapping_proposal = None
        elif exact_name:
            status, tool_name = "REFUSED_SCHEMA_OR_READ_ONLY_MISMATCH", None
            mapping_proposal = None
        else:
            status, tool_name = "NO_EXACT_MATCH", None
            mapping_proposal = None
        proposals.append({"logical_operation": name, "candidate_tool": tool_name,
                          "exact_name_candidates": [tool["name"] for tool in exact_name],
                          "status": status, "mapping_proposal": mapping_proposal,
                          "authority": "proposal only; an authorized semantic owner must approve the mapping"})
    return proposals


def discover_capabilities(config, *, site_approval_reference="", authorized_discovery=False,
                          synthetic_test=False):
    """Run only MCP initialize and tools/list after an explicit caller authorization."""
    if not isinstance(config, dict):
        raise McpError("MCP discovery config must be an object")
    if config.get("config_version") != DISCOVERY_CONFIG_VERSION:
        raise McpError("MCP discovery config_version must be 1.0.0")
    environment = config.get("environment")
    if environment == "SYNTHETIC_TEST_ONLY":
        if not synthetic_test:
            raise McpPermissionError("synthetic discovery requires explicit --synthetic-test")
    elif environment == "INTERNAL_APPROVED_ONLY":
        configured_reference = config.get("site_approval_reference")
        if (not authorized_discovery or not isinstance(configured_reference, str)
                or not configured_reference.strip() or site_approval_reference != configured_reference):
            raise McpPermissionError("internal discovery requires explicit authorization and an exact approval-reference match")
    else:
        raise McpPermissionError("discovery environment must be explicitly synthetic-test or internally approved")
    if config.get("qualification_status", "PENDING_INTERNAL") != "PENDING_INTERNAL":
        raise McpPermissionError("capability discovery requires a pending, non-authorizing draft")
    transport = transport_from_config(config)
    fingerprint_input = json.dumps(config.get("transport"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    client = McpClient(transport)
    try:
        tools = client.list_tools()
        _json_size(tools)
        catalog = []
        for tool in tools:
            item = {key: tool[key] for key in ("name", "title", "description", "annotations", "inputSchema", "outputSchema")
                    if key in tool}
            catalog.append(item)
        return {"status": "CAPABILITIES_DISCOVERED_REVIEW_REQUIRED",
                "environment": environment,
                "protocol_version": client.negotiated_version,
                "transport_fingerprint_sha256": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
                "authorization": "operator asserted for this metadata-only command; not independently authenticated",
                "protocol_operations": ["initialize", "tools/list"],
                "manufacturing_tool_calls": 0,
                "tool_count": len(catalog),
                "tool_catalog": catalog,
                "logical_operation_proposals": _operation_proposals(catalog),
                "authority": "Discovered names, descriptions, annotations, and schemas are untrusted metadata. Proposals do not establish manufacturing meaning, permissions, source approval, or semantic correctness."}
    finally:
        client.close()
