"""Deterministic, non-authorizing MCP onboarding review helpers."""
from __future__ import annotations

from math import isfinite

from fabintel.mcp_client import McpError, McpPermissionError
from products.p4.mcp_workflow import _validate_relationship


def _column_catalog(semantics):
    columns = semantics.get("column_definitions")
    units = semantics.get("units", {})
    if not isinstance(columns, list) or not columns:
        raise McpError("semantic response must include a nonempty typed column catalog")
    out = {}
    for column in columns:
        if (not isinstance(column, dict) or not isinstance(column.get("name"), str)
                or not column["name"] or column["name"] in out
                or not isinstance(column.get("type"), str)):
            raise McpError("semantic column catalog is invalid or contains duplicate names")
        unit = units.get(column["name"]) if isinstance(units, dict) else None
        out[column["name"]] = {**column, "unit": unit or column.get("unit")}
    return out


def _target_specs(profile):
    template = profile.get("analysis_template") if isinstance(profile, dict) else None
    normalization = profile.get("normalization") if isinstance(profile, dict) else None
    failures = []
    if not isinstance(template, dict) or not isinstance(normalization, dict):
        return template, normalization, [], failures + ["explicit P4 analysis_template and normalization are required"]
    if (not isinstance(template.get("objective"), str) or not template["objective"].strip()
            or not isinstance(template.get("context"), dict) or not template["context"]
            or any(not isinstance(template.get(key), str) or not template[key].strip()
                   for key in ("grain", "sampling_unit", "timestamp_semantics"))):
        failures.append("objective, process context, row grain, sampling unit, and timestamp semantics are required")
    if template.get("constraints_approved") is not True:
        failures.append("engineer-approved bounds and metric constraints must be explicit")
    factors, metrics = template.get("factors"), template.get("metrics")
    if not isinstance(factors, list) or not factors or not isinstance(metrics, list) or not metrics:
        failures.append("at least one explicit factor and metric are required")
        factors, metrics = [], []
    targets = []
    factor_names, metric_names = set(), set()
    for factor in factors:
        if not isinstance(factor, dict) or not isinstance(factor.get("name"), str):
            failures.append("factor definition is malformed")
            continue
        name = factor["name"]
        bounds = factor.get("bounds")
        if (not name or name in factor_names or factor.get("approved") is not True
                or not isinstance(factor.get("unit"), str) or not factor["unit"]
                or not isinstance(bounds, list) or len(bounds) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in (bounds or []))
                or (isinstance(bounds, list) and len(bounds) == 2 and bounds[0] >= bounds[1])):
            failures.append(f"factor {name or '(unnamed)'} needs a unique name, unit, approved bounds, and explicit approval")
        factor_names.add(name)
        targets.append(("factor", name, factor.get("unit")))
    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
            failures.append("metric definition is malformed")
            continue
        name = metric["name"]
        if (not name or name in metric_names or metric.get("direction") not in ("maximize", "minimize")
                or not isinstance(metric.get("unit"), str) or not metric["unit"]):
            failures.append(f"metric {name or '(unnamed)'} needs a unique name, direction, and unit")
        metric_names.add(name)
        targets.append(("metric", name, metric.get("unit")))
    factor_map, metric_map = normalization.get("factor_fields"), normalization.get("metric_fields")
    if not isinstance(factor_map, dict) or set(factor_map) - factor_names:
        failures.append("factor field map must be an object containing only declared P4 factors")
    if not isinstance(metric_map, dict) or set(metric_map) - metric_names:
        failures.append("metric field map must be an object containing only declared P4 metrics")
    return template, normalization, targets, failures


