"""Independent coverage challenge for pooled versus predeclared-stratum calibration."""
from __future__ import annotations

import argparse
import hashlib
import json
from math import sqrt
import random
from pathlib import Path

from products.p4.window import _simultaneous_exact_setting_calibration

ROOT = Path(__file__).resolve().parents[1]


class ZeroModel:
    @staticmethod
    def predict(factors, fixed_effects=None):
        return {"estimate": 0.0}


def _wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z*z/trials
    center = (p + z*z/(2*trials)) / denominator
    half = z * sqrt((p*(1-p) + z*z/(4*trials))/trials) / denominator
    return [center-half, center+half]


def run_benchmark(trials: int = 2500, seed: int = 817203) -> dict:
    """Compare under future B-only mix after 50:50 calibration, with known error scales."""
    rng = random.Random(seed)
    pooled_hits = 0
    stratified_hits = 0
    pooled_radii = []
    stratified_radii = []
    plan = {"plan_reference": "SYNTHETIC-FIXED-PLAN",
            "model_selection_reference": "SYNTHETIC-FIXED-MODEL",
            "threshold_selection_reference": "SYNTHETIC-FIXED-THRESHOLDS",
            "metric_family": ["quality"],
            "metric_bounds": {"quality": {"min": 0.0, "max": 100.0}},
            "exact_setting_panel": [{"pressure": 0.0}],
            "strata": {"fields": ["tool_id"],
                       "categories": [{"tool_id": "A"}, {"tool_id": "B"}]}}
    bounds = {"quality": {"min": 0.0, "max": 100.0}}
    for trial in range(trials):
        rows = []
        for tool, scale in (("A", 1.0), ("B", 4.0)):
            for index in range(20):
                rows.append({"lot_id": f"{tool}-{trial}-{index}", "tool_id": tool,
                             "factors": {"pressure": 0.0},
                             "metrics": {"quality": rng.gauss(0.0, scale)}})
        pooled = _simultaneous_exact_setting_calibration(
            rows, ["quality"], {"quality": ZeroModel()}, ["pressure"], {},
            "lot_id", {key: value for key, value in plan.items() if key != "strata"}, bounds)
        stratified = _simultaneous_exact_setting_calibration(
            rows, ["quality"], {"quality": ZeroModel()}, ["pressure"], {},
            "lot_id", plan, bounds)
        if pooled["status"] != "AVAILABLE" or stratified["status"] != "AVAILABLE":
            raise RuntimeError(f"unexpected calibration refusal: pooled={pooled['status']} stratified={stratified['status']}")
        pooled_radius = pooled["metric_quantiles"]["quality"]["absolute_error_radius"]
        stratified_radius = stratified["metric_quantiles"]["quality"]["absolute_error_radius"]
        future_error = abs(rng.gauss(0.0, 4.0))
        pooled_radii.append(pooled_radius)
        stratified_radii.append(stratified_radius)
        pooled_hits += future_error <= pooled_radius
        stratified_hits += future_error <= stratified_radius
    pooled_coverage = pooled_hits / trials
    stratified_coverage = stratified_hits / trials
    return {"schema": "p4-d02-stratified-calibration-benchmark/v1",
            "status": "PASS",
            "benchmark": "D02_POOLED_VS_PREDECLARED_STRATUM_CALIBRATION",
            "product_window_sha256": hashlib.sha256((ROOT / "products/p4/window.py").read_bytes()).hexdigest(),
            "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "seed": seed, "trials": trials,
            "calibration": {"units_per_stratum": 20, "strata": 2,
                            "error_scales": {"A": 1.0, "B": 4.0}, "mix": "50:50"},
            "future_population": {"stratum": "B", "error_scale": 4.0, "mix": "100% B"},
            "independent_future_unit_coverage": {
                "pooled": {"hits": pooled_hits, "fraction": pooled_coverage,
                           "wilson95_monte_carlo_interval": _wilson(pooled_hits, trials),
                           "median_radius": sorted(pooled_radii)[trials//2]},
                "stratified_worst_group": {"hits": stratified_hits, "fraction": stratified_coverage,
                                           "wilson95_monte_carlo_interval": _wilson(stratified_hits, trials),
                                           "median_radius": sorted(stratified_radii)[trials//2]}},
            "interpretation": ("Synthetic finite-sample challenge only. Calibration units are exchangeable within each fixed stratum; "
                               "the future stratum is known and predeclared. This does not assess real source semantics, "
                               "model misspecification, or production coverage.")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=817203)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    pooled = result["independent_future_unit_coverage"]["pooled"]["fraction"]
    stratified = result["independent_future_unit_coverage"]["stratified_worst_group"]["fraction"]
    if not (pooled < 0.93 and stratified >= 0.92):
        raise SystemExit(f"independent coverage challenge failed: pooled={pooled:.4f}, stratified={stratified:.4f}")
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
