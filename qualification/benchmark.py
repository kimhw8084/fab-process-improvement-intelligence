"""Repeatable, local benchmark; optional third-party packages are reference-only."""
import json
import hashlib
import math
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPEATS = 25
sys.path.insert(0, str(ROOT))


def product_source_fingerprint():
    paths = sorted((ROOT / "fabintel").rglob("*.py")) + sorted((ROOT / "products" / "p4").rglob("*.py"))
    files = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    manifest = "\n".join(f"{digest}  {name}" for name, digest in sorted(files.items())) + "\n"
    return files, hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def integrated_demo_is_qualified(evidence, observation_count):
    keys = {"D01": "D01_sensitivity", "D02": "D02_supported_region", "D03": "D03_tradeoffs",
            "D04": "D04_experiment_proposal", "D05": "D05_effectiveness"}
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not isinstance(artifacts[0], dict):
        return False, {capability: None for capability in keys}
    artifact = artifacts[0]
    allowed = {"D01": {"VALID", "INCONCLUSIVE"}, "D02": {"VALID", "INCONCLUSIVE"},
               "D03": {"VALID", "LIMITED_SCOPE"}, "D04": {"PROPOSED", "INCONCLUSIVE"},
               "D05": {"ESTIMATED", "INCONCLUSIVE"}}
    statuses = {capability: artifact.get(key, {}).get("status") for capability, key in keys.items()}
    complete = all(key in artifact for key in keys.values())
    workflow_complete = evidence.get("status") in ("VALID", "PARTIAL") and complete
    return (workflow_complete and observation_count == 900
            and all(statuses[name] in allowed[name] for name in keys)), statuses


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]


def measure(fn):
    samples = []
    result = None
    for _ in range(REPEATS):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"p50_ms": statistics.median(samples), "p95_ms": percentile(samples, 0.95),
            "repeats": REPEATS, "peak_python_alloc_bytes_one_run": peak}, result


def generated_request(n):
    rows = [{"id": f"SYN-BENCH-{i:05d}", "factors": {"x": float(i % 101)},
             "metrics": {"response": 3.0 * (i % 101) + math.sin(i) * 0.2}}
            for i in range(n)]
    return {"objective": "Measure standard single-metric sensitivity benchmark",
            "context": {"process_step": "SYN-BENCHMARK"},
            "grain": "one synthetic measurement row",
            "sampling_unit": "synthetic row",
            "timestamp_semantics": "deterministic row sequence; timestamps are not modeled",
            "constraints_approved": True,
            "factors": [{"name": "x", "role": "controllable", "unit": "synthetic unit",
                         "bounds": [0, 100], "approved": True}],
            "metrics": [{"name": "response", "unit": "synthetic unit", "direction": "maximize"}],
            "observations": rows}


