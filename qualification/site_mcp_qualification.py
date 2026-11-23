"""Future site-side MCP qualification. Never executed by offline qualification."""
from __future__ import annotations

from datetime import datetime, timezone
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
    if not isinstance(entity_ids, list) or not entity_ids or any(value not in sources for value in entity_ids):
        raise ValueError("typed_entity_ids must be selected from the explicit source allowlist")
    if not isinstance(time_window, dict) or not isinstance(approved_plan, dict) or not isinstance(permission_context, dict):
        raise ValueError("a site-approved time window, approved read plan, and permission context are required")
    if not isinstance(limits, dict) or limits.get("read_only") is not True or not isinstance(limits.get("max_rows"), int) or not 1 <= limits["max_rows"] <= 1000:
        raise ValueError("site-approved bounded read must be read-only with max_rows between 1 and 1000")
    if any(source not in sources for source in approved_plan.get("source_ids", [])):
        raise ValueError("approved read plan references a source outside the explicit allowlist")

    adapter = configured_adapter(config, authorized_site_test=True)
    try:
        status = {}
        discovered = adapter.call("discover", {"permission_scope": permission_scope})
        status["discover"] = bool(discovered.get("tool_versions") and discovered.get("auth_scopes"))
        semantics = adapter.call("semantics", {"approved_source_ids": sources, "semantic_version": semantic_version})
        status["semantics"] = bool(semantics.get("approval") and semantics.get("column_definitions") and semantics.get("grain"))
        relationships = adapter.call("relationships", {"typed_entity_ids": entity_ids, "time_window": time_window})
        status["relationships"] = relationships.get("approved") is True and bool(relationships.get("keys"))
        read = adapter.call("read_bounded", {"approved_plan": approved_plan,
            "permission_context": permission_context, "limits": limits})
        typed_rows = read.get("typed_rows")
        status["read_bounded"] = (isinstance(typed_rows, list) and len(typed_rows) <= limits["max_rows"]
                                   and bool(read.get("audit_id")) and bool(read.get("source_versions"))
                                   and isinstance(read.get("truncation"), bool))
        operation_id = read.get("operation_id") or inputs.get("cancel_operation_id")
        if operation_id:
            cancel = adapter.call("cancel", {"operation_id": operation_id})
            status["cancel"] = cancel.get("confirmed_stopped") is True
        else:
            status["cancel"] = False
        audit_id = operation_id or read.get("audit_id")
        audit = adapter.call("audit", {"operation_id": audit_id})
        status["audit"] = bool(audit.get("permission_scope") and audit.get("sources") and audit.get("timestamps")
                                and isinstance(audit.get("query_hash"), str) and len(audit["query_hash"]) == 64)
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
                "source_ids_tested": sources,
                "remaining_signoffs": ["Fab Insight administrator confirms permission scopes and server-enforced read-only grants",
                    "semantic owner approves source versions, keys, units, grain and effectivity",
                    "security owner approves host, authentication, audit, cancel and recovery",
                    "engineer completes controlled pilot and records ROI baseline",
                    "legal/owner confirms transfer rights and licenses"],
                "warning": "A successful transport test is not company qualification or transfer approval."}
    finally:
        adapter.client.close()
