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
from qualification.benchmark import product_source_fingerprint  # noqa: E402
from qualification.workflow_qualification import analysis_result_is_qualified, performance_record_is_qualified  # noqa: E402


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


def benchmark_matches_product_sources(performance):
    current_files, current_manifest = product_source_fingerprint()
    return (performance.get("product_source_sha256") == current_files
            and performance.get("product_source_manifest_sha256") == current_manifest)


def benchmark_workflow_is_qualified(performance):
    return performance_record_is_qualified(performance)


def disposable_snapshot_fingerprint_matches(snapshot):
    hashes = snapshot.get("file_sha256")
    if not isinstance(hashes, dict) or not hashes or snapshot.get("files") != len(hashes):
        return False
    if any(not isinstance(name, str) or not name or not isinstance(digest, str)
           or re.fullmatch(r"[0-9a-f]{64}", digest) is None for name, digest in hashes.items()):
        return False
    manifest = "\n".join(f"{digest}  {name}" for name, digest in sorted(hashes.items())) + "\n"
    digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return snapshot.get("manifest_sha256") == digest and snapshot.get("sha256") == digest


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
        source_build = json.loads((release / "SOURCE_BUILD.json").read_text(encoding="utf-8"))
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
            and source_build.get("source_commit") == evaluated_commit
            and source_build.get("source_file_count") == len(manifest)
            and source_build.get("source_manifest_sha256") == hashlib.sha256((release / "SOURCE_MANIFEST.sha256").read_bytes()).hexdigest()
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
        required_artifacts = ("D01_sensitivity", "D02_observed_process_window", "D02_robust_observed_region",
                              "D02_supported_region", "D03_tradeoffs", "D04_experiment_proposal", "D05_effectiveness")
        complete = all(name in dossier for name in required_artifacts)
        evidence_outputs_qualified, capability_statuses = analysis_result_is_qualified(evidence)
        supported_window = dossier.get("D02_supported_region", {})
        calibration = supported_window.get("calibration", {})
        d02_ok = (supported_window.get("status") == "VALID"
                  and supported_window.get("candidate_count", 0) > 0
                  and calibration.get("calibration_unit_count", 0) >= 19
                  and calibration.get("coverage_guarantee", "").startswith("none;"))
        workflow_pass = complete and evidence_outputs_qualified and d02_ok
        demo_result.update({"status": "PASS" if workflow_pass else "FAIL",
                            "result_status": evidence["status"], "mode": evidence["mode"],
                            "capability_statuses": capability_statuses,
                            "qualification_scope": "D01-D05 execution and evidence assembly; reported PARTIAL/LIMITED_SCOPE states remain scientific limitations, not workflow errors",
                            "capabilities": ["D01", "D02", "D03", "D04", "D05"] if complete else [],
                            "D02_empirical_calibration": {"status": supported_window.get("status"),
                                "candidate_count": supported_window.get("candidate_count"),
                                "grid_cells": len(supported_window.get("grid", [])),
                                "training_units": calibration.get("training_unit_count"),
                                "calibration_units": calibration.get("calibration_unit_count"),
                                "coverage_guarantee": calibration.get("coverage_guarantee"),
                                "qualification": "PASS" if d02_ok else "FAIL"},
                            "evidence": "release/full_workflow_demo_evidence.json"})
        if not workflow_pass:
            demo_result["status"] = "FAIL"

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

    d01_imbalance_path = ROOT / "qualification" / "results" / "D01_CLUSTER_IMBALANCE_BENCHMARK.json"
    d01_imbalance_run, _ = run([sys.executable, "-m", "qualification.benchmark_d01_cluster_imbalance"])
    d01_imbalance = json.loads(d01_imbalance_path.read_text(encoding="utf-8")) if d01_imbalance_path.exists() else {}
    d01_imbalance_scenarios = d01_imbalance.get("metrics", {})
    d01_balanced = d01_imbalance_scenarios.get("balanced", {})
    d01_uneven = d01_imbalance_scenarios.get("one_dominant_cluster", {})
    d01_source_hash = hashlib.sha256((ROOT / "products" / "p4" / "regression.py").read_bytes()).hexdigest()
    d01_script_hash = hashlib.sha256((ROOT / "qualification" / "benchmark_d01_cluster_imbalance.py").read_bytes()).hexdigest()
    d01_imbalance_pass = (
        d01_imbalance_run.returncode == 0
        and d01_imbalance.get("schema") == "p4-d01-cluster-imbalance-benchmark/v1"
        and d01_imbalance.get("qualification") == "PASS"
        and d01_imbalance.get("trials_per_scenario", 0) >= 1000
        and d01_imbalance.get("product_source_sha256") == d01_source_hash
        and d01_imbalance.get("benchmark_script_sha256") == d01_script_hash
        and d01_balanced.get("product", {}).get("abstained_trials") == 0
        and d01_balanced.get("product", {}).get("coverage_wilson95", [1, 0])[0] <= 0.95
        <= d01_balanced.get("product", {}).get("coverage_wilson95", [1, 0])[1]
        and d01_uneven.get("product", {}).get("abstained_trials") == d01_imbalance.get("trials_per_scenario")
        and d01_uneven.get("statsmodels_count_only_cluster_reference", {}).get("false_positive_rate", 0) >= 0.20
    )
    d01_imbalance_result = {
        "status": "PASS" if d01_imbalance_pass else "FAIL",
        "evidence": "qualification/results/D01_CLUSTER_IMBALANCE_BENCHMARK.json",
        "source_hash_matches": d01_imbalance.get("product_source_sha256") == d01_source_hash,
        "trials_per_scenario": d01_imbalance.get("trials_per_scenario"),
        "balanced_product_coverage": d01_balanced.get("product", {}).get("coverage_among_inferred"),
        "dominant_cluster_reference_false_positive_rate": d01_uneven.get("statsmodels_count_only_cluster_reference", {}).get("false_positive_rate"),
        "dominant_cluster_product_abstentions": d01_uneven.get("product", {}).get("abstained_trials"),
        "runtime_dependencies_added": False,
        "scope": "independent synthetic null challenge; inverse-Herfindahl screen is conservative and does not establish coverage"
    }

    mcp, mcp_output = run([sys.executable, "-m", "fabintel", "mcp-test", "--config",
                           "requirements/synthetic-mcp-mapping.v1.json"])
    try:
        mcp_result = json.loads(mcp_output) if mcp.returncode == 0 else {"status": "FAIL"}
    except json.JSONDecodeError:
        mcp_result = {"status": "FAIL", "error": "synthetic MCP CLI output was not JSON"}
    mcp_pass = mcp.returncode == 0 and mcp_result.get("status") == "SYNTHETIC_TRANSPORT_PASS"
    sdk_path = ROOT / "release" / "MCP_SDK_QUALIFICATION.json"
    sdk_report = json.loads(sdk_path.read_text(encoding="utf-8")) if sdk_path.exists() else {}
    mcp_sdk_pass = (sdk_report.get("status") == "PASS_LOCAL_SYNTHETIC_MOCK_ONLY"
                    and sdk_report.get("installed_mcp_version") == "2.3.0"
                    and sdk_report.get("protocol_tests_run") == 7
                    and sdk_report.get("network_used") is False)

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
    d02_replicate_path = ROOT / "qualification" / "results" / "D02_REPLICATION_SHIFT_BENCHMARK.json"
    d02_replicate_run, _ = run([sys.executable, "-m", "qualification.benchmark_d02_replicate_shift",
                                "--output", "qualification/results/D02_REPLICATION_SHIFT_BENCHMARK.json"])
    d02_replicate = json.loads(d02_replicate_path.read_text(encoding="utf-8")) if d02_replicate_path.exists() else {}
    d02_replicate_scenarios = d02_replicate.get("scenarios", {})
    d02_window_hash = hashlib.sha256((ROOT / "products" / "p4" / "window.py").read_bytes()).hexdigest()
    d02_replicate_script_hash = hashlib.sha256(
        (ROOT / "qualification" / "benchmark_d02_replicate_shift.py").read_bytes()).hexdigest()
    d02_replicate_pass = (
        d02_replicate_run.returncode == 0
        and d02_replicate.get("schema") == "p4-d02-replicate-shift-benchmark/v1"
        and d02_replicate.get("trials", 0) >= 1000
        and d02_replicate.get("product_source_sha256") == d02_window_hash
        and d02_replicate.get("benchmark_script_sha256") == d02_replicate_script_hash
        and set(d02_replicate_scenarios) == {"1", "2", "4"}
        and d02_replicate_scenarios.get("1", {}).get("wilson95", [0, 0])[0] <= 0.95
        and d02_replicate_scenarios.get("1", {}).get("wilson95", [0, 0])[1] >= 0.95
        and d02_replicate_scenarios.get("2", {}).get("coverage", 1) < 0.93
        and d02_replicate_scenarios.get("4", {}).get("coverage", 1) < 0.86
    )
    d02_replicate_result = {
        "status": "PASS" if d02_replicate_pass else "FAIL",
        "evidence": "qualification/results/D02_REPLICATION_SHIFT_BENCHMARK.json",
        "source_hash_matches": d02_replicate.get("product_source_sha256") == d02_window_hash,
        "trials": d02_replicate.get("trials"),
        "coverage_by_future_observations_per_setting": {
            key: item.get("coverage") for key, item in d02_replicate_scenarios.items()},
        "runtime_dependencies_added": False,
        "scope": "independent iid finite-panel oracle; replication-shift challenge only"
    }
    d02_simultaneous_path = ROOT / "qualification" / "results" / "D02_SIMULTANEOUS_COVERAGE_BENCHMARK.json"
    d02_simultaneous_run, _ = run([sys.executable, "-m", "qualification.benchmark_d02_simultaneous",
                                   "--output", "qualification/results/D02_SIMULTANEOUS_COVERAGE_BENCHMARK.json"])
    d02_simultaneous = json.loads(d02_simultaneous_path.read_text(encoding="utf-8")) if d02_simultaneous_path.exists() else {}
    d02_simultaneous_script_hash = hashlib.sha256(
        (ROOT / "qualification" / "benchmark_d02_simultaneous.py").read_bytes()).hexdigest()
    d02_coverage = d02_simultaneous.get("joint_exact_panel_coverage", {})
    d02_false_feasible = d02_simultaneous.get("post_selection_false_feasible", {})
    d02_simultaneous_pass = (
        d02_simultaneous_run.returncode == 0
        and d02_simultaneous.get("schema") == "p4-d02-simultaneous-calibration-benchmark/v1"
        and d02_simultaneous.get("trials", 0) >= 500
        and d02_simultaneous.get("product_window_sha256") == d02_window_hash
        and d02_simultaneous.get("benchmark_script_sha256") == d02_simultaneous_script_hash
        and d02_coverage.get("wilson95_miss_rate", [0, 1])[1] <= 0.08
        and d02_false_feasible.get("wilson95_unconditional", [0, 1])[1] <= 0.05
    )
    d02_simultaneous_result = {
        "status": "PASS" if d02_simultaneous_pass else "FAIL",
        "evidence": "qualification/results/D02_SIMULTANEOUS_COVERAGE_BENCHMARK.json",
        "source_hash_matches": d02_simultaneous.get("product_window_sha256") == d02_window_hash,
        "trials": d02_simultaneous.get("trials"),
        "joint_panel_coverage": d02_coverage.get("rate"),
        "joint_panel_miss_wilson95": d02_coverage.get("wilson95_miss_rate"),
        "post_selection_false_feasible_unconditional": d02_false_feasible.get("unconditional_rate"),
        "runtime_dependencies_added": False,
        "scope": "independent nonlinear correlated-lot synthetic challenge under complete-panel assumptions"
    }
    d02_transfer_path = ROOT / "qualification" / "results" / "D02_STRATUM_TRANSFER_BENCHMARK.json"
    d02_transfer_run, _ = run([sys.executable, "-m", "qualification.benchmark_d02_stratum_transfer",
                               "--output", "qualification/results/D02_STRATUM_TRANSFER_BENCHMARK.json"])
    d02_transfer = json.loads(d02_transfer_path.read_text(encoding="utf-8")) if d02_transfer_path.exists() else {}
    d02_transfer_script_hash = hashlib.sha256(
        (ROOT / "qualification" / "benchmark_d02_stratum_transfer.py").read_bytes()).hexdigest()
    d02_transfer_scenarios = d02_transfer.get("scenarios", {})
    d02_same = d02_transfer_scenarios.get("same_known_mix", {})
    d02_shifted = d02_transfer_scenarios.get("shifted_known_mix", {})
    d02_unseen = d02_transfer_scenarios.get("unseen_tool_period", {})
    d02_transfer_pass = (
        d02_transfer_run.returncode == 0
        and d02_transfer.get("schema") == "p4-d02-stratum-transfer-benchmark/v1"
        and d02_transfer.get("trials", 0) >= 1000
        and d02_transfer.get("product_source_sha256") == d02_window_hash
        and d02_transfer.get("benchmark_script_sha256") == d02_transfer_script_hash
        and set(d02_transfer_scenarios) == {"same_known_mix", "shifted_known_mix", "unseen_tool_period"}
        and d02_same.get("wilson95", [1, 0])[0] <= 0.95 <= d02_same.get("wilson95", [1, 0])[1]
        and d02_shifted.get("coverage", 1) < d02_same.get("coverage", 0) - 0.10
        and d02_unseen.get("coverage", 1) < d02_shifted.get("coverage", 0) - 0.20
        and d02_unseen.get("transfer_status_counts", {}).get("COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA", 0)
            >= d02_transfer.get("trials", 0) * 0.90
    )
    d02_transfer_result = {
        "status": "PASS" if d02_transfer_pass else "FAIL",
        "evidence": "qualification/results/D02_STRATUM_TRANSFER_BENCHMARK.json",
        "source_hash_matches": d02_transfer.get("product_source_sha256") == d02_window_hash,
        "trials": d02_transfer.get("trials"),
        "coverage_by_population": {
            name: item.get("coverage") for name, item in d02_transfer_scenarios.items()},
        "mean_observed_total_variation_by_population": {
            name: item.get("mean_observed_calibration_evaluation_total_variation")
            for name, item in d02_transfer_scenarios.items()},
        "runtime_dependencies_added": False,
        "scope": "synthetic correlated-lot transfer challenge across same, shifted-known, and unseen tool-period mixtures; descriptive statuses do not validate exchangeability"
    }
    d03_benchmark_path = ROOT / "qualification" / "results" / "D03_BOUNDED_MEAN_BENCHMARK.json"
    d03_benchmark_run, _ = run([sys.executable, "-m", "qualification.benchmark_d03_bounded_mean",
                                "--output", "qualification/results/D03_BOUNDED_MEAN_BENCHMARK.json"])
    d03_benchmark = json.loads(d03_benchmark_path.read_text(encoding="utf-8")) if d03_benchmark_path.exists() else {}
    d03_current_hashes, d03_current_manifest = product_source_fingerprint()
    d03_script_hash = hashlib.sha256((ROOT / "qualification" / "benchmark_d03_bounded_mean.py").read_bytes()).hexdigest()
    d03_scenarios = d03_benchmark.get("scenario_results", {})
    d03_bounded_pass = (
        d03_benchmark_run.returncode == 0
        and d03_benchmark.get("schema") == "p4-d03-bounded-mean-benchmark/v1"
        and d03_benchmark.get("status") == "PASS"
        and d03_benchmark.get("objective_family_size") == 8
        and d03_benchmark.get("product_source_sha256") == d03_current_hashes
        and d03_benchmark.get("product_source_manifest_sha256") == d03_current_manifest
        and d03_benchmark.get("qualification_script_sha256") == d03_script_hash
        and set(d03_scenarios) == {"30", "60"}
        and all(
            item.get("trials", 0) >= 200
            and item.get("methods", {}).get("bounded_hoeffding", {}).get("joint_mean_coverage_wilson95", [0])[0] >= 0.95
            and item.get("methods", {}).get("bounded_hoeffding", {}).get("false_familywise_dominance_rate", 1) <= 0.05
            for item in d03_scenarios.values())
    )
    d03_benchmark_result = {
        "status": "PASS" if d03_bounded_pass else "FAIL",
        "evidence": "qualification/results/D03_BOUNDED_MEAN_BENCHMARK.json",
        "source_fingerprint_matches": (d03_benchmark.get("product_source_sha256") == d03_current_hashes
                                        and d03_benchmark.get("product_source_manifest_sha256") == d03_current_manifest),
        "trials_by_sample_size": {key: item.get("trials") for key, item in d03_scenarios.items()},
        "bounded_joint_coverage_wilson95_lower_by_sample_size": {
            key: item.get("methods", {}).get("bounded_hoeffding", {}).get("joint_mean_coverage_wilson95", [None])[0]
            for key, item in d03_scenarios.items()},
        "bonferroni_t_joint_coverage_by_sample_size": {
            key: item.get("methods", {}).get("bonferroni_t", {}).get("joint_mean_coverage_rate")
            for key, item in d03_scenarios.items()},
        "bounded_to_t_mean_width_ratio_by_sample_size": {
            key: (item.get("methods", {}).get("bounded_hoeffding", {}).get("mean_interval_width", 0)
                  / max(item.get("methods", {}).get("bonferroni_t", {}).get("mean_interval_width", 1e-300), 1e-300))
            for key, item in d03_scenarios.items()},
        "runtime_dependencies_added": False,
        "scope": "independent skewed bounded synthetic challenge with correlated repeated lots; finite evidence only"
    }
    performance_path = ROOT / "release" / "BENCHMARK_REPORT.json"
    performance = json.loads(performance_path.read_text(encoding="utf-8")) if performance_path.exists() else {}
    performance_source_commit = performance.get("source_commit", "")
    source_is_ancestor = bool(performance_source_commit) and run(
        ["git", "merge-base", "--is-ancestor", performance_source_commit, evaluated_commit])[0].returncode == 0
    _, current_product_manifest = product_source_fingerprint()
    product_paths_unchanged = benchmark_matches_product_sources(performance)
    workflow_perf = performance.get("result_checks", {}).get("integrated_full_workflow_demo_900_rows", {})
    scaling = performance.get("result_checks", {})
    performance_pass = (
        performance.get("benchmark_version") == "3.0.0"
        and source_is_ancestor
        and product_paths_unchanged
        and benchmark_workflow_is_qualified(performance)
        and workflow_perf.get("observations") == 900
        and workflow_perf.get("independent_lots") == 100
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
                          "product_source_manifest_matches": product_paths_unchanged,
                          "product_source_manifest_sha256": current_product_manifest,
                          "integrated_demo_observations": workflow_perf.get("observations"),
                          "integrated_demo_independent_lots": workflow_perf.get("independent_lots"),
                          "maximum_statsmodels_ols_coefficient_difference": performance.get("oss_reference", {}).get("maximum_absolute_coefficient_difference")}
    audit_path = ROOT / "release" / "DEPENDENCY_AUDIT.json"
    dependency_audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    dependency_audit_pass = (
        dependency_audit.get("result") == "PASS"
        and dependency_audit.get("vulnerabilities_found") == 0
        and dependency_audit.get("dependency_instance_count", 0) >= 40
        and {item.get("scope") for item in dependency_audit.get("scope_results", [])}
        == {"qualification", "optional_mcp_sdk_macos_arm64_cp311"}
    )
    dependency_audit_result = {"status": "PASS" if dependency_audit_pass else "FAIL",
                               "evidence": "release/DEPENDENCY_AUDIT.json",
                               "scope": "optional benchmark dependency tree; product runtime has no third-party Python packages",
                               "vulnerabilities_found": dependency_audit.get("vulnerabilities_found")}

    ui_path = ROOT / "release" / "UI_COMPONENT_QUALIFICATION.json"
    ui_report = json.loads(ui_path.read_text(encoding="utf-8")) if ui_path.exists() else {}
    ui_test_source = (ROOT / "products" / "p4" / "ui" / "P4Panel.test.tsx").read_text(encoding="utf-8")
    ui_source_test_count = len(re.findall(r"(?m)^\s*it\(", ui_test_source))
    ui_test_report = ui_report.get("component_tests", {})
    ui_component_pass = (ui_report.get("status") == "PASS_LOCAL_MODULE_ONLY"
                         and ui_test_report.get("expected_test_count") == ui_source_test_count
                         and ui_test_report.get("tests_passed") == ui_source_test_count
                         and ui_report.get("typecheck", {}).get("status") == "PASS"
                         and ui_report.get("contract_snapshot_match") is True)
    p1_host_evidence_path = ROOT / "qualification" / "evidence" / "p1-disposable-host-qualification-2026-11-23.json"
    p1_host_evidence = json.loads(p1_host_evidence_path.read_text(encoding="utf-8")) if p1_host_evidence_path.exists() else {}
    p1_host_checks = p1_host_evidence.get("executed_checks", {})
    p1_browser = p1_host_checks.get("browser", {})
    p1_composition = p1_host_evidence.get("disposable_composition", {})
    p1_current_source = p1_composition.get("current_p4_source", {})
    current_p4_hashes = {
        "engine_sha256": hashlib.sha256((ROOT / "products" / "p4" / "engine.py").read_bytes()).hexdigest(),
        "panel_sha256": hashlib.sha256((ROOT / "products" / "p4" / "ui" / "P4Panel.tsx").read_bytes()).hexdigest(),
        "panel_test_sha256": hashlib.sha256((ROOT / "products" / "p4" / "ui" / "P4Panel.test.tsx").read_bytes()).hexdigest(),
    }
    current_p4_additional_hashes = {
        "products/p4/window.py": hashlib.sha256((ROOT / "products" / "p4" / "window.py").read_bytes()).hexdigest(),
        "products/p4/regression.py": hashlib.sha256((ROOT / "products" / "p4" / "regression.py").read_bytes()).hexdigest(),
        "products/p4/investigation.v1.schema.json": hashlib.sha256((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_bytes()).hexdigest(),
        "products/p4/ui_contribution.json": hashlib.sha256((ROOT / "products" / "p4" / "ui_contribution.json").read_bytes()).hexdigest(),
        "fixtures/full_workflow_demo.json": hashlib.sha256((ROOT / "fixtures" / "full_workflow_demo.json").read_bytes()).hexdigest(),
        "qualification/build_demo_fixture.py": hashlib.sha256((ROOT / "qualification" / "build_demo_fixture.py").read_bytes()).hexdigest(),
    }
    p1_pin = p1_composition.get("p4_registry_pin", {})
    p1_snapshot = p1_composition.get("snapshot_fingerprint", {})
    p1_additional_hashes = p1_composition.get("additional_p4_source_sha256", {})
    p1_source_hashes_match = (p1_current_source == current_p4_hashes
                              and p1_additional_hashes == current_p4_additional_hashes
                              and p1_pin.get("engine_sha256") == current_p4_hashes["engine_sha256"]
                              and p1_pin.get("engine_version") == "1.2.0"
                              and p1_snapshot.get("files") == 28
                              and disposable_snapshot_fingerprint_matches(p1_snapshot))
    p1_disposable_host_pass = (
        p1_source_hashes_match
        and
        p1_host_evidence.get("status") == "PASS_DISPOSABLE_COMPOSITION_ONLY"
        and p1_host_checks.get("p1_frontend_tests", {}).get("status") == "PASS"
        and p1_host_checks.get("p1_frontend_tests", {}).get("tests", 0) > 0
        and p1_host_checks.get("p1_typecheck", {}).get("status") == "PASS"
        and p1_host_checks.get("p1_production_build", {}).get("status") == "PASS"
        and p1_host_checks.get("p1_host_route_tests", {}).get("status") == "PASS"
        and p1_host_checks.get("p4_panel_tests", {}).get("status") == "PASS"
        and p1_browser.get("status") == "PASS_SYNTHETIC_WORKFLOW_AND_REFUSAL"
        and p1_browser.get("success_request") == "COMPLETED"
        and p1_browser.get("permission_refusal", "").startswith("REFUSED")
        and set(p1_browser.get("capabilities", [])) == {"D01", "D02", "D03", "D04", "D05"}
    )
    ui_result = {"status": "PASS_LOCAL_MODULE_ONLY" if ui_component_pass else "NOT_RUN_OR_FAIL",
                 "evidence": "release/UI_COMPONENT_QUALIFICATION.json",
                 "component_tests": ui_test_report.get("tests_passed"),
                 "source_declared_tests": ui_source_test_count,
                 "typecheck": ui_report.get("typecheck", {}).get("status"),
                 "host_integration": "PASS_DISPOSABLE_COMPOSITION_ONLY" if p1_disposable_host_pass else "NOT_RUN_OR_FAIL",
                 "disposable_host_evidence": {
                     "status": "PASS_DISPOSABLE_COMPOSITION_ONLY" if p1_disposable_host_pass else "NOT_RUN_OR_FAIL",
                     "evidence": "qualification/evidence/p1-disposable-host-qualification-2026-11-23.json",
                     "scope": p1_host_evidence.get("scope", "not verified"),
                     "current_p4_source_hashes_match": p1_source_hashes_match,
                     "p1_owner_and_source_version": "PENDING",
                     "formal_accessibility": "PENDING"
                 }}

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
        and security_review.get("finding_count") == len(security_findings)
        and security_review.get("high_or_medium_findings") == 0
        and security_review.get("finding_dispositions_cover_all_reported_findings") is True
        and not security_report.get("errors")
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
                          and frozen_pass and critical_pass and d01_imbalance_pass and d02_replicate_pass and d02_simultaneous_pass and d02_transfer_pass
                          and d03_bounded_pass and mcp_pass and mcp_sdk_pass
                          and dependency_audit_pass and d04_pass and performance_pass
                          and ui_component_pass and security_pass)
    results = {"state": "PASS" if qualification_pass else "FAIL",
               "unit_tests": test_summary, "integrated_demo": demo_result,
               "synthetic_mcp_external_mock": {"status": "PASS" if mcp_pass else "FAIL",
                                                "evidence": "requirements/synthetic-mcp-mapping.v1.json",
                                                "result": mcp_result},
               "mcp_sdk_offline_qualification": {"status": "PASS" if mcp_sdk_pass else "FAIL",
                                                  "evidence": "release/MCP_SDK_QUALIFICATION.json",
                                                  "version": sdk_report.get("installed_mcp_version"),
                                                  "protocol_tests": sdk_report.get("protocol_tests_run")},
               "d04_oss_benchmark": benchmark_result,
               "d01_cluster_imbalance_benchmark": d01_imbalance_result,
               "d02_replicate_shift_benchmark": d02_replicate_result,
               "d02_simultaneous_coverage_benchmark": d02_simultaneous_result,
               "d03_bounded_mean_benchmark": d03_benchmark_result,
               "scientific_performance_benchmark": performance_result,
               "dependency_audit": dependency_audit_result,
               "ui_module_qualification": ui_result,
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
        "d01_cluster_imbalance_benchmark": d01_imbalance_result,
        "d02_replicate_shift_benchmark": d02_replicate_result,
        "d02_simultaneous_coverage_benchmark": d02_simultaneous_result,
        "d02_stratum_transfer_benchmark": d02_transfer_result,
        "d03_bounded_mean_benchmark": d03_benchmark_result,
        "scientific_performance_benchmark": performance_result,
        "dependency_audit": dependency_audit_result,
        "ui_module_qualification": ui_result,
        "source_security_scan": source_security_result,
        "schema_validation": {"status": schema_status, "command_return_code": schema_run.returncode,
                              "evidence": "release/SCHEMA_VALIDATION.json"},
        "frozen_shared_contracts": {"status": "PASS" if frozen_pass else "FAIL", "fingerprints_match_starter": contract_hash},
        "gates": {
            "E01": {"status": "PASS" if demo_result["status"] == "PASS" else "FAIL", "evidence": ["release/full_workflow_demo_evidence.json", "release/TEST_LOG.txt"], "scope": "synthetic end-to-end capability flow"},
            "E02": {"status": "PASS" if critical_pass and d01_imbalance_pass and d02_replicate_pass and d02_simultaneous_pass and d02_transfer_pass and d04_pass and d03_bounded_pass and performance_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "tests/test_d01_d02_independent.py", "tests/test_d03_relationships.py", "tests/test_d04_designs.py", "tests/test_d05_studies.py", "fixtures/p4_independent_oracles.json", "qualification/critical_cases.json", "qualification/benchmark_d01_cluster_imbalance.py", "qualification/results/D01_CLUSTER_IMBALANCE_BENCHMARK.json", "qualification/benchmark_d02_replicate_shift.py", "qualification/results/D02_REPLICATION_SHIFT_BENCHMARK.json", "qualification/benchmark_d02_simultaneous.py", "qualification/results/D02_SIMULTANEOUS_COVERAGE_BENCHMARK.json", "qualification/benchmark_d02_stratum_transfer.py", "qualification/results/D02_STRATUM_TRANSFER_BENCHMARK.json", "qualification/benchmark_d03_bounded_mean.py", "qualification/results/D03_BOUNDED_MEAN_BENCHMARK.json", "release/D04_OSS_COMPARISON.json", "release/BENCHMARK_REPORT.json", "release/TEST_RESULTS.json"], "scope": "fixed numeric oracles, 100 seeded slope cases, held-out nonlinear/confounded/correlated/OOD cases, D01 effective-cluster-size abstention challenge, D02 replicate-count/correlated-lot panel and cross-tool/time transfer challenges under explicit synthetic mixtures, D03 skewed bounded-familywise interval challenge, multiobjective and failed-experiment cases, invalid-assumption refusals, independent statsmodels references, and fixed synthetic D04 OSS benchmarks"},
            "E03": {"status": "PASS" if critical_pass else "FAIL", "evidence": ["tests/test_p4_scientific.py", "tests/test_offline_server.py"], "scope": "unsafe, invalid, leakage, permission, cancellation and host/origin cases"},
            "E04": {"status": "PASS" if frozen_pass and schema_status == "PASS" else "FAIL", "evidence": ["contracts/", "products/p4/investigation.v1.schema.json", "release/SCHEMA_VALIDATION.json"]},
            "E05": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "qualification/internal-capability-report.v1.schema.json"], "reason": "real authorization, approved semantics, bounded reads and source audit are unavailable externally"},
            "E06": {"status": "PASS" if mcp_pass and mcp_sdk_pass else "FAIL", "evidence": ["release/MCP_SDK_QUALIFICATION.json", "release/LICENSE_SECURITY_REVIEW.md", "tests/test_mcp_transport.py", "requirements/synthetic-mcp-mapping.v1.json", "vendor/mcp-sdk/2.3.0/macos-arm64-cp311/requirements.lock"], "scope": "official MCP SDK hash-locked offline install and stdio/Streamable HTTP protocol tests against a synthetic mock; company tool names/permissions/source semantics remain unconfigured"},
            "E07": {"status": "PENDING_AUTHORITATIVE_HOST_AND_FORMAL_ACCESSIBILITY" if ui_component_pass and p1_disposable_host_pass else "PENDING_HOST_AND_FORMAL_ACCESSIBILITY" if ui_component_pass else "NOT_RUN_OR_FAIL", "evidence": ["release/UI_COMPONENT_QUALIFICATION.json", "qualification/evidence/p1-disposable-host-qualification-2026-11-23.json", "products/p4/ui/P4Panel.test.tsx", "products/p4/ui/P4Panel.tsx"], "reason": "current P4 source passed a synthetic workflow and permission-refusal run inside a disposable composition of the available P1 shell, including the shared Pareto chart; authoritative P1 source/version/registry ownership, owner acceptance, formal WCAG and screen-reader review, full contrast review, and target-host behavior remain pending"},
            "E08": {"status": "PENDING_TARGET_OS", "evidence": ["release/NO_NETWORK_QUALIFICATION.md", "qualification/offline_qualify.py"], "reason": "a local-host offline bundle run is recorded separately; the company target OS remains unknown"},
            "E09": {"status": "PENDING_LICENSE_AND_INDEPENDENT_SECURITY_REVIEW", "dependency_audit": "PASS" if dependency_audit_pass else "FAIL", "source_security_scan": source_security_result["status"], "evidence": ["release/SBOM.spdx.json", "release/DEPENDENCY_AUDIT.json", "release/SOURCE_SECURITY_SCAN.json", "release/LICENSE_SECURITY_REVIEW.md"], "reason": "local advisory and source scans are limited-scope evidence; independent manual/OS security review, license interpretation/approval, and owner/legal distribution rights remain unresolved"},
            "E10": {"status": "PASS" if archive_qualification_pass(evaluated_commit) else "PENDING_FINAL_ARCHIVE", "evidence": ["release/TRANSFER_BUNDLE.sha256", "release/BUILD_REPRODUCIBILITY.json", "release/OFFLINE_QUALIFICATION.json", "qualification/build_transfer_bundle.py"], "scope": "exact current local archive, clean-source reproducible build and fresh extracted offline runtime"} if archive_qualification_pass(evaluated_commit) else {"status": "PENDING_FINAL_ARCHIVE", "evidence": ["release/TRANSFER_BUNDLE.sha256", "release/BUILD_REPRODUCIBILITY.json", "release/OFFLINE_QUALIFICATION.json", "qualification/build_transfer_bundle.py"], "reason": "the exact current archive, clean-source reproducible build and fresh extracted offline runtime must all match"},
            "E11": {"status": "PENDING_ENGINEER_BASELINE", "evidence": ["qualification/BENCHMARK_PLAN.md", "release/BENCHMARK_REPORT.json"], "reason": "synthetic latency is measured; no eligible engineer task-time, review-burden or ROI baseline exists"},
            "E12": {"status": "PENDING_INTERNAL", "evidence": ["qualification/first_run.py", "docs/INTERNAL_COMPANY_FIRST_RUN.md"], "reason": "company MCP, host, policy owner and engineer qualification require authorized site testing"}
        },
        "internal": {"state": "PENDING_INTERNAL", "unverified": ["real MCP and auth scopes", "source semantics and joins", "authoritative P1 source/version/registration and owner-accepted D01-D05 capability contract", "company target OS and approved host", "company data pilot", "engineer acceptance", "owner/legal transfer approval", "literal R01-R53 and Golden standard"]},
        "known_critical_defects": [],
        "release_blockers": ["no actual authorized MCP connector", "disposable P1 composition compatibility was demonstrated; authoritative P1 source/version/registration ownership and owner acceptance remain pending", "formal accessibility and target-host behavior remain unqualified", "license ownership and distribution rights are not declared", "independent source security review not completed", "company target OS and formal UX/user baselines not supplied"]
    }
    path = ROOT / "release" / "GATE_REPORT.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "tests": test_summary, "demo": demo_result,
                      "schema_validation": schema_status, "contract_fingerprints": contract_hash,
                      "ui_module_qualification": ui_result,
                      "evaluated_commit": evaluated_commit,
                      "gate_report": str(path)}, indent=2, sort_keys=True))
    return 0 if results["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
