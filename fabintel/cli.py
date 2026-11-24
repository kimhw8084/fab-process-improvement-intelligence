"""Offline P4 command line; internal qualification never connects to a service."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fabintel.catalog import synthetic_catalog
from fabintel.contracts import validate_envelope
from fabintel.project import analyze, ENGINE_VERSION
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
                                     description="Local, deterministic FAB process-improvement analysis with an offline-first workbench.")
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
    web = commands.add_parser("serve", help="start the standalone offline P4 workbench on loopback only")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--mcp-config", help="load a site-owned MCP configuration; no connection is opened until an engineer starts an acquisition")
    web.add_argument("--allow-synthetic-mcp-test", action="store_true", help="explicitly allow an enabled SYNTHETIC_TEST_ONLY profile")
    mcp_test = commands.add_parser("mcp-test", help="exercise configured MCP transports only against an explicit synthetic test config")
    mcp_test.add_argument("--config", default=str(BASE / "requirements" / "synthetic-mcp-mapping.v1.json"))
    site_test = commands.add_parser("site-mcp-qualify", help="run site-owned MCP checks after explicit company authorization")
    site_test.add_argument("--config", required=True)
    site_test.add_argument("--site-approval-reference", required=True)
    site_test.add_argument("--authorized-site-test", action="store_true", required=True,
                           help="explicitly confirms that the operator has approval for this read-only site test")
    site_test.add_argument("--output", default="", help="write the local qualification report to this file")
    onboard = commands.add_parser("mcp-onboard", help="discover a site MCP and produce deterministic, unapproved source-role and schema review")
    onboard.add_argument("--config", required=True, help="site-owned MCP config; source semantics and tool mappings must be supplied by the site")
    onboard.add_argument("--output", default="", help="write the local review report to this file")
    onboard.add_argument("--draft-config-output", default="", help="write a separate PENDING_INTERNAL config copy with deterministic source-role proposals applied; never overwrite")
    onboard.add_argument("--site-approval-reference", default="", help="must exactly match the authorized reference in an internal config")
    onboard.add_argument("--authorized-site-test", action="store_true", help="explicitly confirms approval for this read-only discovery/semantic review")
    onboard.add_argument("--synthetic-test", action="store_true", help="explicitly allow SYNTHETIC_TEST_ONLY test configuration")
    config_check = commands.add_parser("mcp-config-validate", help="validate a site MCP config locally without opening a connection")
    config_check.add_argument("--config", required=True)
    config_check.add_argument("--output", default="")
    args = parser.parse_args()

    if args.command == "doctor":
        obj = {"state": "CANDIDATE", "external_transfer_ready": False, "internal_state": "PENDING_INTERNAL",
               "product_id": "p4", "engine_version": ENGINE_VERSION,
               "dependencies": {"scientific_core": "Python standard library only",
                                "mcp_adapter": "optional pinned SDK extra; macOS ARM64 CPython 3.11 candidate only",
                                "ui": "P4 standalone local HTML/CSS/JavaScript; no external host dependency"},
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
        mcp_config = None
        if args.mcp_config:
            from fabintel.mcp_client import load_site_config
            mcp_config = load_site_config(args.mcp_config)
        if args.allow_synthetic_mcp_test and (not mcp_config or mcp_config.get("environment") != "SYNTHETIC_TEST_ONLY"):
            parser.error("--allow-synthetic-mcp-test requires an explicit SYNTHETIC_TEST_ONLY --mcp-config")
        serve(args.port, mcp_config=mcp_config,
              allow_synthetic_mcp_test=args.allow_synthetic_mcp_test)
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
    elif args.command == "mcp-onboard":
        from fabintel.mcp_client import configured_adapter, load_site_config
        from fabintel.site_config import validate_site_config
        from fabintel.onboarding import inspect_onboarding
        config = load_site_config(args.config)
        structural = validate_site_config(config)
        if not structural["p4_workflow_ready"]:
            obj = {"status": "CONFIGURATION_REPAIR_REQUIRED", "configuration_validation": structural,
                   "network_requests": 0, "authority": "No source mappings or approvals were created."}
            if args.output:
                _write_json(args.output, obj)
                print(f"WROTE configuration diagnostics: {args.output}", file=sys.stderr)
            else:
                print(json.dumps(obj, indent=2, sort_keys=True))
            return 2
        synthetic = config.get("environment") == "SYNTHETIC_TEST_ONLY"
        internal = config.get("environment") == "INTERNAL_APPROVED_ONLY"
        if synthetic and not args.synthetic_test:
            parser.error("synthetic onboarding requires explicit --synthetic-test")
        if internal and (not args.authorized_site_test or
                args.site_approval_reference != config.get("site_approval_reference")):
            parser.error("internal onboarding requires explicit --authorized-site-test and an exact approved reference match")
        if not (synthetic or internal):
            parser.error("onboarding accepts only explicit synthetic-test or internal-approved configurations")
        adapter = None
        try:
            adapter = configured_adapter(config, allow_synthetic_test=synthetic,
                                         authorized_site_test=internal and config.get("qualification_status") != "QUALIFIED_INTERNAL")
            obj = inspect_onboarding(adapter, config)
        except Exception as exc:
            obj = {"status": "CONNECTION_OR_SCHEMA_FAILURE", "environment": config.get("environment"),
                   "failure_type": type(exc).__name__, "reason": str(exc),
                   "authority": "No source mappings or approvals were created; repair the site configuration or server and retry."}
        finally:
            if adapter is not None:
                adapter.client.close()
        if (args.draft_config_output and obj.get("status") == "REVIEW_REQUIRED"
                and isinstance(obj.get("proposed_normalization"), dict)):
            draft_path = Path(args.draft_config_output)
            config_path = Path(args.config)
            if draft_path.resolve() == config_path.resolve():
                obj["draft_config"] = {"status": "NOT_WRITTEN_SOURCE_PATH", "path": str(draft_path)}
            elif draft_path.exists():
                obj["draft_config"] = {"status": "NOT_WRITTEN_ALREADY_EXISTS", "path": str(draft_path)}
            else:
                draft = json.loads(json.dumps(config))
                draft["p4_profile"]["normalization"] = obj["proposed_normalization"]
                transport = draft.get("transport", {})
                cwd = transport.get("cwd") if isinstance(transport, dict) else None
                if isinstance(cwd, str) and cwd and not Path(cwd).is_absolute() and config.get("_config_dir"):
                    transport["cwd"] = str((Path(config["_config_dir"]) / cwd).resolve())
                draft.pop("_config_dir", None)
                _write_json(draft_path, draft)
                obj["draft_config"] = {"status": "UNAPPROVED_REVIEW_COPY_WRITTEN", "path": str(draft_path),
                    "authorization": "none; site-owner review and approval remain required"}
        if args.output:
            _write_json(args.output, obj)
            print(f"WROTE unapproved onboarding review: {args.output}", file=sys.stderr)
            return 0 if obj.get("status") == "REVIEW_REQUIRED" else 1
    elif args.command == "mcp-config-validate":
        from fabintel.mcp_client import load_site_config
        from fabintel.site_config import validate_site_config
        obj = validate_site_config(load_site_config(args.config))
        if args.output:
            _write_json(args.output, obj)
            print(f"WROTE local config validation: {args.output}", file=sys.stderr)
            return 0 if not obj["errors"] else 2
    else:
        data = _read_json(BASE / "fixtures" / "case_positive.json")
        obj = analyze(data)
        validate_envelope(obj)
    print(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False))
    if args.command == "mcp-test":
        return 0 if obj.get("status") == "SYNTHETIC_TRANSPORT_PASS" else 1
    if args.command == "site-mcp-qualify":
        return 0 if obj.get("status") == "SITE_TESTS_COMPLETED_PENDING_SIGNOFF" else 1
    if args.command == "mcp-config-validate":
        return 0 if not obj["errors"] else 2
    if args.command == "mcp-onboard":
        return 0 if obj.get("status") == "REVIEW_REQUIRED" else 1
    return 0


if __name__ == "__main__":
    main()