def main():
    from fabintel.catalog import synthetic_catalog
    from products.p4.engine import analyze

    fixture = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text())
    tasks = {}
    result_checks = {}
    integrated_stats, integrated = measure(lambda: analyze(fixture))
    tasks["integrated_full_workflow_demo_900_rows"] = integrated_stats
    integrated_qualified, capability_statuses = integrated_demo_is_qualified(
        integrated, len(fixture.get("observations", [])))
    if not integrated_qualified or len({row.get("lot_id") for row in fixture["observations"]}) != 100:
        raise RuntimeError("the benchmark walkthrough must contain all five qualified capability outputs over 900 rows and 100 lots")
    result_checks["integrated_full_workflow_demo_900_rows"] = {
        "status": integrated["status"], "observations": len(fixture["observations"]),
        "independent_lots": len({row["lot_id"] for row in fixture["observations"]}),
        "capability_statuses": capability_statuses,
        "qualification_status": "PASS",
        "note": "reported PARTIAL/LIMITED_SCOPE states are retained when the full workflow runs correctly"}
    for n in (18, 1000, 5000):
        request = generated_request(n)
        task_stats, result = measure(lambda: analyze(request))
        dossier = result.get("artifacts", [{}])[0]
        sensitivity_status = dossier.get("D01_sensitivity", {}).get("status")
        if sensitivity_status != "VALID":
            raise RuntimeError(f"the generated {n}-row sensitivity request failed validation")
        tasks[f"single_metric_sensitivity_{n}_rows"] = task_stats
        result_checks[f"single_metric_sensitivity_{n}_rows"] = {
            "dossier_status": result.get("status"), "D01_status": sensitivity_status,
            "observations": n, "note": "other unrequested D02-D05 sections may make the dossier PARTIAL"}
    tasks["synthetic_schema_catalog_13000_tables"], catalog = measure(lambda: synthetic_catalog(13000))
    product_files, product_manifest = product_source_fingerprint()
    report = {
        "benchmark_version": "3.0.0",
        "precommitted_protocol": "qualification/BENCHMARK_PLAN.md (900-row integrated fixture and independent scaling tasks)",
        "environment": {"os": platform.platform(), "system": platform.system(), "release": platform.release(),
                        "architecture": platform.machine(), "processor": platform.processor(), "python": sys.version},
        "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         capture_output=True).stdout.strip() or "UNAVAILABLE",
        "product_source_sha256": product_files,
        "product_source_manifest_sha256": product_manifest,
        "network": "not used",
        "tasks": tasks,
        "result_checks": result_checks,
        "catalog_rows": len(catalog),
        "reproducibility": "25 repetitions per task; deterministic input fixtures; perf_counter and tracemalloc",
        "engineering_user_baseline": "NOT_AVAILABLE; no eligible engineer study or human task-time baseline supplied",
        "thresholds": "No latency or ROI thresholds invented; p50/p95 reported for later internal pre-registration.",
    }
    try:
        import numpy as np
        import statsmodels
        import statsmodels.api as sm
        rows = fixture["observations"]
        p = np.array([r["factors"]["pressure"] for r in rows])
        t = np.array([r["factors"]["temperature"] for r in rows])
        y = np.array([r["metrics"]["yield_index"] for r in rows])
        pc, tc = p.mean(), t.mean()
        design = np.column_stack([np.ones(len(rows)), p-pc, t-tc, (p-pc)*(t-tc)])
        def fit_reference():
            return sm.OLS(y, design).fit()
        reference_stats, fit = measure(fit_reference)
        reference_request = {
            "objective": "Compare centered first-order interaction coefficients to statsmodels OLS",
            "context": {"process_step": "SYN-BENCHMARK"},
            "grain": "one synthetic measurement row",
            "sampling_unit": "synthetic row",
            "timestamp_semantics": "deterministic row sequence; timestamps are not modeled",
            "constraints_approved": True,
            "factors": [{"name": "pressure", "role": "controllable", "unit": "synthetic", "approved": True},
                        {"name": "temperature", "role": "controllable", "unit": "synthetic", "approved": True}],
            "metrics": [{"name": "yield_index", "unit": "synthetic", "direction": "maximize"}],
            "primary_metric": "yield_index", "observations": rows,
            "model": {"factor_fields": ["pressure", "temperature"], "interactions": True}
        }
        engine_report = analyze(reference_request)
        engine_d01 = engine_report.get("artifacts", [{}])[0].get("D01_sensitivity", {})
        if engine_d01.get("status") != "VALID":
            raise RuntimeError("the benchmark's independent first-order model did not produce valid D01 estimates")
        engine = engine_d01["terms"]
        names = ["intercept", "pressure", "temperature", "pressure:temperature"]
        engine_names = ["intercept_at_factor_centers", "pressure", "temperature", "pressure:temperature"]
        deltas = {name: abs(float(fit.params[i]) - engine[engine_names[i]]["estimate"])
                  for i, name in enumerate(names)}
        report["oss_reference"] = {"name": "statsmodels OLS", "version": statsmodels.__version__,
                                    "role": "benchmark-only; not imported by product runtime", "metrics": reference_stats,
                                    "maximum_absolute_coefficient_difference": max(deltas.values()),
                                    "absolute_differences": deltas}
    except ImportError as exc:
        report["oss_reference"] = {"name": "statsmodels OLS", "status": "NOT_INSTALLED",
                                    "reason": str(exc), "role": "optional benchmark reference only"}
    out = ROOT / "release" / "BENCHMARK_REPORT.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
