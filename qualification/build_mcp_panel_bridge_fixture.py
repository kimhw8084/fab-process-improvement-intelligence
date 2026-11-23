"""Build a reproducible synthetic MCP-to-P4-panel evidence bridge fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema

from fabintel.contracts import validate_envelope
from products.p4.mcp_workflow import run_mcp_investigation
from tests.test_mcp_transport import McpToP4WorkflowQualification


def _run(scenario: str, request: dict) -> dict:
    adapter = McpToP4WorkflowQualification._adapter(scenario)
    try:
        return run_mcp_investigation(adapter, request)
    finally:
        adapter.client.close()


def build_fixture() -> dict:
    request = McpToP4WorkflowQualification.request()
    analysis = _run("normal", request)
    refusal = _run("permission_denied", request)
    schema = json.loads((ROOT / "contracts" / "evidence.v1.schema.json").read_text(encoding="utf-8"))
    for result in (analysis, refusal):
        validate_envelope(result)
        jsonschema.validate(result, schema)

    template = request["analysis_template"]
    metrics = template["metrics"]
    metric_names = [item["name"] for item in metrics]
    metric_units = [item["unit"] for item in metrics]
    preview = {
        "status": "SYNTHETIC_ONLY",
        "permission": "Synthetic mock read only; no company source permission is configured.",
        "semantic_version": request["semantic_version"],
        "grain": analysis["sources"][0]["grain"] if analysis.get("sources") else template["grain"],
        "metric": "; ".join(metric_names),
        "unit": "; ".join(metric_units),
        "scope": "P4 synthetic MCP-to-panel qualification fixture",
        "time_window": f"{request['time_window']['start']} through {request['time_window']['end']}",
        "coverage": {"observations": len(request["approved_plan"]["synthetic_rows"]),
                     "synthetic_sources": len(request["approved_source_ids"])},
    }
    source_paths = (
        "qualification/build_mcp_panel_bridge_fixture.py",
        "products/p4/mcp_workflow.py",
        "fabintel/mcp_client.py",
        "fabintel/mock_mcp_server.py",
        "contracts/adapter-operations.v1.json",
        "contracts/evidence.v1.schema.json",
        "tests/test_mcp_transport.py",
    )
    source_fingerprint = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_paths}
    return {
        "schema": "p4-mcp-panel-bridge-fixture/v1",
        "source": "official-mcp-sdk-synthetic-mock",
        "source_fingerprint": source_fingerprint,
        "source_preview": preview,
        "analysis_evidence": analysis,
        "refusal_evidence": refusal,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/mcp_p4_panel_bridge.json")
    args = parser.parse_args()
    fixture = build_fixture()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(fixture, indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(output),
                      "sha256": hashlib.sha256(payload.encode()).hexdigest(),
                      "analysis_status": fixture["analysis_evidence"]["status"],
                      "refusal_status": fixture["refusal_evidence"]["status"],
                      "capability_artifact_types": [artifact.get("type") for artifact in fixture["analysis_evidence"].get("artifacts", [])]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
