"""Transfer-bundle first-run report; does not contact any internal or external service."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability-report", help="local JSON snapshot emitted by an authorized internal bridge")
    parser.add_argument("--output", help="optional local path for the machine-readable report")
    args = parser.parse_args()
    report = {"product_id": "p4", "status": "PENDING_INTERNAL", "network_requests": 0,
              "source_state": "CANDIDATE", "contract_version": "1.0.0", "static_checks": {},
              "company_qualification": "PENDING_INTERNAL",
              "unverified": ["real MCP identity and authorization", "approved source semantics and temporal joins",
                             "read-only bounded queries and audit/cancel", "target OS and approved UI host",
                             "approved model configuration", "engineer and security-owner acceptance"]}
    try:
        product = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
        report["static_checks"]["product_manifest"] = product.get("product_id") == "p4" and product.get("contract_version") == "1.0.0"
        for name in ("evidence.v1.schema.json", "product-manifest.v1.schema.json", "adapter-operations.v1.json"):
            value = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
            report["static_checks"][name] = bool(value)
        report["static_checks"]["offline_dependencies"] = product.get("dependencies") == ["Python >=3.10 standard library only; no third-party runtime packages"]
        if args.capability_report:
            from fabintel.qualification import inspect_capability_report
            path = Path(args.capability_report)
            if path.stat().st_size > 256 * 1024:
                raise ValueError("capability report exceeds 256 KiB")
            compat = inspect_capability_report(json.loads(path.read_text(encoding="utf-8")))
            report["logical_compatibility"] = compat
        else:
            report["logical_compatibility"] = {"static_compatibility": "NOT_PROVIDED",
                                                "note": "Obtain an authorized internal capability snapshot; no endpoint or tool name is guessed here."}
        gates = json.loads((ROOT / "release" / "GATE_REPORT.json").read_text(encoding="utf-8"))
        report["release_state"] = gates.get("state", "CANDIDATE")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["status"] = "ERROR"
        report["error"] = str(exc)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if report["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
