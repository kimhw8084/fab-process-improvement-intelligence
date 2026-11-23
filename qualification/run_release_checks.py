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


def archive_qualification_pass(evaluated_commit):
    release = ROOT / "release"
    archive = release / "FAB_INTELLIGENCE_P4_CANDIDATE.zip"
    if not archive.is_file():
        return False
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        sidecar = (release / "TRANSFER_BUNDLE.sha256").read_text(encoding="utf-8").strip()
        reproducibility = json.loads((release / "BUILD_REPRODUCIBILITY.json").read_text(encoding="utf-8"))
        offline = json.loads((release / "OFFLINE_QUALIFICATION.json").read_text(encoding="utf-8"))
        manifest = {}
        for line in (release / "SOURCE_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            if line.strip():
                expected, relative = line.split("  ", 1)
                manifest[relative] = expected
        from qualification.build_transfer_bundle import source_files
        workspace = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in source_files()}
    except (OSError, json.JSONDecodeError):
        return False
    return (manifest == workspace
            and sidecar == f"{digest}  {archive.name}"
            and reproducibility.get("status") == "PASS"
            and reproducibility.get("source_commit") == evaluated_commit
            and all(value == digest for value in reproducibility.get("sha256_by_clean_build", []))
            and reproducibility.get("workspace_archive_sha256") == digest
            and reproducibility.get("workspace_archive_matches_clean_build") is True
            and reproducibility.get("source_manifest_matches_clean_commit") is True
            and reproducibility.get("sidecar_matches_workspace_archive") is True
            and offline.get("result") == "PASS"
            and offline.get("archive_sha256") == digest
            and offline.get("archive_checksum_verified") is True
            and offline.get("source_files_verified", 0) > 0
            and offline.get("network_policy") == "must be enforced by caller OS sandbox"
            and offline.get("network_policy_probe", {}).get("status") == "DENIED")


