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
    web = commands.add_parser("serve", help="serve the offline engineer UI on loopback only")
    web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command == "doctor":
        obj = {"state": "CANDIDATE", "external_transfer_ready": False, "internal_state": "PENDING_INTERNAL",
               "product_id": "p4", "engine_version": "1.0.0", "dependencies": "Python standard library only",
               "network": "none in CLI; UI binds to 127.0.0.1", "note": "See release/GATE_REPORT.json for evidence and remaining gates."}
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
    else:
        data = _read_json(BASE / "fixtures" / "case_positive.json")
        obj = analyze(data)
        validate_envelope(obj)
    print(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
