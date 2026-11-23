"""Future site-side MCP qualification. Never executed by offline qualification."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

from fabintel.mcp_client import configured_adapter


def qualify(config, *, site_approval_reference):
    if not isinstance(config, dict) or config.get("environment") != "INTERNAL_APPROVED_ONLY":
        raise ValueError("site qualification requires INTERNAL_APPROVED_ONLY configuration")
    if config.get("qualification_status") != "PENDING_INTERNAL":
        raise ValueError("this runner accepts only a PENDING_INTERNAL configuration")
    if not isinstance(site_approval_reference, str) or not site_approval_reference.strip():
        raise ValueError("authorized site approval reference is required")
    if config.get("site_approval_reference") != site_approval_reference:
        raise ValueError("CLI site approval reference must exactly match the local config")
    inputs = config.get("qualification_inputs")
    if not isinstance(inputs, dict):
        raise ValueError("site-owned qualification_inputs are required; this package supplies no company mappings")
    sources = config.get("approved_source_ids")
    versions = config.get("approved_semantic_versions")
    if not isinstance(sources, list) or not sources or not isinstance(versions, list) or not versions:
        raise ValueError("site-approved source IDs and semantic versions are required")
    semantic_version = inputs.get("semantic_version")
    if semantic_version not in versions:
        raise ValueError("qualification semantic_version must be in the approved site list")
    permission_scope = inputs.get("permission_scope")
    entity_ids = inputs.get("typed_entity_ids")
    time_window = inputs.get("time_window")
    approved_plan = inputs.get("approved_plan")
    permission_context = inputs.get("permission_context")
    limits = inputs.get("limits")
    if not isinstance(permission_scope, str) or not permission_scope:
        raise ValueError("site-approved permission_scope is required")
    if not isinstance(entity_ids, list) or len(entity_ids) != 2 or any(value not in sources for value in entity_ids):
        raise ValueError("P4 relationship qualification requires two typed entities selected from the explicit source allowlist")
    if not isinstance(time_window, dict) or not isinstance(approved_plan, dict) or not isinstance(permission_context, dict):
        raise ValueError("a site-approved time window, approved read plan, and permission context are required")
    if not isinstance(limits, dict) or limits.get("read_only") is not True or not isinstance(limits.get("max_rows"), int) or not 1 <= limits["max_rows"] <= 1000:
        raise ValueError("site-approved bounded read must be read-only with max_rows between 1 and 1000")
    if any(source not in sources for source in approved_plan.get("source_ids", [])):
        raise ValueError("approved read plan references a source outside the explicit allowlist")
    if (approved_plan.get("source_ids") != sources or approved_plan.get("time_window") != time_window
            or permission_context.get("scope") != permission_scope or permission_context.get("read_only") is not True):
        raise ValueError("site plan and permission context must exactly match the approved sources, time window, and read-only scope")

    adapter = configured_adapter(config, authorized_site_test=True)
    try:
        status = {}
        discovered = adapter.call("discover", {"permission_scope": permission_scope})
        tool_versions = discovered.get("tool_versions")
        mapped_names = [entry.get("tool_name") for entry in config.get("operations", {}).values()]
        status["discover"] = (isinstance(tool_versions, dict) and bool(discovered.get("auth_scopes"))
                              and permission_scope in discovered.get("auth_scopes", [])
                              and all(isinstance(name, str) and tool_versions.get(name) for name in mapped_names))
        semantics = adapter.call("semantics", {"approved_source_ids": sources, "semantic_version": semantic_version})
        semantic_source_versions = semantics.get("source_versions")
        status["semantics"] = (bool(semantics.get("approval") and semantics.get("column_definitions") and semantics.get("grain"))
                               and semantics.get("semantic_version") == semantic_version
                               and isinstance(semantic_source_versions, dict) and set(semantic_source_versions) == set(sources)
                               and all(isinstance(value, str) and value for value in semantic_source_versions.values()))
        relationships = adapter.call("relationships", {"typed_entity_ids": entity_ids, "time_window": time_window})
        relationship_contract = relationships.get("relationship_contract")
        upstream = relationship_contract.get("upstream") if isinstance(relationship_contract, dict) else None
        downstream = relationship_contract.get("downstream") if isinstance(relationship_contract, dict) else None
        status["relationships"] = (relationships.get("approved") is True and relationships.get("cardinality") == "one_to_one"
            and isinstance(relationships.get("keys"), dict) and isinstance(relationship_contract, dict)
            and relationship_contract.get("approved") is True
            and relationship_contract.get("contract_version")
            and isinstance(upstream, dict) and upstream.get("source_id") == entity_ids[0]
            and isinstance(downstream, dict) and downstream.get("source_id") == entity_ids[1]
            and isinstance(relationship_contract.get("relationship_id"), str)
            and isinstance(relationship_contract.get("approval_reference"), str))
        read = adapter.call("read_bounded", {"approved_plan": approved_plan,
            "permission_context": permission_context, "limits": limits})
        typed_rows = read.get("typed_rows")
        source_hashes = read.get("source_hashes")
        source_versions = read.get("source_versions")
        status["read_bounded"] = (isinstance(typed_rows, list) and len(typed_rows) <= limits["max_rows"]
            and bool(read.get("audit_id")) and read.get("truncation") is False
            and isinstance(source_versions, dict) and source_versions == semantic_source_versions
            and isinstance(source_hashes, dict) and set(source_hashes) == set(sources)
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in source_hashes.values()))
        operation_id = read.get("operation_id") or inputs.get("cancel_operation_id")
        if operation_id:
            cancel = adapter.call("cancel", {"operation_id": operation_id})
            status["cancel"] = cancel.get("confirmed_stopped") is True
        else:
            status["cancel"] = False
        audit_id = operation_id or read.get("audit_id")
        audit = adapter.call("audit", {"operation_id": audit_id})
        status["audit"] = (audit.get("permission_scope") == permission_scope
            and isinstance(audit.get("sources"), list) and set(audit["sources"]) == set(sources)
            and isinstance(audit.get("timestamps"), dict)
            and isinstance(audit.get("query_hash"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", audit["query_hash"]) is not None)
        endpoint = config.get("transport", {}).get("endpoint")
        return {"status": "SITE_TESTS_COMPLETED_PENDING_SIGNOFF" if all(status.values()) else "SITE_TESTS_FAILED_OR_INCOMPLETE",
                "qualification_status": "PENDING_INTERNAL", "networking_performed": True,
                "tested_at_utc": datetime.now(timezone.utc).isoformat(),
                "site_approval_reference": site_approval_reference,
                "endpoint_host": urlsplit(endpoint).hostname if endpoint else None,
                "protocol_version": adapter.client.negotiated_version,
                "discovered_tool_count": len(adapter.client.tools), "operation_checks": status,
                "bounded_rows_returned": len(typed_rows) if isinstance(typed_rows, list) else None,
                "read_truncated": read.get("truncation"),
                "source_versions_tested": read.get("source_versions"),
                "source_hashes_tested": read.get("source_hashes"),
                "relationship_id_tested": relationship_contract.get("relationship_id") if isinstance(relationship_contract, dict) else None,
                "source_ids_tested": sources,
                "remaining_signoffs": ["Fab Insight administrator confirms permission scopes and server-enforced read-only grants",
                    "semantic owner approves source versions, keys, units, grain and effectivity",
                    "security owner approves host, authentication, audit, cancel and recovery",
                    "engineer completes controlled pilot and records ROI baseline",
                    "legal/owner confirms transfer rights and licenses"],
                "warning": "A successful transport test is not company qualification or transfer approval."}
    finally:
        adapter.client.close()
