"""Run reproducible local qualification checks and emit honest machine-readable gate states."""
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(command):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return result, (result.stdout or "") + (result.stderr or "")


def baseline_contracts_unchanged():
    manifest = ROOT / "release" / "BOOTSTRAP_MANIFEST.sha256"
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            checksum, rel = line.split("  ", 1)
            expected[rel] = checksum
    names = ("contracts/SHARED_ARCHITECTURE.md", "contracts/adapter-operations.v1.json",
             "contracts/evidence.v1.schema.json", "contracts/product-manifest.v1.schema.json")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected.get(name) for name in names}


def main():
    tests, test_log = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    (ROOT / "release" / "TEST_LOG.txt").write_text(test_log, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", test_log)
    test_pass = tests.returncode == 0 and "OK" in test_log and match is not None
    test_summary = {"command": "python -m unittest discover -s tests -v", "return_code": tests.returncode,
                    "tests_run": int(match.group(1)) if match else None,
                    "duration_seconds": float(match.group(2)) if match else None,
                    "status": "PASS" if test_pass else "FAIL",
                    "log": "release/TEST_LOG.txt"}

    demo, demo_output = run([sys.executable, "-m", "fabintel", "analyze", "--input",
                             "fixtures/full_workflow_demo.json", "--output", "release/full_workflow_demo_evidence.json"])
    demo_result = {"command": "python -m fabintel analyze --input fixtures/full_workflow_demo.json --output release/full_workflow_demo_evidence.json",
                   "return_code": demo.returncode, "status": "FAIL"}
    if demo.returncode == 0:
        evidence = json.loads((ROOT / "release" / "full_workflow_demo_evidence.json").read_text(encoding="utf-8"))
        dossier = evidence["artifacts"][0]
        complete = all(name in dossier for name in ("D01_sensitivity", "D02_observed_process_window", "D02_robust_observed_region",
                                                      "D03_tradeoffs", "D04_experiment_proposal", "D05_effectiveness"))
        demo_result.update({"status": "PASS" if evidence["status"] == "VALID" and complete else "FAIL",
                            "result_status": evidence["status"], "mode": evidence["mode"],
                            "capabilities": ["D01", "D02", "D03", "D04", "D05"] if complete else [],
                            "evidence": "release/full_workflow_demo_evidence.json"})

    schema_run, schema_log = run([sys.executable, "qualification/schema_check.py"])
    schema_path = ROOT / "release" / "SCHEMA_VALIDATION.json"
    schema_status = json.loads(schema_path.read_text(encoding="utf-8"))["status"] if schema_path.exists() else "NOT_RUN"
    contract_hash = baseline_contracts_unchanged()
    frozen_pass = all(contract_hash.values())
    missing_case_tests = [f"P4-{number:02d}" for number in range(1, 13)
                          if f"test_p4_{number:02d}_" not in (ROOT / "tests" / "test_p4_scientific.py").read_text(encoding="utf-8")]
    cases = json.loads((ROOT / "qualification" / "critical_cases.json").read_text(encoding="utf-8"))
    missing_case_evidence = [case["id"] for case in cases
                             if not case.get("implemented_and_tested") or not case.get("test")]
    critical_pass = not missing_case_tests and not missing_case_evidence and test_pass

    results = {"state": "PASS" if test_pass and demo_result["status"] == "PASS" and schema_status == "PASS" and frozen_pass and critical_pass else "FAIL",
               "unit_tests": test_summary, "integrated_demo": demo_result,
               "schema_validation": {"status": schema_status, "evidence": "release/SCHEMA_VALIDATION.json"},
               "frozen_shared_contracts": {"status": "PASS" if frozen_pass else "FAIL", "fingerprints_match_starter": contract_hash},
               "critical_cases": {"status": "PASS" if critical_pass else "FAIL", "cases": cases,
                                  "missing_test_names": missing_case_tests, "missing_case_evidence": missing_case_evidence}}
    (ROOT / "release" / "TEST_RESULTS.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "state": "CANDIDATE",
        "product": "p4",
        "evaluated_commit": None,
        "build_host": {"os": platform.platform(), "architecture": platform.machine(), "python": sys.version},
        "unit_tests": test_summary,
        "integrated_demo": demo_result,
        "schema_validation": {"status": schema_status, "command_return_code": schema_run.returncode,
                              "evidence": "release/SCHEMA_VALIDATION.json"},
        "frozen_shared_contracts": {"status": "PASS" if frozen_pass else "FAIL", "fingerprints_match_starter": contract_hash},
        "gates": {
            "E01": {"status": "PASS" if demo_result["status"] == "PASS" else "FAIL", "evidence": ["release/full_workflow_demo_evidence.json", "release/TEST_LOG.txt"], "scope": "synthetic end-to-end capability flow"},
            "E02": {"status": "PASS" if critical_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "fixtures/p4_independent_oracles.json", "qualification/critical_cases.json", "release/TEST_RESULTS.json"], "scope": "12 fixed challenge cases and 100 seeded numeric cases"},
            "E03": {"status": "PASS" if critical_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "tests/test_offline_server.py"], "scope": "unsafe, invalid, leakage, permission, cancellation and host/origin cases"},
            "E04": {"status": "PASS" if frozen_pass and schema_status == "PASS" else "FAIL", "evidence": ["contracts/", "products/p4/investigation.v1.schema.json", "release/SCHEMA_VALIDATION.json"]},
            "E05": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "qualification/internal-capability-report.v1.schema.json"], "reason": "real authorization, approved semantics, bounded reads and source audit are unavailable externally"},
            "E06": {"status": "PASS", "evidence": ["release/LICENSE_SECURITY_REVIEW.md", "tests/test_p4_scientific.py"], "scope": "deterministic model-off product; no LLM or external prompt/data path"},
            "E07": {"status": "PENDING_FORMAL_ACCESSIBILITY", "evidence": ["release/UI_BROWSER_ACCEPTANCE.md", "tests/test_offline_server.py"], "reason": "local browser flow passed; keyboard-only, screen-reader and approved-host accessibility review remain unrun"},
            "E08": {"status": "PENDING_TARGET_OS", "evidence": ["release/NO_NETWORK_QUALIFICATION.md", "qualification/offline_qualify.py"], "reason": "the final archive must be extracted and tested under network deny; company target OS is unknown"},
            "E09": {"status": "PENDING_LICENSE_AND_VULNERABILITY_REVIEW", "evidence": ["release/SBOM.spdx.json", "release/LICENSE_SECURITY_REVIEW.md"], "reason": "project distribution license is undeclared and no CVE scanner/database was available"},
            "E10": {"status": "PENDING_FINAL_ARCHIVE", "evidence": ["qualification/build_transfer_bundle.py", "release/RUNBOOK_ROLLBACK_KILL_SWITCH.md"], "reason": "the final archive/checksum/fresh-extract run is performed after this report"},
            "E11": {"status": "PENDING_ENGINEER_BASELINE", "evidence": ["qualification/BENCHMARK_PLAN.md", "release/BENCHMARK_REPORT.json"], "reason": "synthetic latency is measured; no eligible engineer task-time, review-burden or ROI baseline exists"},
            "E12": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "docs/INTERNAL_COMPANY_FIRST_RUN.md"], "reason": "company MCP, host, policy owner and engineer qualification require authorized site testing"}
        },
        "internal": {"state": "PENDING_INTERNAL", "unverified": ["real MCP and auth scopes", "source semantics and joins", "company target OS and approved host", "company data pilot", "engineer acceptance", "owner/legal transfer approval", "literal R01-R53 and Golden standard"]},
        "known_critical_defects": [],
        "release_blockers": ["no actual authorized MCP connector", "license ownership and distribution rights are not declared", "vulnerability scan unavailable", "company target OS and formal UX/user baselines not supplied"]
    }
    path = ROOT / "release" / "GATE_REPORT.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "tests": test_summary, "demo": demo_result,
                      "schema_validation": schema_status, "contract_fingerprints": contract_hash,
                      "gate_report": str(path)}, indent=2, sort_keys=True))
    return 0 if results["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
