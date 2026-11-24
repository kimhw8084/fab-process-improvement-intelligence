"""Offline P4 command line; internal qualification never connects to a service."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fabintel.catalog import synthetic_catalog
from fabintel.contracts import validate_envelope
from fabintel.project import analyze
from fabintel.server import preflight_report, serve

BASE = Path(__file__).resolve().parent.parent


def _read_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("input file exceeds 2 MiB")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("input file must contain a JSON object")
    return data


def _write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(prog="python -m fabintel",
                                     description="Local, deterministic FAB process-improvement analysis (synthetic-only build).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="show product and qualification state")
    commands.add_parser("demo", help="run the fixed synthetic example")
    pre = commands.add_parser("preflight", help="show pending internal qualification without networking")
    pre.add_argument("--report", help="inspect a locally supplied logical capability report")
    run = commands.add_parser("analyze", help="analyze a local JSON investigation")
    run.add_argument("--input", "-i", required=True)
    run.add_argument("--output", "-o", default="")
    catalog = commands.add_parser("catalog", help="generate a deterministic synthetic 13,000-table catalog")
    catalog.add_argument("--tables", type=int, default=13000)
    catalog.add_argument("--output", default="")
    web = commands.add_parser("serve", help="start the synthetic headless API fixture on loopback only")
    web.add_argument("--port", type=int, default=8765)
    mcp_test = commands.add_parser("mcp-test", help="exercise configured MCP transports only against an explicit synthetic test config")
    mcp_test.add_argument("--config", default=str(BASE / "requirements" / "synthetic-mcp-mapping.v1.json"))
    site_test = commands.add_parser("site-mcp-qualify", help="run site-owned MCP checks after explicit company authorization")
    site_test.add_argument("--config", required=True)
    site_test.add_argument("--site-approval-reference", required=True)
    site_test.add_argument("--authorized-site-test", action="store_true", required=True,
                           help="explicitly confirms that the operator has approval for this read-only site test")
    site_test.add_argument("--output", default="", help="write the local qualification report to this file")
    args = parser.parse_args()

    if args.command == "doctor":
        obj = {"state": "CANDIDATE", "external_transfer_ready": False, "internal_state": "PENDING_INTERNAL",
               "product_id": "p4", "engine_version": "1.2.1",
               "dependencies": {"scientific_core": "Python standard library only",
                                "mcp_adapter": "optional pinned SDK extra; macOS ARM64 CPython 3.11 candidate only",
                                "ui": "P1-owned React host peer; no P4 shell or chart runtime"},
               "network": "none in core CLI; synthetic test API is loopback-only",
               "note": "See release/GATE_REPORT.json for evidence and remaining gates."}
    elif args.command == "preflight":
        obj = preflight_report()
        if args.report:
            from fabintel.qualification import inspect_capability_report
            obj = inspect_capability_report(_read_json(args.report))
    elif args.command == "catalog":
        obj = {"catalog_version": "SYNTHETIC-1", "tables": synthetic_catalog(args.tables)}
        if args.output:
            _write_json(args.output, obj)
            print(f"WROTE SYNTHETIC catalog: {args.output}", file=sys.stderr)
            return
    elif args.command == "analyze":
        obj = analyze(_read_json(args.input))
        validate_envelope(obj)
        if args.output:
            _write_json(args.output, obj)
            print(f"WROTE evidence dossier: {args.output}", file=sys.stderr)
            return
    elif args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("--port must be between 1024 and 65535")
        serve(args.port)
        return
    elif args.command == "mcp-test":
        from fabintel.mcp_client import configured_adapter, load_site_config
        config = load_site_config(args.config)
        if config.get("environment") != "SYNTHETIC_TEST_ONLY":
            parser.error("mcp-test accepts only SYNTHETIC_TEST_ONLY configs; company-side qualification remains manual and pending")
        adapter = configured_adapter(config, allow_synthetic_test=True)
        try:
            discovery = adapter.call("discover", {"permission_scope": "SYNTHETIC_READ"})
            sources = config.get("approved_source_ids", [])
            semantic = adapter.call("semantics", {"approved_source_ids": sources[:1],
                                                   "semantic_version": (config.get("approved_semantic_versions") or [None])[0]})
            relationship = adapter.call("relationships", {"typed_entity_ids": sources[:2], "time_window": {"scope": "SYNTHETIC_TEST"}})
            bounded = adapter.call("read_bounded", {"approved_plan": {"source_ids": sources[:1], "synthetic_rows": [{"unit_id": "SYNTHETIC-TEST-ROW"}]},
                "permission_context": {"scope": "SYNTHETIC_READ"}, "limits": {"max_rows": 1, "read_only": True}})
            canceled = adapter.call("cancel", {"operation_id": "SYN-OP-STOPPED"})
            audit = adapter.call("audit", {"operation_id": "SYN-OP-1"})
            obj = {"status": "SYNTHETIC_TRANSPORT_PASS", "internal_qualification": "PENDING_INTERNAL",
                   "protocol_version": adapter.client.negotiated_version, "discovered_tool_count": len(adapter.client.tools),
                   "operations": {"discover": bool(discovery.get("tool_versions")), "semantics": bool(semantic.get("approval")),
                                  "relationships": bool(relationship.get("approved")), "read_bounded": len(bounded.get("typed_rows", [])) == 1,
                                  "cancel": canceled.get("confirmed_stopped") is True, "audit": len(audit.get("query_hash", "")) == 64},
                   "scope": "synthetic MCP server and synthetic semantic mappings only; no company endpoint or data was contacted"}
        finally:
            adapter.client.close()
        if not all(obj["operations"].values()):
            obj["status"] = "SYNTHETIC_TRANSPORT_FAIL"
    elif args.command == "site-mcp-qualify":
        from fabintel.mcp_client import load_site_config
        from qualification.site_mcp_qualification import qualify
        config = load_site_config(args.config)
        obj = qualify(config, site_approval_reference=args.site_approval_reference)
        if args.output:
            _write_json(args.output, obj)
            print(f"WROTE local internal qualification report: {args.output}", file=sys.stderr)
            return 0 if obj["status"] == "SITE_TESTS_COMPLETED_PENDING_SIGNOFF" else 1
    else:
        data = _read_json(BASE / "fixtures" / "case_positive.json")
        obj = analyze(data)
        validate_envelope(obj)
    print(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False))
    if args.command == "mcp-test":
        return 0 if obj.get("status") == "SYNTHETIC_TRANSPORT_PASS" else 1
    if args.command == "site-mcp-qualify":
        return 0 if obj.get("status") == "SITE_TESTS_COMPLETED_PENDING_SIGNOFF" else 1
    return 0


if __name__ == "__main__":
    main()
