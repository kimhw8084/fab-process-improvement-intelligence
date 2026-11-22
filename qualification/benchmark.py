"""Repeatable, local benchmark; optional third-party packages are reference-only."""
import json
import math
import platform
import statistics
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
    return {"constraints_approved": True,
            "factors": [{"name": "x", "role": "controllable", "unit": "synthetic unit",
                         "bounds": [0, 100], "approved": True}],
            "metrics": [{"name": "response", "unit": "synthetic unit", "direction": "maximize"}],
            "observations": rows}


def main():
    from fabintel.catalog import synthetic_catalog
    from products.p4.engine import analyze

    fixture = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text())
    tasks = {}
    for n in (18, 1000, 5000):
        request = fixture if n == 18 else generated_request(n)
        tasks[f"integrated_analysis_{n}_rows"], _ = measure(lambda: analyze(request))
    tasks["synthetic_schema_catalog_13000_tables"], catalog = measure(lambda: synthetic_catalog(13000))
    report = {
        "benchmark_version": "1.0.0",
        "precommitted_protocol": "qualification/BENCHMARK_PLAN.md",
        "environment": {"os": platform.platform(), "system": platform.system(), "release": platform.release(),
                        "architecture": platform.machine(), "processor": platform.processor(), "python": sys.version},
        "network": "not used",
        "tasks": tasks,
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
        engine = analyze(fixture)["artifacts"][0]["D01_sensitivity"]["terms"]
        names = ["intercept", "pressure", "temperature", "pressure:temperature"]
        deltas = {name: abs(float(fit.params[i]) - engine[name]["estimate"]) for i, name in enumerate(names)}
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
