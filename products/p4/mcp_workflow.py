"""Fail-closed synthetic MCP acquisition and P4 analysis composition.

The official MCP SDK and configured semantic adapter own transport and logical
tool mapping. This module validates the returned site contract and maps only
explicitly supplied fields into the existing P4 investigation API. It contains
no company tool names, source meanings, or authorization claims.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
import re

from fabintel.contracts import envelope, authorized_envelope, validate_envelope
from fabintel.mcp_client import McpError, McpPermissionError
from products.p4.engine import analyze


MAX_ACQUISITION_ROWS = 1000
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _cancelled(cancel):
    return bool(cancel and cancel())


def _parse_time(value, label):
    if not isinstance(value, str) or not value.strip():
        raise McpError(f"{label} must be a nonempty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise McpError(f"{label} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise McpError(f"{label} must include an explicit UTC offset")
    return parsed


def _refused(request, reason, acquisition=None):
    raw = request if isinstance(request, dict) else {}
    if (isinstance(acquisition, dict) and acquisition.get("environment") == "INTERNAL_APPROVED_ONLY"
            and acquisition.get("qualification_status") == "QUALIFIED_INTERNAL"
            and acquisition.get("site_approval_reference")):
        result = authorized_envelope("p4", raw, "REFUSED", [], [str(reason)],
                                     authorization_reference=acquisition["site_approval_reference"])
    else:
        result = envelope("p4", raw, "REFUSED", [], [str(reason)])
    if acquisition is not None:
        result["provenance"]["mcp_acquisition"] = acquisition
    validate_envelope(result)
    return result


def _columns(semantics):
    values = semantics.get("column_definitions")
    if not isinstance(values, list) or not values:
        raise McpError("semantic response must provide a nonempty column catalog")
    columns = {}
    for column in values:
        if (not isinstance(column, dict) or not isinstance(column.get("name"), str)
                or not column["name"] or not isinstance(column.get("type"), str)):
            raise McpError("semantic column definition is invalid")
        if column["name"] in columns:
            raise McpError("semantic column catalog contains duplicate names")
        columns[column["name"]] = column
    return columns


def _require_column(columns, units, source_name, *, expected_type=None, target_unit=None):
    if source_name not in columns:
        raise McpError(f"semantic schema drift: mapped source field is unavailable: {source_name}")
    definition = columns[source_name]
    if expected_type and definition["type"] != expected_type:
        raise McpError(f"semantic type mismatch for mapped field: {source_name}")
    source_unit = units.get(source_name) if isinstance(units, dict) else None
    source_unit = source_unit or definition.get("unit")
    if not isinstance(source_unit, str) or not source_unit:
        raise McpError(f"semantic unit is missing for mapped field: {source_name}")
    if target_unit is not None and target_unit != source_unit:
        raise McpError(f"semantic unit mismatch for mapped field: {source_name}")


def _validate_time_window(value):
    if not isinstance(value, dict) or not {"start", "end"}.issubset(value):
        raise McpError("time_window requires explicit start and end timestamps")
    start = _parse_time(value["start"], "time_window.start")
    end = _parse_time(value["end"], "time_window.end")
    if start > end:
        raise McpError("time_window start must not exceed end")
    return start, end


def _validate_audit_record(read, audit, source_ids, permission_scope):
    operation_id = read.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise McpError("bounded read omitted its operation ID")
    if audit.get("operation_id") != operation_id:
        raise McpError("audit operation ID does not match the bounded-read operation ID")
    if audit.get("permission_scope") != permission_scope:
        raise McpError("audit record effective permission scope differs from the requested scope")
    audited_sources = audit.get("sources")
    if (not isinstance(audited_sources, list) or len(audited_sources) != len(source_ids)
            or any(not isinstance(source, str) for source in audited_sources)
            or set(audited_sources) != set(source_ids)):
        raise McpError("audit record source list differs from the exact requested source population")
    query_hash = audit.get("query_hash")
    if not isinstance(query_hash, str) or not _SHA256.fullmatch(query_hash):
        raise McpError("audit query hash is missing or malformed")
    timestamps = audit.get("timestamps")
    if not isinstance(timestamps, dict):
        raise McpError("audit timestamps are required")
    started = _parse_time(timestamps.get("started"), "audit started timestamp")
    ended = _parse_time(timestamps.get("ended"), "audit ended timestamp")
    if started > ended:
        raise McpError("audit start timestamp is after its end timestamp")
    return operation_id


def _validate_relationship(adapter, source_ids, time_window, semantics, analysis_template, normalization,
                           *, internal_authorized=False):
    if len(source_ids) == 1:
        return None
    if len(source_ids) != 2:
        raise McpError("P4 join normalization supports only an explicitly approved two-source relationship")
    response = adapter.call("relationships", {"typed_entity_ids": source_ids, "time_window": time_window})
    contract = response.get("relationship_contract")
    if response.get("approved") is not True or response.get("cardinality") != "one_to_one":
        raise McpPermissionError("relationship is not approved one-to-one; P4 will not infer or repair a join")
    if not isinstance(contract, dict) or contract.get("approved") is not True:
        raise McpPermissionError("relationship response omitted its approved, versioned contract")
    if (not isinstance(contract.get("relationship_id"), str) or not contract["relationship_id"].strip()
            or not isinstance(contract.get("approval_reference"), str) or not contract["approval_reference"].strip()
            or (not internal_authorized and (not contract["relationship_id"].startswith("SYN-")
                or not contract["approval_reference"].startswith("SYN-")))
            or not isinstance(contract.get("contract_version"), str) or not contract["contract_version"]):
        raise McpError("relationship contract identity/version is incomplete or not explicitly synthetic")
    upstream, downstream = contract.get("upstream"), contract.get("downstream")
    if not isinstance(upstream, dict) or not isinstance(downstream, dict):
        raise McpError("relationship endpoints are incomplete")
    metric_fields = normalization.get("metric_fields")
    target_metrics = {item.get("name") for item in analysis_template.get("metrics", []) if isinstance(item, dict)}
    if not isinstance(metric_fields, dict):
        raise McpError("relationship requires an explicit P4 metric normalization map")
    for endpoint in (upstream, downstream):
        metric_name, metric_field = endpoint.get("metric"), endpoint.get("metric_field")
        if (not isinstance(metric_name, str) or not metric_name or metric_name not in target_metrics
                or metric_fields.get(metric_name) != metric_field
                or not isinstance(metric_field, str) or not metric_field):
            raise McpPermissionError(
                "approved relationship metric does not match an exact P4 target metric and source-field mapping")
    if (not isinstance(contract.get("maximum_lag_seconds"), (int, float))
            or isinstance(contract.get("maximum_lag_seconds"), bool)
            or contract["maximum_lag_seconds"] <= 0):
        raise McpError("relationship maximum lag must be positive")
    if response.get("grain") != semantics.get("grain") or contract.get("upstream", {}).get("source_id") != source_ids[0] or contract.get("downstream", {}).get("source_id") != source_ids[1]:
        raise McpError("relationship source order or row grain does not match the semantic request")
    if contract.get("unit_field") != normalization.get("unit_field"):
        raise McpError("relationship independent unit field differs from the explicit normalization map")
    keys = response.get("keys")
    if (not isinstance(keys, dict)
            or keys.get("upstream") != contract["upstream"].get("key_field")
            or keys.get("downstream") != contract["downstream"].get("key_field")):
        raise McpError("relationship key metadata disagrees with its approved contract")
    factors = {item.get("name") for item in analysis_template.get("factors", []) if isinstance(item, dict)}
    decision_factors = contract.get("decision_factors")
    if not isinstance(decision_factors, list) or not decision_factors or not set(decision_factors).issubset(factors):
        raise McpError("relationship decision factors are not represented in the P4 analysis template")
    effectivity = response.get("effectivity")
    if not isinstance(effectivity, dict) or effectivity.get("max_lag_seconds") != contract.get("maximum_lag_seconds"):
        raise McpError("relationship lag metadata disagrees with its approved contract")
    return contract


def _normalize_rows(raw_rows, source_ids, semantics, read, audit, permission_scope, time_window,
                    analysis_template, normalization, relationship, *, permission_reference=None):
    if not isinstance(raw_rows, list) or not raw_rows:
        raise McpError("bounded read returned no typed rows")
    if len(raw_rows) > MAX_ACQUISITION_ROWS or read.get("truncation") is not False:
        raise McpError("truncated or oversized reads cannot be treated as a complete analysis population")
    source_versions = read.get("source_versions")
    semantic_versions = semantics.get("source_versions")
    timestamps = audit["timestamps"]
    if (not isinstance(source_versions, dict) or set(source_versions) != set(source_ids)
            or not isinstance(semantic_versions, dict) or set(semantic_versions) != set(source_ids)
            or source_versions != semantic_versions):
        raise McpError("bounded-read source versions do not exactly match the discovered semantic catalog")
    source_hashes = read.get("source_hashes")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(source_ids) or any(
            not isinstance(source_hashes[source], str) or not _SHA256.fullmatch(source_hashes[source]) for source in source_ids):
        raise McpError("bounded read must provide a SHA-256 content hash for every requested source")
    columns = _columns(semantics)
    units = semantics.get("units", {})
    row_id_field = normalization.get("row_id_field")
    unit_field = normalization.get("unit_field")
    timestamp_field = normalization.get("timestamp_field")
    factor_fields = normalization.get("factor_fields")
    metric_fields = normalization.get("metric_fields")
    uncertainty_fields = normalization.get("measurement_uncertainty_fields", {})
    passthrough_fields = normalization.get("passthrough_fields", [])
    if any(not isinstance(value, str) or not value for value in (row_id_field, unit_field, timestamp_field)):
        raise McpError("row ID, unit, and timestamp fields must be explicitly mapped")
    if not isinstance(factor_fields, dict) or not isinstance(metric_fields, dict):
        raise McpError("factor_fields and metric_fields must be explicit target-to-source maps")
    if not isinstance(uncertainty_fields, dict):
        raise McpError("measurement_uncertainty_fields must be an explicit metric-to-source map")
    if not isinstance(passthrough_fields, list) or any(not isinstance(field, str) or not field for field in passthrough_fields):
        raise McpError("passthrough_fields must be an explicit list of source field names")
    target_factors = {item.get("name"): item for item in analysis_template.get("factors", []) if isinstance(item, dict)}
    target_metrics = {item.get("name"): item for item in analysis_template.get("metrics", []) if isinstance(item, dict)}
    if set(factor_fields) != set(target_factors) or set(metric_fields) != set(target_metrics):
        raise McpError("normalization maps must cover the declared P4 factors and metrics exactly")
    if (not set(uncertainty_fields).issubset(target_metrics)
            or any(not isinstance(value, str) or not value for value in uncertainty_fields.values())
            or len(set(uncertainty_fields.values())) != len(uncertainty_fields)):
        raise McpError("measurement-uncertainty mappings must uniquely identify declared metric source fields")
    mapped_sources = {row_id_field, unit_field, timestamp_field,
                      *factor_fields.values(), *metric_fields.values(), *passthrough_fields}
    if mapped_sources.intersection(uncertainty_fields.values()):
        raise McpError("measurement-uncertainty source fields must be distinct from other normalized fields")
    _require_column(columns, units, row_id_field, expected_type="string")
    _require_column(columns, units, unit_field, expected_type="string")
    _require_column(columns, units, timestamp_field, expected_type="string")
    for target, source_name in factor_fields.items():
        _require_column(columns, units, source_name, expected_type="number", target_unit=target_factors[target].get("unit"))
    for target, source_name in metric_fields.items():
        _require_column(columns, units, source_name, expected_type="number", target_unit=target_metrics[target].get("unit"))
    for target, source_name in uncertainty_fields.items():
        _require_column(columns, units, source_name, expected_type="number", target_unit=target_metrics[target].get("unit"))
    for field in passthrough_fields:
        if field not in columns:
            raise McpError(f"semantic schema drift: passthrough source field is unavailable: {field}")
    _require_column(columns, units, relationship["upstream"]["key_field"], expected_type="string") if relationship else None
    _require_column(columns, units, relationship["downstream"]["key_field"], expected_type="string") if relationship else None
    if relationship:
        for endpoint in (relationship["upstream"], relationship["downstream"]):
            _require_column(columns, units, endpoint.get("event_time_field"), expected_type="string")
            _require_column(columns, units, endpoint.get("population_field"), expected_type="string")
            _require_column(columns, units, endpoint.get("metric_field"), expected_type="number")
    expected_grain = analysis_template.get("grain")
    if not isinstance(expected_grain, str) or expected_grain != semantics.get("grain"):
        raise McpError("analysis row grain must exactly match approved source semantics")
    lower, upper = _validate_time_window(time_window)
    seen_rows, seen_units, observations = set(), set(), []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            raise McpError(f"typed row {index} is not an object")
        row_id, unit_id = raw.get(row_id_field), raw.get(unit_field)
        if not isinstance(row_id, str) or not row_id or row_id in seen_rows:
            raise McpError("typed row IDs must be unique nonempty strings")
        if not isinstance(unit_id, str) or not unit_id:
            raise McpError("typed independent-unit identifiers must be nonempty strings")
        seen_rows.add(row_id)
        observed_at = _parse_time(raw.get(timestamp_field), f"typed row {row_id} timestamp")
        if not lower <= observed_at <= upper:
            raise McpError("bounded read returned an observation outside the exact requested time window")
        normalized = {"id": row_id, "factors": {}, "metrics": {}, "source_ids": source_ids,
                      unit_field: unit_id, timestamp_field: raw[timestamp_field]}
        for target, source_name in factor_fields.items():
            value = raw.get(source_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise McpError(f"mapped factor is missing or not numeric: {source_name}")
            normalized["factors"][target] = value
        for target, source_name in metric_fields.items():
            value = raw.get(source_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise McpError(f"mapped metric is missing or not numeric: {source_name}")
            normalized["metrics"][target] = value
        if uncertainty_fields:
            normalized["measurement_uncertainty"] = {}
            for target, source_name in uncertainty_fields.items():
                value = raw.get(source_name)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or value < 0):
                    raise McpError(f"mapped measurement uncertainty must be finite and nonnegative: {source_name}")
                normalized["measurement_uncertainty"][target] = value
        for field in passthrough_fields:
            if field not in raw:
                raise McpError(f"mapped passthrough value is missing from typed row: {field}")
            normalized[field] = raw[field]
        if relationship:
            up, down = relationship["upstream"], relationship["downstream"]
            up_key, down_key = raw.get(up["key_field"]), raw.get(down["key_field"])
            if not isinstance(up_key, str) or not up_key or up_key != down_key:
                raise McpError("joined row violates the approved relationship key equality")
            if unit_id != up_key:
                raise McpError("normalized unit identity disagrees with the approved relationship keys")
            if up_key in seen_units:
                raise McpError("joined rows violate the approved one-to-one relationship grain")
            seen_units.add(up_key)
            endpoint_times = [_parse_time(raw.get(up["event_time_field"]), "upstream event timestamp"),
                              _parse_time(raw.get(down["event_time_field"]), "downstream event timestamp")]
            if any(not lower <= value <= upper for value in endpoint_times):
                raise McpError("joined relationship event lies outside the approved time window")
            lag = abs((endpoint_times[1]-endpoint_times[0]).total_seconds())
            if lag > relationship["maximum_lag_seconds"]:
                raise McpError("joined events exceed the approved maximum lag")
            if any(raw.get(endpoint["population_field"]) != endpoint["population_id"] for endpoint in (up, down)):
                raise McpError("joined row population differs from the approved relationship population")
            if any(isinstance(raw.get(endpoint["metric_field"]), bool)
                   or not isinstance(raw.get(endpoint["metric_field"]), (int, float))
                   for endpoint in (up, down)):
                raise McpError("joined relationship metric field is missing or nonnumeric")
            # Retain only fields explicitly named by the approved relationship.
            # D03 consumes these after normalization to revalidate paired unit,
            # time, population, and objective evidence instead of trusting the
            # MCP join result alone.
            relationship_fields = set()
            for endpoint in (up, down):
                relationship_fields.update(endpoint[key] for key in
                    ("key_field", "event_time_field", "population_field", "metric_field"))
            for field in relationship_fields:
                if not isinstance(field, str) or not field or field not in columns:
                    raise McpError("approved relationship references an unavailable semantic field")
                if field not in raw:
                    raise McpError(f"approved relationship field is absent from the bounded row: {field}")
                normalized[field] = raw[field]
            for composition in relationship.get("population_composition_fields", []):
                if not isinstance(composition, dict):
                    raise McpError("approved population composition mapping is malformed")
                for key in ("upstream_field", "downstream_field"):
                    field = composition.get(key)
                    if not isinstance(field, str) or not field or field not in columns:
                        raise McpError("approved population composition field is unavailable in semantic catalog")
                    _require_column(columns, units, field, expected_type="string")
                    if field not in raw:
                        raise McpError(f"approved population composition field is absent from bounded row: {field}")
                    normalized[field] = raw[field]
        observations.append(normalized)

    versions = read["source_versions"]
    source_refs = [{"id": source_id, "approved_semantic_version": semantics["semantic_version"],
                    "grain": semantics["grain"], "source_hash": source_hashes[source_id],
                    "permissions_ref": permission_reference or permission_scope, "observed_at": timestamps["ended"]}
                   for source_id in source_ids]
    return observations, source_refs, versions, source_hashes


def run_mcp_investigation(adapter, request, *, cancel=None):
    """Acquire through configured logical operations, normalize, then analyze.

    Internal acquisition is available only to a site configuration already
    marked QUALIFIED_INTERNAL by the site owner. This function records that
    assertion but cannot authenticate company approval or server permissions.
    """
    config = adapter.config
    environment = config.get("environment")
    internal_authorized = environment == "INTERNAL_APPROVED_ONLY"
    acquisition = {"status": "NOT_STARTED", "environment": environment or "UNKNOWN"}
    read = None
    try:
        if not isinstance(request, dict):
            raise McpError("MCP investigation request must be an object")
        if environment == "SYNTHETIC_TEST_ONLY":
            if config.get("qualification_status") != "PENDING_INTERNAL":
                raise McpPermissionError("synthetic MCP config must retain PENDING_INTERNAL qualification")
        elif environment == "INTERNAL_APPROVED_ONLY":
            if (config.get("qualification_status") != "QUALIFIED_INTERNAL"
                    or not isinstance(config.get("site_approval_reference"), str)
                    or not config["site_approval_reference"].strip()):
                raise McpPermissionError("internal MCP analysis requires site-qualified config and an explicit site approval reference")
            acquisition.update({"qualification_status": "QUALIFIED_INTERNAL",
                                "site_approval_reference": config["site_approval_reference"]})
        else:
            raise McpPermissionError("MCP analysis requires explicit synthetic-test or internally qualified configuration")
        if _cancelled(cancel):
            return _refused(request, "MCP investigation was cancelled before any source acquisition", acquisition)
        source_ids = request.get("approved_source_ids")
        semantic_version = request.get("semantic_version")
        permission_scope = request.get("permission_scope")
        time_window = request.get("time_window")
        approved_plan = request.get("approved_plan")
        permission_context = request.get("permission_context")
        max_rows = request.get("max_rows")
        normalization = request.get("normalization")
        analysis_template = request.get("analysis_template")
        if (not isinstance(source_ids, list) or not source_ids or len(set(source_ids)) != len(source_ids)
                or any(source not in adapter.source_ids for source in source_ids)):
            raise McpPermissionError("request sources must be a unique subset of the explicit site allowlist")
        if semantic_version not in adapter.semantic_versions:
            raise McpPermissionError("request semantic version is outside the explicit site allowlist")
        if not isinstance(permission_scope, str) or not permission_scope:
            raise McpPermissionError("an explicit read permission scope is required")
        _validate_time_window(time_window)
        if (not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ACQUISITION_ROWS
                or not isinstance(approved_plan, dict) or approved_plan.get("source_ids") != source_ids
                or approved_plan.get("time_window") != time_window
                or not isinstance(permission_context, dict) or permission_context.get("scope") != permission_scope
                or permission_context.get("read_only") is not True):
            raise McpPermissionError("bounded acquisition must match explicit sources/time window and read-only permission context")
        if not isinstance(normalization, dict) or not isinstance(analysis_template, dict):
            raise McpError("explicit normalization map and P4 analysis template are required")
        if any(key in analysis_template for key in ("observations", "sources", "linkage", "request_actuation", "request_recipe_change")):
            raise McpError("analysis template may not bypass acquired rows, source lineage, relationship, or actuation gates")
        if "mode" in analysis_template:
            raise McpPermissionError("analysis mode is derived from the configured acquisition environment")

        discovered = adapter.call("discover", {"permission_scope": permission_scope})
        tool_versions = discovered.get("tool_versions")
        if (not isinstance(tool_versions, dict) or not isinstance(discovered.get("semantic_versions"), list)
                or semantic_version not in discovered["semantic_versions"]
                or permission_scope not in discovered.get("auth_scopes", [])
                or discovered.get("audit_support") is not True):
            raise McpPermissionError("discovery does not qualify the requested semantics, scope, and audit support")
        configured_operations = adapter.config.get("operations", {})
        for operation in ("discover", "semantics", "relationships", "read_bounded", "audit"):
            if operation == "relationships" and len(source_ids) == 1:
                continue
            tool_name = configured_operations.get(operation, {}).get("tool_name")
            if not isinstance(tool_name, str) or not tool_versions.get(tool_name):
                raise McpError(f"discovery omitted the configured logical operation version: {operation}")
        server_limit = discovered.get("limits", {}).get("max_rows")
        if not isinstance(server_limit, int) or isinstance(server_limit, bool) or max_rows > server_limit:
            raise McpPermissionError("requested bounded row count exceeds the discovered server limit")
        if _cancelled(cancel):
            return _refused(request, "MCP investigation was cancelled before semantic lookup", acquisition)

        semantics = adapter.call("semantics", {"approved_source_ids": source_ids,
                                                 "semantic_version": semantic_version})
        effectivity = semantics.get("effectivity")
        if (semantics.get("approval") is None or semantics.get("semantic_version") != semantic_version
                or not isinstance(semantics.get("grain"), str) or not semantics["grain"]):
            raise McpPermissionError("semantic response is not approved at the exact requested version/grain")
        if not isinstance(effectivity, dict):
            raise McpError("semantic effectivity metadata is missing")
        semantic_start = _parse_time(effectivity.get("start"), "semantic effective start")
        semantic_end_value = effectivity.get("end")
        semantic_end = _parse_time(semantic_end_value, "semantic effective end") if semantic_end_value else None
        lower, upper = _validate_time_window(time_window)
        if lower < semantic_start or (semantic_end and upper > semantic_end):
            raise McpPermissionError("requested time window is outside semantic effective dates")
        relationship = _validate_relationship(adapter, source_ids, time_window, semantics, analysis_template, normalization,
                                              internal_authorized=internal_authorized)
        if _cancelled(cancel):
            return _refused(request, "MCP investigation was cancelled before the bounded read", acquisition)

        read = adapter.call("read_bounded", {"approved_plan": approved_plan,
            "permission_context": permission_context,
            "limits": {"max_rows": max_rows, "read_only": True}})
        audit_id = read.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            raise McpError("bounded read omitted its audit receipt ID")
        operation_id = read.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise McpError("bounded read omitted its operation ID")
        audit = adapter.call("audit", {"operation_id": operation_id})
        audit_operation_id = _validate_audit_record(read, audit, source_ids, permission_scope)
        acquisition.update({"status": "AUDITED_READ_COMPLETED", "environment": environment,
            "logical_contract_version": adapter.contract.get("contract_version"),
            "semantic_version": semantic_version, "source_ids": source_ids,
            "source_versions": read.get("source_versions"), "source_hashes": read.get("source_hashes"),
            "row_count": len(read.get("typed_rows", [])) if isinstance(read.get("typed_rows"), list) else None,
            "truncation": read.get("truncation"), "read_only": True, "time_window": time_window,
            "operation_id": operation_id, "audit_id": audit_id, "audit_operation_id": audit_operation_id,
            "audit_query_hash": audit.get("query_hash"),
            "permission_scope": audit.get("permission_scope"), "relationship_id": relationship.get("relationship_id") if relationship else None})
        if _cancelled(cancel):
            cancel_result = None
            cancel_result = adapter.call("cancel", {"operation_id": operation_id})
            acquisition["status"] = "CANCELLED_AFTER_AUDITED_READ"
            acquisition["cancel_confirmed"] = cancel_result.get("confirmed_stopped") if cancel_result else False
            return _refused(request, "MCP investigation was cancelled after read; no P4 analysis was started", acquisition)

        observations, source_refs, source_versions, source_hashes = _normalize_rows(
            read.get("typed_rows"), source_ids, semantics, read, audit, permission_scope, time_window,
            analysis_template, normalization, relationship,
            permission_reference=config.get("site_approval_reference") if internal_authorized else None)
        data = dict(analysis_template)
        if internal_authorized:
            data["mode"] = "INTERNAL_AUTHORIZED"
        data["observations"] = observations
        data["sources"] = source_refs
        if relationship:
            data["linkage"] = relationship
        result = analyze(data, cancel=cancel, acquisition=acquisition if internal_authorized else None)
        acquisition.update({"status": ("ANALYSIS_REFUSED" if result.get("status") == "REFUSED"
                                         else "ANALYSIS_COMPLETED"),
                            "normalized_rows": len(observations),
                            "source_versions": source_versions, "source_hashes": source_hashes,
                            "measurement_uncertainty_metrics": sorted(normalization.get("measurement_uncertainty_fields", {})),
                            "relationship_id": relationship.get("relationship_id") if relationship else None})
        result["provenance"]["mcp_acquisition"] = acquisition
        validate_envelope(result)
        return result
    except (McpError, McpPermissionError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        if read and acquisition.get("status") == "NOT_STARTED":
            acquisition = {"status": "READ_RETURNED_AUDIT_NOT_CONFIRMED", "audit_id": read.get("audit_id"),
                           "operation_id": read.get("operation_id"),
                           "row_count": len(read.get("typed_rows", [])) if isinstance(read.get("typed_rows"), list) else None}
        return _refused(request, str(exc), acquisition)