def main():
    commit, _ = run(["git", "rev-parse", "HEAD"])
    evaluated_commit = commit.stdout.strip() if commit.returncode == 0 else "UNAVAILABLE"
    tests, test_log = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    (ROOT / "release" / "TEST_LOG.txt").write_text(test_log, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", test_log)
    skipped = re.search(r"\(skipped=(\d+)\)", test_log)
    skipped_tests = int(skipped.group(1)) if skipped else 0
    test_pass = tests.returncode == 0 and "OK" in test_log and match is not None and skipped_tests == 0
    test_summary = {"command": "python -m unittest discover -s tests -v", "return_code": tests.returncode,
                    "tests_run": int(match.group(1)) if match else None,
                    "tests_skipped": skipped_tests,
                    "duration_seconds": float(match.group(2)) if match else None,
                    "status": "PASS" if test_pass else "FAIL",
                    "optional_qualification_dependencies": "qualification/benchmark-requirements.txt",
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

    mcp, mcp_output = run([sys.executable, "-m", "fabintel", "mcp-test", "--config",
                           "requirements/synthetic-mcp-mapping.v1.json"])
    try:
        mcp_result = json.loads(mcp_output) if mcp.returncode == 0 else {"status": "FAIL"}
    except json.JSONDecodeError:
        mcp_result = {"status": "FAIL", "error": "synthetic MCP CLI output was not JSON"}
    mcp_pass = mcp.returncode == 0 and mcp_result.get("status") == "SYNTHETIC_TRANSPORT_PASS"

    benchmark_path = ROOT / "release" / "D04_OSS_COMPARISON.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.exists() else {}
    d_opt = benchmark.get("d_optimal", {}).get("results", {})
    lhs = benchmark.get("latin_hypercube", {}).get("results", {})
    sequential = benchmark.get("sequential_next_best", {})
    d04_pass = (
        benchmark.get("status") == "PASS"
        and d_opt.get("p4_greedy", {}).get("D_efficiency_percent", 0) >= 99.99
        and lhs.get("p4_basic", {}).get("stratified_seed_fraction") == 1.0
        and sequential.get("results_by_function", {}).get("multimodal", {}).get("p4", {}).get("accepted_fraction") == 0.0
    )
    benchmark_result = {"status": "PASS" if d04_pass else "FAIL",
                        "evidence": "release/D04_OSS_COMPARISON.json",
                        "runtime_dependencies_added": False,
                        "d_optimal_efficiency_percent": d_opt.get("p4_greedy", {}).get("D_efficiency_percent"),
                        "p4_latin_hypercube_all_seeds_stratified": lhs.get("p4_basic", {}).get("stratified_seed_fraction"),
                        "multimodal_next_best_acceptance_fraction": sequential.get("results_by_function", {}).get("multimodal", {}).get("p4", {}).get("accepted_fraction")}
    performance_path = ROOT / "release" / "BENCHMARK_REPORT.json"
    performance = json.loads(performance_path.read_text(encoding="utf-8")) if performance_path.exists() else {}
    performance_source_commit = performance.get("source_commit", "")
    source_is_ancestor = bool(performance_source_commit) and run(
        ["git", "merge-base", "--is-ancestor", performance_source_commit, evaluated_commit])[0].returncode == 0
    changed_since_performance = run(
        ["git", "diff", "--name-only", f"{performance_source_commit}..{evaluated_commit}"])[0].stdout.splitlines()
    product_paths_unchanged = not any(path.startswith(("fabintel/", "ui/", "products/", "contracts/",
                                                       "tests/", "fixtures/", "requirements/"))
                                      for path in changed_since_performance)
    workflow_perf = performance.get("result_checks", {}).get("integrated_full_workflow_demo_540_rows", {})
    scaling = performance.get("result_checks", {})
    performance_pass = (
        performance.get("benchmark_version") == "2.0.0"
        and source_is_ancestor
        and product_paths_unchanged
        and workflow_perf.get("status") == "VALID"
        and workflow_perf.get("observations") == 540
        and workflow_perf.get("independent_lots") == 60
        and all(scaling.get(f"single_metric_sensitivity_{n}_rows", {}).get("D01_status") == "VALID"
                for n in (18, 1000, 5000))
        and performance.get("oss_reference", {}).get("version") == "0.15.0"
        and performance.get("oss_reference", {}).get("maximum_absolute_coefficient_difference", float("inf")) <= 1e-9
    )
    performance_result = {"status": "PASS" if performance_pass else "FAIL",
                          "evidence": "release/BENCHMARK_REPORT.json",
                          "source_commit": performance_source_commit,
                          "package_source_snapshot": evaluated_commit,
                          "product_code_unchanged_after_benchmark": product_paths_unchanged,
                          "integrated_demo_observations": workflow_perf.get("observations"),
                          "integrated_demo_independent_lots": workflow_perf.get("independent_lots"),
                          "maximum_statsmodels_ols_coefficient_difference": performance.get("oss_reference", {}).get("maximum_absolute_coefficient_difference")}
    audit_path = ROOT / "release" / "DEPENDENCY_AUDIT.json"
    dependency_audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    dependency_audit_pass = dependency_audit.get("result") == "PASS" and dependency_audit.get("vulnerabilities_found") == 0
    dependency_audit_result = {"status": "PASS" if dependency_audit_pass else "FAIL",
                               "evidence": "release/DEPENDENCY_AUDIT.json",
                               "scope": "optional benchmark dependency tree; product runtime has no third-party Python packages",
                               "vulnerabilities_found": dependency_audit.get("vulnerabilities_found")}

    contrast_run, contrast_log = run([sys.executable, "qualification/accessibility_contrast_check.py"])
    contrast_report = json.loads((ROOT / "release" / "UI_CONTRAST_CHECK.json").read_text(encoding="utf-8"))
    contrast_pass = contrast_run.returncode == 0 and contrast_report.get("status") == "PASS"
    contrast_result = {"status": "PASS" if contrast_pass else "FAIL",
                       "evidence": "release/UI_CONTRAST_CHECK.json",
                       "pairs_checked": contrast_report.get("pairs_checked"),
                       "scope": contrast_report.get("scope")}

    security_path = ROOT / "release" / "SOURCE_SECURITY_SCAN.json"
    security_report = json.loads(security_path.read_text(encoding="utf-8")) if security_path.exists() else {}
    security_review = security_report.get("review", {})
    security_findings = security_report.get("results", [])
    security_pass = (
        security_review.get("tool") == "Bandit"
        and security_review.get("tool_version") == "1.9.4"
        and security_review.get("limited_scan_result") == "PASS_LIMITED_SCOPE"
        and security_review.get("independent_human_source_review") == "PENDING"
        and security_review.get("license_and_ownership_review") == "PENDING"
        and security_review.get("finding_count") == len(security_findings) == 8
        and security_review.get("high_or_medium_findings") == 0
        and security_review.get("finding_dispositions_cover_all_reported_findings") is True
        and all(item.get("issue_severity") == "LOW" and item.get("test_id") in {"B311", "B404", "B603", "B110"}
                for item in security_findings)
    )
    source_security_result = {"status": "PASS_LIMITED_SCOPE" if security_pass else "FAIL",
                              "evidence": "release/SOURCE_SECURITY_SCAN.json",
                              "tool": security_review.get("tool"),
                              "version": security_review.get("tool_version"),
                              "finding_count": len(security_findings),
                              "high_or_medium_findings": security_review.get("high_or_medium_findings"),
                              "independent_human_review": "PENDING"}

    qualification_pass = (test_pass and demo_result["status"] == "PASS" and schema_status == "PASS"
                          and frozen_pass and critical_pass and mcp_pass and d04_pass and performance_pass
                          and contrast_pass and security_pass)
    results = {"state": "PASS" if qualification_pass else "FAIL",
               "unit_tests": test_summary, "integrated_demo": demo_result,
               "synthetic_mcp_external_mock": {"status": "PASS" if mcp_pass else "FAIL",
                                                "evidence": "requirements/synthetic-mcp-mapping.v1.json",
                                                "result": mcp_result},
               "d04_oss_benchmark": benchmark_result,
               "scientific_performance_benchmark": performance_result,
               "dependency_audit": dependency_audit_result,
               "ui_accessibility_contrast": contrast_result,
               "source_security_scan": source_security_result,
               "schema_validation": {"status": schema_status, "evidence": "release/SCHEMA_VALIDATION.json"},
               "frozen_shared_contracts": {"status": "PASS" if frozen_pass else "FAIL", "fingerprints_match_starter": contract_hash},
               "critical_cases": {"status": "PASS" if critical_pass else "FAIL", "cases": cases,
                                  "missing_test_names": missing_case_tests, "missing_case_evidence": missing_case_evidence}}
    (ROOT / "release" / "TEST_RESULTS.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "state": "CANDIDATE",
        "product": "p4",
        "evaluated_commit": evaluated_commit,
        "product_source_commit": performance_source_commit,
        "build_host": {"os": platform.platform(), "architecture": platform.machine(), "python": sys.version},
        "unit_tests": test_summary,
        "integrated_demo": demo_result,
        "synthetic_mcp_external_mock": {"status": "PASS" if mcp_pass else "FAIL",
                                         "evidence": ["fabintel/mcp_client.py", "fabintel/mock_mcp_server.py",
                                                      "requirements/synthetic-mcp-mapping.v1.json"],
                                         "result": mcp_result},
        "d04_oss_benchmark": benchmark_result,
        "scientific_performance_benchmark": performance_result,
        "dependency_audit": dependency_audit_result,
        "ui_accessibility_contrast": contrast_result,
        "source_security_scan": source_security_result,
        "schema_validation": {"status": schema_status, "command_return_code": schema_run.returncode,
                              "evidence": "release/SCHEMA_VALIDATION.json"},
        "frozen_shared_contracts": {"status": "PASS" if frozen_pass else "FAIL", "fingerprints_match_starter": contract_hash},
        "gates": {
            "E01": {"status": "PASS" if demo_result["status"] == "PASS" else "FAIL", "evidence": ["release/full_workflow_demo_evidence.json", "release/TEST_LOG.txt"], "scope": "synthetic end-to-end capability flow"},
            "E02": {"status": "PASS" if critical_pass and d04_pass and performance_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "tests/test_d01_d02_independent.py", "tests/test_d03_relationships.py", "tests/test_d04_designs.py", "tests/test_d05_studies.py", "fixtures/p4_independent_oracles.json", "qualification/critical_cases.json", "release/D04_OSS_COMPARISON.json", "release/BENCHMARK_REPORT.json", "release/TEST_RESULTS.json"], "scope": "fixed numeric oracles, 100 seeded slope cases, held-out nonlinear/confounded/correlated/OOD cases, multiobjective and failed-experiment cases, invalid-assumption refusals, independent statsmodels coefficient parity, and fixed synthetic D04 OSS benchmarks"},
            "E03": {"status": "PASS" if critical_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "tests/test_offline_server.py"], "scope": "unsafe, invalid, leakage, permission, cancellation and host/origin cases"},
            "E04": {"status": "PASS" if frozen_pass and schema_status == "PASS" else "FAIL", "evidence": ["contracts/", "products/p4/investigation.v1.schema.json", "release/SCHEMA_VALIDATION.json"]},
            "E05": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "qualification/internal-capability-report.v1.schema.json"], "reason": "real authorization, approved semantics, bounded reads and source audit are unavailable externally"},
            "E06": {"status": "PASS" if mcp_pass else "FAIL", "evidence": ["release/LICENSE_SECURITY_REVIEW.md", "tests/test_mcp_transport.py", "requirements/synthetic-mcp-mapping.v1.json"], "scope": "model-off product; MCP JSON-RPC stdio and Streamable HTTP mapping exercised against synthetic mock; company tool names/permissions/source semantics remain unconfigured"},
            "E07": {"status": "PENDING_FORMAL_ACCESSIBILITY", "evidence": ["release/UI_BROWSER_ACCEPTANCE.md", "release/UI_ACCESSIBILITY_CHECK.json", "release/UI_CONTRAST_CHECK.json", "qualification/accessibility_contrast_check.py", "tests/test_offline_server.py"], "reason": "local keyboard-only task, accessible table alternatives, focus management and browser accessibility tree passed; 15 curated text/focus contrast pairs passed; screen-reader, complete formal WCAG, and approved-host reviews remain unrun"},
            "E08": {"status": "PENDING_TARGET_OS", "evidence": ["release/NO_NETWORK_QUALIFICATION.md", "qualification/offline_qualify.py"], "reason": "a local-host offline bundle run is recorded separately; the company target OS remains unknown"},
            "E09": {"status": "PENDING_LICENSE_AND_INDEPENDENT_SECURITY_REVIEW", "dependency_audit": "PASS" if dependency_audit_pass else "FAIL", "source_security_scan": source_security_result["status"], "evidence": ["release/SBOM.spdx.json", "release/DEPENDENCY_AUDIT.json", "release/SOURCE_SECURITY_SCAN.json", "release/LICENSE_SECURITY_REVIEW.md"], "reason": "the package-advisory scan is clean and Bandit found no medium/high source findings (eight low tool findings are dispositioned); independent manual/OS security review and owner/legal distribution rights remain unresolved"},
            "E10": {"status": "PASS" if archive_qualification_pass(evaluated_commit) else "PENDING_FINAL_ARCHIVE", "evidence": ["release/TRANSFER_BUNDLE.sha256", "release/BUILD_REPRODUCIBILITY.json", "release/OFFLINE_QUALIFICATION.json", "qualification/build_transfer_bundle.py"], "scope": "exact current local archive, clean-source reproducible build and fresh extracted offline runtime"} if archive_qualification_pass(evaluated_commit) else {"status": "PENDING_FINAL_ARCHIVE", "evidence": ["release/TRANSFER_BUNDLE.sha256", "release/BUILD_REPRODUCIBILITY.json", "release/OFFLINE_QUALIFICATION.json", "qualification/build_transfer_bundle.py"], "reason": "the exact current archive, clean-source reproducible build and fresh extracted offline runtime must all match"},
            "E11": {"status": "PENDING_ENGINEER_BASELINE", "evidence": ["qualification/BENCHMARK_PLAN.md", "release/BENCHMARK_REPORT.json"], "reason": "synthetic latency is measured; no eligible engineer task-time, review-burden or ROI baseline exists"},
            "E12": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "docs/INTERNAL_COMPANY_FIRST_RUN.md"], "reason": "company MCP, host, policy owner and engineer qualification require authorized site testing"}
        },
        "internal": {"state": "PENDING_INTERNAL", "unverified": ["real MCP and auth scopes", "source semantics and joins", "company target OS and approved host", "company data pilot", "engineer acceptance", "owner/legal transfer approval", "literal R01-R53 and Golden standard"]},
        "known_critical_defects": [],
        "release_blockers": ["no actual authorized MCP connector", "license ownership and distribution rights are not declared", "independent source security review not completed", "company target OS and formal UX/user baselines not supplied"]
    }
    path = ROOT / "release" / "GATE_REPORT.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "tests": test_summary, "demo": demo_result,
                      "schema_validation": schema_status, "contract_fingerprints": contract_hash,
                      "evaluated_commit": evaluated_commit,
                      "gate_report": str(path)}, indent=2, sort_keys=True))
    return 0 if results["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
