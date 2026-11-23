"""Repeatable, local benchmark; optional third-party packages are reference-only."""
import json
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
    tasks["integrated_full_workflow_demo_540_rows"] = integrated_stats
    if integrated.get("status") != "VALID" or len(fixture.get("observations", [])) != 540:
        raise RuntimeError("the benchmark walkthrough must be the validated 540-row/60-lot fixture")
    result_checks["integrated_full_workflow_demo_540_rows"] = {
        "status": integrated["status"], "observations": len(fixture["observations"]),
        "independent_lots": len({row["lot_id"] for row in fixture["observations"]})}
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
    report = {
        "benchmark_version": "2.0.0",
        "precommitted_protocol": "qualification/BENCHMARK_PLAN.md (540-row integrated fixture and independent scaling tasks)",
        "environment": {"os": platform.platform(), "system": platform.system(), "release": platform.release(),
                        "architecture": platform.machine(), "processor": platform.processor(), "python": sys.version},
        "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         capture_output=True).stdout.strip() or "UNAVAILABLE",
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
