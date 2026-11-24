"""Adversarial known-surface challenge for the actual P4 D02 grid selector.

The observed design uses only the 3x3 integer grid. A randomly selected odd
harmonic interaction is identically zero at those training/calibration
settings but can be nonzero between them. Each trial invokes
products.p4.window.explore_window directly, with independent lot groups for
model fitting and local calibration. The benchmark then scores screened cells
against the known latent surface, which is not supplied to P4.

This is a model-form/interpolation stress diagnostic. It is not a manufacturing
failure-rate estimate, a coverage claim, or evidence that any recipe is safe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from products.p4.window import explore_window


ROOT = Path(__file__).resolve().parents[1]
LEVELS = (0.0, 1.0, 2.0)
GRID_POINTS = 9
LIMIT = 0.15
FACTOR_DEFS = {
    "pressure": {"role": "controllable", "unit": "synthetic-kPa", "bounds": [0, 2], "approved": True},
    "power": {"role": "controllable", "unit": "synthetic-W", "bounds": [0, 2], "approved": True},
}
METRIC_DEFS = {"quality": {"unit": "synthetic-score", "direction": "minimize", "max": LIMIT}}
ANALYSIS_TEMPLATE = {
    "model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
              "quadratic": True, "interactions": True},
    "window_exploration": {
        "factors": ["pressure", "power"], "independent_unit_field": "lot_id",
        "min_independent_units": 30, "grid_points": GRID_POINTS,
        "min_support_points": 3, "max_support_radius": 0.65,
        "calibration": {"group_field": "lot_id", "partition_field": "partition",
                        "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                        "minimum_calibration_units": 19,
                        "split_reference": "FROZEN-D02-ACTUAL-SELECTOR-CHALLENGE"},
    },
}


def _wilson(successes: int, trials: int) -> list[float] | None:
    if trials <= 0:
        return None
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    half = z * math.sqrt((rate * (1 - rate) + z * z / (4 * trials)) / trials) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def _latent_quality(pressure: float, power: float, amplitude: float, frequency_p: int, frequency_w: int) -> float:
    smooth_baseline = 0.10 + 0.04 * ((pressure - 1.0) ** 2 + (power - 1.0) ** 2)
    omitted_interaction = (amplitude * math.sin(frequency_p * math.pi * pressure)
                           * math.sin(frequency_w * math.pi * power))
    return smooth_baseline + omitted_interaction


def _one_trial(trial_seed: int) -> dict:
    rng = random.Random(trial_seed)
    amplitude = rng.uniform(0.03, 0.11) * rng.choice((-1.0, 1.0))
    frequency_p = rng.choice((1, 3, 5))
    frequency_w = rng.choice((1, 3, 5))
    rows = []
    for lot in range(50):
        partition = "TRAIN" if lot < 30 else "CALIBRATION"
        lot_effect = rng.gauss(0.0, 0.008)
        for pressure in LEVELS:
            for power in LEVELS:
                mean = _latent_quality(pressure, power, amplitude, frequency_p, frequency_w)
                rows.append({
                    "id": f"D02-ACTUAL-{trial_seed}-{lot}-{pressure}-{power}",
                    "factors": {"pressure": pressure, "power": power},
                    "metrics": {"quality": mean + lot_effect + rng.gauss(0.0, 0.003)},
                    "lot_id": f"D02-ACTUAL-{trial_seed}-LOT-{lot:02d}",
                    "partition": partition,
                })

    # No evaluation partition is supplied: it cannot affect fitting, calibration,
    # or selection. The latent function below is the separate independent oracle.
    result = explore_window(rows, FACTOR_DEFS, METRIC_DEFS, ANALYSIS_TEMPLATE)
    if result.get("status") not in ("VALID", "INCONCLUSIVE"):
        raise RuntimeError(f"actual D02 selector returned an unexpected state: {result.get('status')}")
    candidates = result.get("candidate_cells", [])
    interpolated = [cell for cell in candidates if cell.get("region_class") == "interpolated"]
    observed = [cell for cell in candidates if cell.get("region_class") == "observed"]
    interpolated_screened = [cell for cell in result.get("grid", [])
                             if cell.get("screened_candidate") and cell.get("region_class") == "interpolated"]
    action_consistent = all(
        cell.get("candidate_review_status") == "MODEL_INTERPOLATION_ADVISORY_REQUIRES_EXACT_CONFIRMATION"
        and cell.get("required_engineer_action") == "PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS"
        for cell in interpolated_screened)

    def failing(cells: list[dict]) -> list[dict]:
        return [cell for cell in cells
                if _latent_quality(cell["factors"]["pressure"], cell["factors"]["power"],
                                  amplitude, frequency_p, frequency_w) > LIMIT]

    failing_candidates = failing(candidates)
    failing_interpolated = failing(interpolated)
    center = next((cell for cell in result.get("grid", [])
                   if cell.get("factors") == {"pressure": 1.0, "power": 1.0}), None)
    if center is None:
        raise RuntimeError("actual D02 grid did not contain the predeclared center setting")
    center_selected = center.get("screened_candidate") is True
    center_false_feasible = center_selected and _latent_quality(1.0, 1.0, amplitude,
                                                                 frequency_p, frequency_w) > LIMIT
    return {
        "candidate_count": len(candidates),
        "observed_candidate_count": len(observed),
        "interpolated_candidate_count": len(interpolated),
        "false_feasible_candidate_count": len(failing_candidates),
        "false_feasible_interpolated_count": len(failing_interpolated),
        "any_false_feasible_candidate": bool(failing_candidates),
        "any_false_feasible_interpolation": bool(failing_interpolated),
        "predeclared_center_selected": center_selected,
        "predeclared_center_false_feasible": center_false_feasible,
        "interpolated_review_action_consistent": action_consistent,
        "harmonic_amplitude": amplitude,
        "harmonic_frequencies": [frequency_p, frequency_w],
    }


def run_benchmark(trials: int = 250, seed: int = 20261123) -> dict:
    if trials < 1:
        raise ValueError("at least one trial is required")
    outcomes = [_one_trial(seed + trial) for trial in range(trials)]
    any_selected = sum(item["candidate_count"] > 0 for item in outcomes)
    any_false = sum(item["any_false_feasible_candidate"] for item in outcomes)
    any_false_interpolated = sum(item["any_false_feasible_interpolation"] for item in outcomes)
    center_selected = sum(item["predeclared_center_selected"] for item in outcomes)
    center_false = sum(item["predeclared_center_false_feasible"] for item in outcomes)
    action_consistent = sum(item["interpolated_review_action_consistent"] for item in outcomes)
    candidate_total = sum(item["candidate_count"] for item in outcomes)
    interpolated_total = sum(item["interpolated_candidate_count"] for item in outcomes)
    false_candidate_total = sum(item["false_feasible_candidate_count"] for item in outcomes)
    false_interpolated_total = sum(item["false_feasible_interpolated_count"] for item in outcomes)
    return {
        "schema": "p4-d02-actual-selector-interpolation-benchmark/v1",
        "status": "DIAGNOSTIC_COMPLETE",
        "method": "direct invocation of products.p4.window.explore_window with its local grouped calibration and candidate screen",
        "generator": "random signed odd-harmonic interaction; zero at all 3x3 observed settings, variable between settings; independent Gaussian lot and observation noise",
        "seed": seed,
        "trials": trials,
        "observed_settings": [list(setting) for setting in [(x, y) for x in LEVELS for y in LEVELS]],
        "grid_points_per_axis": GRID_POINTS,
        "training_lots_per_trial": 30,
        "calibration_lots_per_trial": 20,
        "evaluation_partition_supplied_to_product": False,
        "independent_oracle": "known latent response function evaluated at every P4-selected cell after selection; never supplied to the product",
        "required_candidate_scope": "MODEL_BASED_ADVISORY_SCREENING_ONLY",
        "interpolated_review_action_consistent_trials": action_consistent,
        "predeclared_baseline": {"setting": {"pressure": 1.0, "power": 1.0},
                                 "screen": "same P4 local interval at this fixed exact observed setting",
                                 "selected_trials": center_selected,
                                 "false_feasible_trials": center_false,
                                 "false_feasible_trial_rate": center_false / trials,
                                 "wilson95": _wilson(center_false, trials)},
        "actual_p4_candidate_family": {
            "selected_trials": any_selected,
            "trials_with_any_latent_mean_above_limit": any_false,
            "any_false_feasible_trial_rate": any_false / trials,
            "any_false_feasible_trial_wilson95": _wilson(any_false, trials),
            "trials_with_interpolated_latent_mean_above_limit": any_false_interpolated,
            "interpolation_false_feasible_trial_rate": any_false_interpolated / trials,
            "interpolation_false_feasible_trial_wilson95": _wilson(any_false_interpolated, trials),
            "mean_candidate_cells": statistics.mean(item["candidate_count"] for item in outcomes),
            "mean_interpolated_candidate_cells": statistics.mean(item["interpolated_candidate_count"] for item in outcomes),
            "candidate_cell_false_feasible_fraction": false_candidate_total / candidate_total if candidate_total else None,
            "interpolated_cell_false_feasible_fraction": false_interpolated_total / interpolated_total if interpolated_total else None,
            "scope": "pre-independent-confirmation model screen; known synthetic latent mean violations, not observed production risk",
        },
        "product_window_sha256": hashlib.sha256((ROOT / "products/p4/window.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "deliberately omitted high-frequency interactions are outside the quadratic response model",
            "all results are synthetic and generator-specific; no manufacturing failure-rate or coverage claim",
            "the exact center baseline is guaranteed feasible by this challenge construction and is not a general product comparison",
            "an independent exact-setting confirmation is required before any process decision; the product is advisory and read-only",
        ],
        "trial_summaries": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path, default=ROOT / "qualification/results/D02_ACTUAL_SELECTOR_INTERPOLATION.json")
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "output": str(args.output), "trials": result["trials"],
        "actual_selector_false_feasible_rate": result["actual_p4_candidate_family"]["any_false_feasible_trial_rate"],
        "interpolation_false_feasible_rate": result["actual_p4_candidate_family"]["interpolation_false_feasible_trial_rate"],
        "predeclared_center_false_feasible_rate": result["predeclared_baseline"]["false_feasible_trial_rate"],
        "mean_candidate_cells": result["actual_p4_candidate_family"]["mean_candidate_cells"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
