"""Offline structural checks for a site-authored MCP configuration."""
from __future__ import annotations

import json
from pathlib import Path

from fabintel.mcp_client import transport_from_config, McpError

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = json.loads((ROOT / "contracts" / "adapter-operations.v1.json").read_text(encoding="utf-8"))
P4_REQUIRED_RESULTS = {
    "semantics": {"semantic_version", "source_versions"},
    "relationships": {"relationship_contract"},
    "read_bounded": {"operation_id", "source_versions", "source_hashes"},
}


def _contains_plain_secret(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if (("password" in name or "secret" in name or "credential" in name
                 or name in {"authorization", "authorization_header", "auth_header"} or "api_key" in name
                 or ("token" in name and not name.endswith("_env")))):
                return f"plaintext secret-like config key at {path + key}"
            found = _contains_plain_secret(child, path + key + ".")
            if found:
                return found
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found = _contains_plain_secret(child, f"{path}{i}.")
            if found:
                return found
    return None


def validate_site_config(config):
    """Validate shape and local consistency; never connect or approve semantics."""
    errors = []
    if not isinstance(config, dict):
        return {"status": "CONFIGURATION_REPAIR_REQUIRED", "network_requests": 0,
                "p4_workflow_ready": False, "errors": ["configuration must be a JSON object"]}
    if config.get("config_version") != "1.0.0":
        errors.append("config_version must equal 1.0.0")
    environment = config.get("environment")
    if environment not in ("SYNTHETIC_TEST_ONLY", "INTERNAL_APPROVED_ONLY"):
        errors.append("environment must be explicit: SYNTHETIC_TEST_ONLY or INTERNAL_APPROVED_ONLY")
    qualification = config.get("qualification_status")
    if environment == "SYNTHETIC_TEST_ONLY" and qualification != "PENDING_INTERNAL":
        errors.append("synthetic config must remain PENDING_INTERNAL")
    if environment == "INTERNAL_APPROVED_ONLY" and qualification not in ("PENDING_INTERNAL", "QUALIFIED_INTERNAL"):
        errors.append("internal qualification_status is invalid")
    if environment == "INTERNAL_APPROVED_ONLY" and qualification == "QUALIFIED_INTERNAL":
        if not isinstance(config.get("site_approval_reference"), str) or not config["site_approval_reference"].strip():
            errors.append("qualified internal config requires a site approval reference")
    source_ids, versions = config.get("approved_source_ids"), config.get("approved_semantic_versions")
    for name, values in (("approved_source_ids", source_ids), ("approved_semantic_versions", versions)):
        if (not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values)
                or len(values) != len(set(values))):
            errors.append(f"{name} must be a unique list of nonempty strings")
    if environment == "INTERNAL_APPROVED_ONLY" and qualification == "QUALIFIED_INTERNAL":
        if not source_ids or not versions:
            errors.append("qualified internal config requires approved source IDs and semantic versions")
    try:
        # Structural validation must not read credentials or open a process/session.
        transport_from_config(config, require_environment=False)
    except (McpError, TypeError, AttributeError) as exc:
        errors.append(f"transport: {exc}")
    secret_issue = _contains_plain_secret(config)
    if secret_issue:
        errors.append(secret_issue)
    operations = config.get("operations")
    p4_ready = True
    if not isinstance(operations, dict):
        operations = {}
        errors.append("operations must be an object")
    source_count = len(source_ids) if isinstance(source_ids, list) else 0
    required_operations = {entry["name"] for entry in CONTRACT["logical_operations"]}
    if source_count < 2:
        required_operations.discard("relationships")
    for operation in sorted(required_operations):
        mapping = operations.get(operation)
        spec = next(entry for entry in CONTRACT["logical_operations"] if entry["name"] == operation)
        if not isinstance(mapping, dict):
            errors.append(f"logical operation {operation} is not explicitly mapped")
            p4_ready = False
            continue
        if not isinstance(mapping.get("tool_name"), str) or not mapping["tool_name"].strip():
            errors.append(f"{operation}.tool_name must be supplied by the site owner")
            p4_ready = False
        input_map, result_map = mapping.get("input_map"), mapping.get("result_map")
        valid_input_map = (isinstance(input_map, dict)
                           and all(isinstance(key, str) and key and isinstance(value, str) and value
                                   for key, value in input_map.items()))
        if not valid_input_map or not set(spec["requires"]).issubset(set(input_map.values())):
            errors.append(f"{operation}.input_map must explicitly map every required logical input")
            p4_ready = False
        valid_result_map = (isinstance(result_map, dict)
                            and all(isinstance(key, str) and key and isinstance(value, str) and value
                                    for key, value in result_map.items()))
        if not valid_result_map or not set(spec["returns"]).issubset(result_map):
            errors.append(f"{operation}.result_map must return every frozen logical result field")
            p4_ready = False
        if isinstance(result_map, dict) and not P4_REQUIRED_RESULTS.get(operation, set()).issubset(result_map):
            missing = sorted(P4_REQUIRED_RESULTS[operation] - set(result_map))
            errors.append(f"{operation}.result_map is missing P4 evidence fields: {', '.join(missing)}")
            p4_ready = False
    profile = config.get("p4_profile")
    if not isinstance(profile, dict):
        p4_ready = False
        errors.append("p4_profile is missing; acquisition cannot be composed with a D01-D05 investigation")
    else:
        if profile.get("semantic_version") not in (versions if isinstance(versions, list) else []):
            errors.append("p4_profile.semantic_version must be in approved_semantic_versions")
            p4_ready = False
        if profile.get("permission_scope") is None or not isinstance(profile.get("permission_scope"), str) or not profile["permission_scope"].strip():
            errors.append("p4_profile.permission_scope is required")
            p4_ready = False
        start, end = (profile.get("time_window", {}).get("start"), profile.get("time_window", {}).get("end")) if isinstance(profile.get("time_window"), dict) else (None, None)
        try:
            from datetime import datetime
            start_time = datetime.fromisoformat(start.replace("Z", "+00:00")) if isinstance(start, str) else None
            end_time = datetime.fromisoformat(end.replace("Z", "+00:00")) if isinstance(end, str) else None
            valid_window = (start_time is not None and end_time is not None
                            and start_time.utcoffset() is not None and end_time.utcoffset() is not None
                            and start_time <= end_time)
        except ValueError:
            valid_window = False
        if not valid_window:
            errors.append("p4_profile.time_window must contain explicit start and end timestamps")
            p4_ready = False
        plan = profile.get("approved_plan")
        if (not isinstance(plan, dict) or plan.get("source_ids") != source_ids
                or plan.get("time_window") != profile.get("time_window")):
            errors.append("p4_profile.approved_plan must exactly match the approved source allowlist and time window")
            p4_ready = False
        permission = profile.get("permission_context")
        if (not isinstance(permission, dict) or permission.get("scope") != profile.get("permission_scope")
                or permission.get("read_only") is not True):
            errors.append("p4_profile.permission_context must match the explicit read-only permission scope")
            p4_ready = False
        limit = profile.get("max_rows")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            errors.append("p4_profile.max_rows must be an integer from 1 to 1000")
            p4_ready = False
        if not isinstance(profile.get("normalization"), dict) or not isinstance(profile.get("analysis_template"), dict):
            errors.append("p4_profile requires explicit normalization and analysis_template objects")
            p4_ready = False
    return {"status": "CONFIGURATION_REPAIR_REQUIRED" if errors else "STRUCTURALLY_VALID_REVIEW_REQUIRED",
            "network_requests": 0, "p4_workflow_ready": bool(p4_ready and not errors),
            "company_authorization_authenticated": False,
            "errors": errors,
            "still_requires": ["authorized semantic owner reviews source-role proposals and units",
                               "Fab Insight administrator confirms server-enforced read-only grants",
                               "site owner records the authorized review and qualification decision"]}