def _role_proposals(profile, columns):
    template, normalization, targets, failures = _target_specs(profile)
    if not isinstance(normalization, dict):
        return [], failures
    maps = {"factor": normalization.get("factor_fields", {}),
            "metric": normalization.get("metric_fields", {})}
    proposals, used_fields = [], {}
    for kind, name, expected_unit in targets:
        mapping = maps.get(kind, {})
        source = mapping.get(name) if isinstance(mapping, dict) else None
        # Candidate suggestions use exact technical identifier and unit only.
        # Free-text tool/column descriptions are intentionally ignored.
        exact = [field for field, item in columns.items()
                 if field == name and item.get("type") == "number" and item.get("unit") == expected_unit]
        if not source and len(exact) == 1:
            source = exact[0]
            proposal_basis = "EXACT_FIELD_NAME_AND_UNIT_MATCH"
        elif source:
            proposal_basis = "EXPLICIT_SITE_PROFILE_MAPPING"
        else:
            proposal_basis = "NO_SAFE_AUTOMATIC_MATCH"
        column = columns.get(source) if isinstance(source, str) else None
        problems = []
        if column is None:
            problems.append("mapped source field is absent from the semantic catalog")
        else:
            if column.get("type") != "number":
                problems.append("mapped field type is not numeric")
            if column.get("unit") != expected_unit:
                problems.append(f"unit mismatch: expected {expected_unit!r}, received {column.get('unit')!r}")
            if source in used_fields:
                problems.append(f"source field is already assigned to {used_fields[source]}")
            used_fields[source] = f"{kind}:{name}"
        proposals.append({"target_role": f"{kind}:{name}", "source_field": source,
                          "expected_type": "number", "expected_unit": expected_unit,
                          "catalog_type": column.get("type") if column else None,
                          "catalog_unit": column.get("unit") if column else None,
                          "proposal_basis": proposal_basis,
                          "status": "REVIEW_REQUIRED" if not problems else "REFUSED",
                          "validation_errors": problems,
                          "authority": "proposal only; only an authorized semantic owner can approve this mapping"})
    return proposals, failures


