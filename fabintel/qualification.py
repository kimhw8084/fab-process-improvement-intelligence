"""Check a supplied adapter capability snapshot against the frozen logical contract.

This is a compatibility shape check only. It cannot authenticate a company tool,
verify server-side permissions, or perform an internal qualification.
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def inspect_capability_report(report):
    if not isinstance(report, dict):
        raise ValueError("capability report must be a JSON object")
    contract = json.loads((BASE / "contracts" / "adapter-operations.v1.json").read_text(encoding="utf-8"))
    failures = []
    if report.get("contract_version") != contract["contract_version"]:
        failures.append("logical contract version mismatch")
    if report.get("environment") != "INTERNAL_APPROVED_ONLY":
        failures.append("report environment must be INTERNAL_APPROVED_ONLY")
    operations = report.get("operations")
    if not isinstance(operations, dict):
        operations = {}
        failures.append("operations map is missing")
    for spec in contract["logical_operations"]:
        name = spec["name"]
        actual = operations.get(name)
        if not isinstance(actual, dict) or actual.get("supported") is not True:
            failures.append(f"logical operation unsupported: {name}")
            continue
        returned = actual.get("returns", [])
        if isinstance(returned, dict):
            returned = [key for key, present in returned.items() if present is True]
        if not isinstance(returned, list):
            returned = []
        missing = sorted(set(spec["returns"]) - set(returned))
        if missing:
            failures.append(f"{name} missing logical result fields: {', '.join(missing)}")
    read = operations.get("read_bounded", {})
    if isinstance(read, dict):
        if read.get("read_only") is not True:
            failures.append("read_bounded is not explicitly read-only")
        if not isinstance(read.get("max_rows"), int) or isinstance(read.get("max_rows"), bool) or not 1 <= read["max_rows"] <= 1000:
            failures.append("read_bounded max_rows must be an integer from 1 to 1000")
        if not isinstance(read.get("max_seconds"), (int, float)) or not 0 < read["max_seconds"] <= 30:
            failures.append("read_bounded max_seconds must be in (0, 30]")
    return {"status": "PENDING_INTERNAL", "static_compatibility": "FAIL" if failures else "SHAPE_COMPATIBLE",
            "network_requests": 0, "logical_contract": contract["contract_version"],
            "failures": failures,
            "still_requires": ["authenticate actual approved MCP and user scope", "verify server-enforced read-only grants",
                               "inspect approved semantic versions and relationships", "execute authorized bounded read/cancel/audit tests",
                               "qualify target OS, approved UI host and model", "record engineer and security-owner approval"],
            "warning": "This checker validates only a supplied logical capability snapshot; it never calls company services or certifies authorization."}
