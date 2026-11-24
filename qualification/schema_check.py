"""Optional offline JSON Schema validation using a locally installed jsonschema package."""
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        print(json.dumps({"status": "SKIPPED", "reason": "jsonschema is not installed; it is not a product dependency"}, indent=2))
        return 0
    checks = [
        ("contracts/product-manifest.v1.schema.json", "product.json"),
        ("contracts/evidence.v1.schema.json", "release/full_workflow_demo_evidence.json"),
        ("products/p4/investigation.v1.schema.json", "fixtures/full_workflow_demo.json"),
        ("products/p4/relationships.v1.1.schema.json", "fixtures/relationship_contract_v1.1.json"),
        ("requirements/site-mcp-config.v1.schema.json", "requirements/synthetic-mcp-mapping.v1.json"),
        ("requirements/site-mcp-config.v1.schema.json", "requirements/company-config.template.json"),
    ]
    results = []
    for schema_rel, instance_rel in checks:
        schema_path, instance_path = ROOT / schema_rel, ROOT / instance_rel
        schema_bytes = schema_path.read_bytes()
        schema = json.loads(schema_bytes)
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(instance), key=lambda error: list(map(str, error.absolute_path)))
        results.append({"schema": schema_rel, "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                        "instance": instance_rel, "status": "PASS" if not errors else "FAIL",
                        "errors": [error.message for error in errors]})
    bridge_path = ROOT / "tests" / "fixtures" / "mcp_p4_panel_bridge.json"
    bridge_schema_path = ROOT / "contracts" / "evidence.v1.schema.json"
    bridge_schema = json.loads(bridge_schema_path.read_text(encoding="utf-8"))
    bridge_validator = Draft202012Validator(bridge_schema, format_checker=FormatChecker())
    bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    for evidence_key in ("analysis_evidence", "refusal_evidence"):
        instance = bridge[evidence_key]
        errors = sorted(bridge_validator.iter_errors(instance), key=lambda error: list(map(str, error.absolute_path)))
        results.append({"schema": "contracts/evidence.v1.schema.json",
                        "schema_sha256": hashlib.sha256(bridge_schema_path.read_bytes()).hexdigest(),
                        "instance": f"tests/fixtures/mcp_p4_panel_bridge.json#{evidence_key}",
                        "status": "PASS" if not errors else "FAIL",
                        "errors": [error.message for error in errors]})
    report = {"status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
              "validator": "python-jsonschema", "validator_version": importlib.metadata.version("jsonschema"),
              "role": "qualification-only; not a runtime dependency", "checks": results}
    output = ROOT / "release" / "SCHEMA_VALIDATION.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