def inspect_onboarding(adapter, config):
    """Discover a configured site and create exact-match, always-unapproved role proposals."""
    environment = config.get("environment")
    profile = config.get("p4_profile")
    sources = config.get("approved_source_ids")
    versions = config.get("approved_semantic_versions")
    result = {"status": "CONFIGURATION_REPAIR_REQUIRED", "authority": "Mappings are proposals only; this report cannot approve semantics or authorization.",
              "environment": environment, "source_role_proposals": [], "validation": [],
              "tool_mapping_review": [], "relationship_review": "NOT_REQUESTED",
              "authorized_review": {"status": "PENDING_SITE_OWNER", "reviewer": None,
                  "approval_reference": None, "reviewed_at": None,
                  "instruction": "An authorized site owner must approve mappings; this report cannot approve itself."}}
    if not isinstance(profile, dict):
        result["validation"].append({"check": "P4 profile", "status": "REFUSED", "detail": "site config must contain an explicit p4_profile"})
        return result
    normalization = profile.get("normalization")
    semantic_version = profile.get("semantic_version")
    permission_scope = profile.get("permission_scope")
    if (not isinstance(sources, list) or not sources or not isinstance(versions, list)
            or semantic_version not in versions or not isinstance(permission_scope, str) or not permission_scope):
        result["validation"].append({"check": "source allowlist", "status": "REFUSED", "detail": "profile source version and permission scope must match the site allowlists"})
        return result
    discovered = adapter.call("discover", {"permission_scope": permission_scope})
    tool_versions = discovered.get("tool_versions")
    result["tool_mapping_review"] = [
        {"logical_operation": operation, "configured_tool": mapping.get("tool_name") if isinstance(mapping, dict) else None,
         "discovered": bool(isinstance(tool_versions, dict) and tool_versions.get(mapping.get("tool_name"))) if isinstance(mapping, dict) else False,
         "status": "REVIEW_REQUIRED"}
        for operation, mapping in sorted(config.get("operations", {}).items())]
    tool_mappings_valid = bool(result["tool_mapping_review"]) and all(item["discovered"] for item in result["tool_mapping_review"])
    if (not tool_mappings_valid or not isinstance(tool_versions, dict) or semantic_version not in discovered.get("semantic_versions", [])
            or permission_scope not in discovered.get("auth_scopes", [])
            or discovered.get("audit_support") is not True):
        result["validation"].append({"check": "MCP discovery", "status": "REFUSED", "detail": "server discovery does not confirm every configured logical tool, exact version, scope, and audit capability"})
        return result
    semantics = adapter.call("semantics", {"approved_source_ids": sources, "semantic_version": semantic_version})
    source_versions = semantics.get("source_versions")
    if (semantics.get("semantic_version") != semantic_version or not semantics.get("approval")
            or semantics.get("grain") != profile.get("analysis_template", {}).get("grain")
            or not isinstance(source_versions, dict) or set(source_versions) != set(sources)
            or any(not isinstance(v, str) or not v for v in source_versions.values())):
        result["validation"].append({"check": "semantic version/grain", "status": "REFUSED", "detail": "semantic response lacks exact approval, version, or P4 grain match"})
        return result
    columns = _column_catalog(semantics)
    proposals, profile_failures = _role_proposals(profile, columns)
    result["source_role_proposals"] = proposals
    proposed_normalization = None
    if proposals and all(not proposal["validation_errors"] for proposal in proposals):
        proposed_normalization = {**normalization,
            "factor_fields": {proposal["target_role"].split(":", 1)[1]: proposal["source_field"]
                              for proposal in proposals if proposal["target_role"].startswith("factor:")},
            "metric_fields": {proposal["target_role"].split(":", 1)[1]: proposal["source_field"]
                              for proposal in proposals if proposal["target_role"].startswith("metric:")}}
        result["proposed_normalization"] = proposed_normalization
    result["semantic_catalog"] = {"semantic_version": semantics.get("semantic_version"),
        "grain": semantics.get("grain"), "source_versions": semantics.get("source_versions"),
        "columns": [{"name": c["name"], "type": c["type"], "unit": c.get("unit")}
                    for c in columns.values()]}
    if len(sources) == 2:
        try:
            relationship = _validate_relationship(adapter, sources, profile.get("time_window"), semantics,
                                                   profile.get("analysis_template", {}),
                                                   proposed_normalization or profile.get("normalization", {}),
                                                   internal_authorized=environment == "INTERNAL_APPROVED_ONLY")
            result["relationship_review"] = {"status": "REVIEW_REQUIRED", "relationship_id": relationship.get("relationship_id"),
                                               "contract_version": relationship.get("contract_version"),
                                               "approval_reference": relationship.get("approval_reference")}
        except (McpError, McpPermissionError, KeyError, TypeError, AttributeError) as exc:
            result["relationship_review"] = {"status": "REFUSED", "reason": str(exc)}
    elif len(sources) == 1:
        result["relationship_review"] = "NOT_REQUIRED_FOR_SINGLE_SOURCE"
    else:
        result["relationship_review"] = {"status": "REFUSED", "reason": "P4 supports one source or one approved two-source relationship"}
    result["validation"].extend([{"check": "semantic version/grain", "status": "PASS", "detail": "exact configured version and analysis grain match"},
                                 {"check": "factor/outcome mappings", "status": "REVIEW_REQUIRED" if proposed_normalization else "REFUSED",
                                  "detail": "field types, units, and target uniqueness checked; any proposed normalization still requires authorized site-owner approval"},
                                 {"check": "experimental context", "status": "REFUSED" if profile_failures else "PASS",
                                  "detail": "; ".join(profile_failures) if profile_failures else "objective, context, approved factor bounds, outcome directions, grain, sampling unit, and timestamp semantics are present"}])
    relation_status = (result["relationship_review"].get("status")
                       if isinstance(result["relationship_review"], dict) else "PASS")
    result["status"] = ("REVIEW_REQUIRED" if not profile_failures
                         and proposed_normalization is not None
                         and relation_status != "REFUSED"
                         else "CONFIGURATION_REPAIR_REQUIRED")
    result["authorized_review"] = {"status": "PENDING_SITE_OWNER", "reviewer": None,
        "approval_reference": None, "reviewed_at": None,
        "instruction": "An authorized site owner must inspect the source definitions, proposal basis, units, relationships, row grain, context, permissions, and read plan. This report cannot approve itself."}
    return result
