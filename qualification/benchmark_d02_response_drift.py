"""Paired independent challenge for D02 response drift behind matching strata.

The held-out evaluation uses the same declared tool, time, exact setting panel,
and observation count as calibration. In one paired scenario a hidden chamber
changes the response surface. The product's held-out interval evaluator is
scored against a known generator; rates are trial-level summaries because
units within a trial share the fitted model and calibration band.

This is synthetic counterevidence detection evidence, not a coverage guarantee,
population validation, or qualification of any manufacturing process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from products.p4.regression import fit_linear_model
from products.p4.window import (
    _calibration_transfer_assessment,
    _evaluate_calibration_band_transfer,
    _evaluation_panel_compatibility,
    _partition_composition_diagnostic,
    _simultaneous_exact_setting_calibration,
)


SETTINGS = [(float(x), float(y)) for x in (0, 1, 2) for y in (0, 1, 2)]
MODEL_FACTORS = ["pressure", "power"]
DRIFT_AMPLITUDES = (0.0, 0.025, 0.05, 0.10, 0.19)
FACTORS = {
    "pressure": {"role": "controllable", "unit": "kPa"},
    "power": {"role": "controllable", "unit": "W"},
}
PRECOMMIT = {
    "plan_reference": "SYNTHETIC-FROZEN-D02-DRIFT-PLAN-v1",
    "model_selection_reference": "SYNTHETIC-FROZEN-D02-DRIFT-MODEL-v1",
    "threshold_selection_reference": "SYNTHETIC-FROZEN-D02-DRIFT-THRESHOLD-v1",
    "observations_per_setting": 1,
    "metric_family": ["quality"],
    "metric_bounds": {"quality": {"min": None, "max": 0.50}},
    "exact_setting_panel": [
        {"pressure": x, "power": y} for x, y in SETTINGS
    ],
}


def _surface(pressure: float, power: float) -> float:
    x, y = pressure - 1.0, power - 1.0
    return 0.30 + 0.035*x - 0.050*x*x + 0.020*y - 0.028*y*y + 0.014*x*y


def _unit_rows(rng: random.Random, unit: str, partition: str) -> list[dict]:
    lot_intercept = rng.gauss(0.0, 0.030)
    lot_pressure_slope = rng.gauss(0.0, 0.008)
    rows = []
    for pressure, power in SETTINGS:
        x = pressure - 1.0
        rows.append({
            "id": f"{unit}-{pressure:g}-{power:g}",
            "lot_id": unit,
            "partition": partition,
            "tool_id": "TOOL-A",
            "event_year": 2026,
            "chamber": "CH-EVAL" if partition == "EVALUATION" else "CH-BASE",
            "factors": {"pressure": pressure, "power": power},
            "metrics": {
                "quality": (_surface(pressure, power) + lot_intercept
                            + lot_pressure_slope*x + rng.gauss(0.0, 0.010))
            },
        })
    return rows


def _panel_rows(rng: random.Random, count: int, prefix: str, partition: str) -> list[dict]:
    return [row for index in range(count)
            for row in _unit_rows(rng, f"{prefix}-{index:03d}", partition)]


def _apply_response_drift(rows: list[dict], amplitude: float) -> list[dict]:
    shifted_rows = []
    for base in rows:
        shifted = {**base, "factors": dict(base["factors"]), "metrics": dict(base["metrics"])}
        x = shifted["factors"]["pressure"] - 1.0
        y = shifted["factors"]["power"] - 1.0
        shifted["metrics"]["quality"] += amplitude * (x + (0.12 / 0.19) * x * y)
        shifted_rows.append(shifted)
    return shifted_rows


def _wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1.0 + z*z/trials
    center = (rate + z*z/(2*trials)) / denominator
    half = z * math.sqrt((rate*(1-rate) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def _transfer(rows: list[dict], calibration_rows: list[dict], models: dict,
              calibration: dict) -> dict:
    panel = _evaluation_panel_compatibility(
        rows, "lot_id", MODEL_FACTORS, PRECOMMIT["exact_setting_panel"], 1)
    composition = _partition_composition_diagnostic(
        {"CALIBRATION": calibration_rows, "EVALUATION": rows},
        "lot_id", ["tool_id", "event_year"], "CALIBRATION", "EVALUATION")
    band = _evaluate_calibration_band_transfer(
        rows, "lot_id", models, MODEL_FACTORS, {}, calibration)
    return _calibration_transfer_assessment(
        "AVAILABLE", panel, composition, True, "CALIBRATION", "EVALUATION", band)


def run_benchmark(trials: int = 250, seed: int = 20261123,
                  calibration_units: int = 39, evaluation_units: int = 24) -> dict:
    if trials < 100 or calibration_units < 19 or evaluation_units < 10:
        raise ValueError("requires at least 100 trials, 19 calibration units, and 10 evaluation units")
    rng = random.Random(seed)

    # Freeze the model once on an independent training sample, before creating
    # any trial calibration/evaluation outcomes.
    training_rows = _panel_rows(rng, 60, "TRAIN", "TRAIN")
    reports, model = fit_linear_model(
        training_rows, FACTORS, "quality",
        {"quadratic": True, "interactions": True,
         "covariance": "cluster", "cluster_field": "lot_id",
         "minimum_clusters": 30})
    if model is None or reports.get("status") != "VALID":
        raise RuntimeError(f"independent training model did not qualify: {reports}")
    models = {"quality": model}

    rates_by_amplitude = {amplitude: [] for amplitude in DRIFT_AMPLITUDES}
    miss_units_by_amplitude = {amplitude: 0 for amplitude in DRIFT_AMPLITUDES}
    scored_units_by_amplitude = {amplitude: 0 for amplitude in DRIFT_AMPLITUDES}
    counterevidence_trials_by_amplitude = {amplitude: 0 for amplitude in DRIFT_AMPLITUDES}
    status_counts_by_amplitude = {amplitude: {} for amplitude in DRIFT_AMPLITUDES}
    exact_panel_trials = 0
    declared_composition_match_trials = 0

    for trial in range(trials):
        calibration_rows = _panel_rows(
            rng, calibration_units, f"CAL-{trial:04d}", "CALIBRATION")
        calibration = _simultaneous_exact_setting_calibration(
            calibration_rows, ["quality"], models, MODEL_FACTORS, {}, "lot_id", PRECOMMIT,
            PRECOMMIT["metric_bounds"])
        if calibration.get("status") != "AVAILABLE":
            raise RuntimeError(f"finite exact-panel calibration unavailable at trial {trial}: {calibration}")

        # Paired held-out rows share the same random variation. Only the hidden
        # chamber response surface changes; tool/year strata and panel structure
        # remain identical to calibration in every arm.
        base_rng = random.Random(rng.getrandbits(64))
        base_rows = _panel_rows(base_rng, evaluation_units, f"EVAL-{trial:04d}", "EVALUATION")
        for amplitude in DRIFT_AMPLITUDES:
            scenario_rows = base_rows if amplitude == 0.0 else _apply_response_drift(base_rows, amplitude)
            assessment = _transfer(scenario_rows, calibration_rows, models, calibration)
            band = assessment["heldout_band_evaluation"]
            if band.get("complete_panel_units") != evaluation_units:
                raise RuntimeError(f"evaluation panel was not scored completely at amplitude {amplitude}: {band}")
            if assessment["evaluation_panel_status"] != "DESCRIPTIVE_PANEL_STRUCTURE_MATCH":
                raise RuntimeError(f"exact panel was not recognized at amplitude {amplitude}: {assessment}")
            if assessment["calibration_to_evaluation_total_variation"] != 0.0:
                raise RuntimeError(f"declared strata unexpectedly changed at amplitude {amplitude}: {assessment}")
            rates_by_amplitude[amplitude].append(float(band["missed_any_interval_fraction"]))
            miss_units_by_amplitude[amplitude] += int(band["missed_any_interval_units"])
            scored_units_by_amplitude[amplitude] += int(band["complete_panel_units"])
            counterevidence_trials_by_amplitude[amplitude] += int(
                assessment["status"] == "COUNTEREVIDENCE_CALIBRATION_BAND_MISSES")
            status = assessment["status"]
            status_counts_by_amplitude[amplitude][status] = (
                status_counts_by_amplitude[amplitude].get(status, 0) + 1)
        exact_panel_trials += 1
        declared_composition_match_trials += 1

    matched_trial_rates = rates_by_amplitude[0.0]
    drift_trial_rates = rates_by_amplitude[0.19]
    differences = [drift - matched for drift, matched in zip(drift_trial_rates, matched_trial_rates)]
    positive_differences = sum(value > 0 for value in differences)
    matched_mean = statistics.mean(matched_trial_rates)
    drift_mean = statistics.mean(drift_trial_rates)
    difference_mean = statistics.mean(differences)
    sorted_differences = sorted(differences)
    quantile = lambda p: sorted_differences[min(len(sorted_differences)-1, int(p*(len(sorted_differences)-1)))]
    sensitivity = {}
    for amplitude in DRIFT_AMPLITUDES:
        rates = rates_by_amplitude[amplitude]
        sensitivity[f"{amplitude:.3f}"] = {
            "mean_trial_level_interval_miss_fraction": statistics.mean(rates),
            "trial_level_standard_deviation": statistics.stdev(rates),
            "aggregate_descriptive_unit_miss_fraction": (
                miss_units_by_amplitude[amplitude] / scored_units_by_amplitude[amplitude]),
            "counterevidence_trials": counterevidence_trials_by_amplitude[amplitude],
            "counterevidence_trial_fraction": counterevidence_trials_by_amplitude[amplitude] / trials,
            "transfer_status_counts": dict(sorted(status_counts_by_amplitude[amplitude].items())),
            "units_are_not_treated_as_independent_for_monte_carlo_uncertainty": True,
        }

    source = ROOT / "products" / "p4" / "window.py"
    script = Path(__file__)
    return {
        "schema": "p4-d02-response-drift-benchmark/v1",
        "method": "paired independent-trial Monte Carlo; production finite-panel calibration and held-out transfer evaluator; known response-surface oracle",
        "generator": "nonlinear two-factor surface with lot intercept/slope correlation; evaluation chamber introduces pressure-by-factor response drift while declared tool/time labels and exact panel remain unchanged",
        "seed": seed,
        "trials": trials,
        "calibration_units_per_trial": calibration_units,
        "evaluation_units_per_trial_and_arm": evaluation_units,
        "exact_settings_per_unit": len(SETTINGS),
        "declared_strata": {"tool_id": "TOOL-A", "event_year": 2026},
        "evaluation_panel_and_strata_match_trials": exact_panel_trials,
        "zero_declared_composition_distance_trials": declared_composition_match_trials,
        "response_drift_sensitivity_by_surface_change_amplitude": sensitivity,
        "matched_response": sensitivity["0.000"],
        "hidden_response_drift": sensitivity["0.190"],
        "paired_drift_minus_matched_trial_miss_fraction": {
            "mean": difference_mean,
            "standard_deviation": statistics.stdev(differences),
            "percentile_2_5": quantile(0.025),
            "percentile_97_5": quantile(0.975),
            "fraction_trials_positive": positive_differences / trials,
            "wilson95_positive_trial_fraction": _wilson(positive_differences, trials),
        },
        "product_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "limitations": [
            "the model, noise, hidden chamber drift, and synthetic precommit are known to the evaluator",
            "paired independent trials, rather than evaluation lots pooled across trials, are the Monte Carlo comparison units",
            "held-out miss rates are descriptive counterevidence; they do not validate exchangeability or conditional coverage",
            "same observed tool/time composition and exact panel cannot rule out unmeasured process drift",
            "this challenge does not qualify production data, a process window, a target population, or future performance",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    drift = result["hidden_response_drift"]
    matched = result["matched_response"]
    paired = result["paired_drift_minus_matched_trial_miss_fraction"]
    if (result["trials"] < 100
            or result["evaluation_panel_and_strata_match_trials"] != result["trials"]
            or result["zero_declared_composition_distance_trials"] != result["trials"]
            or drift["mean_trial_level_interval_miss_fraction"]
                < matched["mean_trial_level_interval_miss_fraction"] + 0.20
            or paired["fraction_trials_positive"] < 0.90
            or drift["counterevidence_trial_fraction"] < 0.90):
        raise SystemExit("same-strata hidden-response-drift challenge did not meet its frozen separation criteria")
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
