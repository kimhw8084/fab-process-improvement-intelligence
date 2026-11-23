"""Independent Monte Carlo check for D02 finite exact-setting calibration.

The known generator has correlated responses, lot-level dependence, nonlinear
factor effects, and setting-dependent noise. Calibration and future lots are
drawn independently from the same generator. This checks the implemented
finite-panel statement under its assumptions; it does not qualify production
exchangeability or interpolation coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from products.p4.regression import fit_linear_model
from products.p4.window import _simultaneous_exact_setting_calibration


SETTINGS = [(float(pressure), float(power)) for pressure in (0, 1, 2) for power in (0, 1, 2)]
FACTORS = {"pressure": {"role": "controllable", "unit": "kPa"},
           "power": {"role": "controllable", "unit": "W"}}
METRICS = ("quality", "defect")
ROOT = Path(__file__).resolve().parents[1]
BOUNDS = {"quality": {"min": 0.15}, "defect": {"max": 0.24}}
PRECOMMIT = {"plan_reference": "BENCHMARK-PRECOMMIT-001",
             "model_selection_reference": "BENCHMARK-FROZEN-MODEL-001",
             "threshold_selection_reference": "BENCHMARK-FROZEN-LIMITS-001",
             "observations_per_setting": 1,
             "metric_family": list(METRICS),
             "exact_setting_panel": [
                 {"pressure": pressure, "power": power} for pressure, power in SETTINGS]}


def _panel_rows(rng: random.Random, unit_id: str, partition: str):
    lot_quality = rng.gauss(0.0, 0.025)
    lot_defect = rng.gauss(0.0, 0.018)
    correlated_lot_shock = rng.gauss(0.0, 0.012)
    rows = []
    for pressure, power in SETTINGS:
        p, w = pressure - 1.0, power - 1.0
        quality = (0.285 + 0.018*p - 0.060*p*p - 0.045*w*w + 0.012*p*w
                   + lot_quality + correlated_lot_shock
                   + rng.gauss(0.0, 0.006 + 0.004*pressure))
        defect = (0.118 + 0.035*p*p + 0.050*w*w - 0.010*p*w
                  + lot_defect + 0.55*correlated_lot_shock
                  + rng.gauss(0.0, 0.007 + 0.003*power))
        rows.append({"id": f"{unit_id}-{pressure}-{power}",
                     "factors": {"pressure": pressure, "power": power},
                     "metrics": {"quality": quality, "defect": defect},
                     "lot_id": unit_id, "partition": partition})
    return rows


def _draw_panel(rng: random.Random, count: int, prefix: str, partition: str):
    return [row for i in range(count) for row in _panel_rows(rng, f"{prefix}-{i:04d}", partition)]


def run_benchmark(trials: int = 1000, seed: int = 20261123):
    if trials < 100:
        raise ValueError("at least 100 trials are required for a useful Monte Carlo diagnostic")
    rng = random.Random(seed)
    training = _draw_panel(rng, 40, "TRAIN", "TRAIN")
    models = {}
    reports = {}
    options = {"quadratic": True, "interactions": True,
               "covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30}
    for metric in METRICS:
        reports[metric], models[metric] = fit_linear_model(training, FACTORS, metric, options)
        if models[metric] is None or reports[metric].get("status") != "VALID":
            raise RuntimeError(f"training fit unavailable for {metric}: {reports[metric]}")

    simultaneous_misses = 0
    selected_any = 0
    false_feasible = 0
    candidate_cell_counts = []
    radii = {metric: [] for metric in METRICS}
    setting_count = len(SETTINGS)
    for trial in range(trials):
        calibration = _draw_panel(rng, 39, f"CAL-{trial}", "CALIBRATION")
        evaluation = _panel_rows(rng, f"EVAL-{trial}", "EVALUATION")
        calibrated = _simultaneous_exact_setting_calibration(
            calibration, list(METRICS), models, ["pressure", "power"], {}, "lot_id", PRECOMMIT)
        if calibrated.get("status") != "AVAILABLE":
            raise RuntimeError(f"finite exact-setting calibration unavailable: {calibrated}")
        for metric in METRICS:
            radii[metric].append(calibrated["metric_quantiles"][metric]["absolute_error_radius"])

        candidate_settings = []
        all_covered = True
        for row in evaluation:
            factors = row["factors"]
            for metric in METRICS:
                prediction = models[metric].predict(factors, {})["estimate"]
                radius = calibrated["metric_quantiles"][metric]["absolute_error_radius"]
                if abs(row["metrics"][metric] - prediction) > radius:
                    all_covered = False
        if not all_covered:
            simultaneous_misses += 1

        for pressure, power in SETTINGS:
            factors = {"pressure": pressure, "power": power}
            predictions = {metric: models[metric].predict(factors, {})["estimate"] for metric in METRICS}
            intervals = {
                metric: (predictions[metric] - calibrated["metric_quantiles"][metric]["absolute_error_radius"],
                         predictions[metric] + calibrated["metric_quantiles"][metric]["absolute_error_radius"])
                for metric in METRICS
            }
            if intervals["quality"][0] >= BOUNDS["quality"]["min"] and intervals["defect"][1] <= BOUNDS["defect"]["max"]:
                candidate_settings.append((pressure, power))
        candidate_cell_counts.append(len(candidate_settings))
        if candidate_settings:
            selected_any += 1
            for row in evaluation:
                if ((row["factors"]["pressure"], row["factors"]["power"]) in candidate_settings
                        and (row["metrics"]["quality"] < BOUNDS["quality"]["min"]
                             or row["metrics"]["defect"] > BOUNDS["defect"]["max"])):
                    false_feasible += 1
                    break

    def rate_interval(events, denominator=trials):
        rate = events / denominator
        z = 1.959963984540054
        adjusted_denominator = 1.0 + z*z/denominator
        center = (rate + z*z/(2*denominator))/adjusted_denominator
        half = z*math.sqrt((rate*(1-rate) + z*z/(4*denominator))/denominator)/adjusted_denominator
        return [max(0.0, center-half), min(1.0, center+half)]

    return {
        "schema": "p4-d02-simultaneous-calibration-benchmark/v1",
        "method": "split-conformal independent-unit maximum absolute residual over a complete 3x3 exact-setting panel, Bonferroni across two outcomes",
        "generator": "fixed-known nonlinear quality/defect surfaces with correlated lot shocks and factor-dependent noise",
        "seed": seed,
        "trials": trials,
        "product_window_sha256": hashlib.sha256((ROOT / "products" / "p4" / "window.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "training_units": 40,
        "calibration_units_per_trial": 39,
        "future_units_per_trial": 1,
        "metrics": list(METRICS),
        "candidate_thresholds": BOUNDS,
        "joint_exact_panel_coverage": {
            "successes": trials - simultaneous_misses,
            "rate": (trials-simultaneous_misses)/trials,
            "wilson95_coverage": rate_interval(trials-simultaneous_misses),
            "wilson95_miss_rate": rate_interval(simultaneous_misses),
            "misses": simultaneous_misses,
            "target_miss_probability_at_most": 0.05,
        },
        "post_selection_false_feasible": {
            "trials_with_any_candidate": selected_any,
            "trials_with_any_future_candidate_violation": false_feasible,
            "conditional_rate_when_candidate_selected": false_feasible/selected_any if selected_any else None,
            "wilson95_conditional_rate_when_candidate_selected": rate_interval(false_feasible, selected_any) if selected_any else None,
            "unconditional_rate": false_feasible/trials,
            "wilson95_unconditional": rate_interval(false_feasible),
            "mean_candidate_cells_per_trial": statistics.mean(candidate_cell_counts),
            "minimum_candidate_cells_per_trial": min(candidate_cell_counts),
            "maximum_candidate_cells_per_trial": max(candidate_cell_counts),
            "mean_metric_interval_radii": {metric: statistics.mean(values) for metric, values in radii.items()},
            "interpretation": "descriptive finite simulation under exchangeable complete-panel assumptions only",
        },
        "all_training_models": {metric: reports[metric] for metric in METRICS},
        "limitations": [
            "Monte Carlo evidence does not verify real-process exchangeability or internal source semantics",
            "guarantee target is the finite exact-setting panel, not interpolated or extrapolated cells",
            "false-feasible rate is an empirical challenge result, not a production risk estimate",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(serialized, end="")
    misses = result["joint_exact_panel_coverage"]["misses"]
    if misses / args.trials > 0.08:
        raise SystemExit("simultaneous calibration exceeded the prespecified Monte Carlo miss-rate tolerance")


if __name__ == "__main__":
    main()
