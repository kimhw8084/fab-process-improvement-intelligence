"""Held-out challenge: detect stratum-local nonlinear drift diluted by pooling."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from products.p4.window import (_evaluate_calibration_band_transfer,
                                _simultaneous_exact_setting_calibration)

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = (0.0, 1.0, 2.0)
PLAN = {
    "plan_reference": "SYNTHETIC-FIXED-D02-SUBGROUP-PLAN-v1",
    "model_selection_reference": "SYNTHETIC-FROZEN-ZERO-MODEL-v1",
    "threshold_selection_reference": "SYNTHETIC-FROZEN-D02-THRESHOLD-v1",
    "metric_family": ["quality"],
    "metric_bounds": {"quality": {"min": -1000.0, "max": 1000.0}},
    "exact_setting_panel": [{"pressure": setting} for setting in SETTINGS],
    "strata": {"fields": ["tool_id"], "categories": [{"tool_id": "A"}, {"tool_id": "B"}]},
}


class ZeroModel:
    @staticmethod
    def predict(_factors, _fixed_effects=None):
        return {"estimate": 0.0}


def _unit_rows(rng: random.Random, unit: str, tool: str, evaluation: bool) -> list[dict]:
    rows = []
    for pressure in SETTINGS:
        # A hidden tool-specific quadratic response drift appears only after
        # calibration. The observed tool mix and exact panel remain unchanged.
        drift = 1.5 * pressure * pressure if evaluation and tool == "B" else 0.0
        rows.append({"lot_id": unit, "tool_id": tool, "factors": {"pressure": pressure},
                     "metrics": {"quality": rng.gauss(0.0, 1.0) + drift}})
    return rows


def _oracle(rows: list[dict], radius: float) -> dict[str, dict[str, int]]:
    """Independent direct grouping and max-score calculation, not P4 output parsing."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["lot_id"], []).append(row)
    counts: dict[str, dict[str, int]] = {}
    for unit_rows in grouped.values():
        tool = unit_rows[0]["tool_id"]
        summary = counts.setdefault(tool, {"units": 0, "misses": 0})
        summary["units"] += 1
        if max(abs(row["metrics"]["quality"]) for row in unit_rows) > radius:
            summary["misses"] += 1
    return counts


def run_benchmark(seed: int = 20261124, calibration_units_per_stratum: int = 39,
                  evaluation_a_units: int = 5000, evaluation_b_units: int = 100) -> dict:
    if calibration_units_per_stratum < 39 or evaluation_a_units < 500 or evaluation_b_units < 50:
        raise ValueError("challenge requires >=39 calibration units/stratum, >=500 A and >=50 B evaluation units")
    rng = random.Random(seed)
    calibration_rows = [row for tool in ("A", "B")
                        for i in range(calibration_units_per_stratum)
                        for row in _unit_rows(rng, f"CAL-{tool}-{i:03d}", tool, False)]
    calibration = _simultaneous_exact_setting_calibration(
        calibration_rows, ["quality"], {"quality": ZeroModel()}, ["pressure"], {},
        "lot_id", PLAN, PLAN["metric_bounds"])
    if calibration.get("status") != "AVAILABLE":
        raise RuntimeError(f"independent fixed-panel calibration failed: {calibration}")

    evaluation_rows = [row for tool, count in (("A", evaluation_a_units), ("B", evaluation_b_units))
                       for i in range(count)
                       for row in _unit_rows(rng, f"EVAL-{tool}-{i:05d}", tool, True)]
    result = _evaluate_calibration_band_transfer(
        evaluation_rows, "lot_id", {"quality": ZeroModel()}, ["pressure"], {}, calibration)
    radius = calibration["metric_quantiles"]["quality"]["absolute_error_radius"]
    oracle = _oracle(evaluation_rows, radius)
    observed = {item["category"]["tool_id"]: item
                for item in result["by_predeclared_stratum"]["categories"]}
    if result["status"] != "DESCRIPTIVE_HELDOUT_BAND_EVALUATION":
        raise SystemExit(f"evaluation did not score its fixed panel: {result['status']}")
    for tool in ("A", "B"):
        if observed[tool]["complete_panel_units"] != oracle[tool]["units"]:
            raise SystemExit(f"P4 subgroup denominator differs from independent oracle for {tool}")
        if observed[tool]["missed_any_interval_units"] != oracle[tool]["misses"]:
            raise SystemExit(f"P4 subgroup miss count differs from independent oracle for {tool}")
    aggregate = result["missed_any_interval_fraction"]
    a_rate = oracle["A"]["misses"] / oracle["A"]["units"]
    b_rate = oracle["B"]["misses"] / oracle["B"]["units"]
    if not (aggregate < 0.10 and a_rate < 0.10 and b_rate >= 0.90 and b_rate-aggregate >= 0.70):
        raise SystemExit(f"subgroup dilution challenge was not reproduced: aggregate={aggregate}, A={a_rate}, B={b_rate}")
    return {
        "schema": "p4-d02-subgroup-misses-benchmark/v1",
        "status": "PASS",
        "benchmark": "D02_HELDOUT_NONLINEAR_STRATUM_LOCAL_DRIFT",
        "seed": seed,
        "calibration_units_per_stratum": calibration_units_per_stratum,
        "evaluation_units": {"A": evaluation_a_units, "B": evaluation_b_units},
        "generator": "frozen zero model; iid normal calibration errors; same complete three-setting panel and 50:1 evaluation mix; held-out B-only quadratic mean drift 1.5*pressure^2",
        "independent_oracle": "direct unit grouping and maximum absolute exact-panel residual; equality checked against every P4 stratum count",
        "independent_oracle_counts": oracle,
        "calibration_radius": radius,
        "heldout_miss_fractions": {"pooled": aggregate, "A": a_rate, "B": b_rate},
        "p4_diagnostic": result["by_predeclared_stratum"],
        "limitations": [
            "fixed synthetic generator; not an estimate of fab-population performance",
            "stratum labels and exchangeability are caller-supplied and unauthenticated",
            "held-out misses are descriptive counterevidence, not conditional coverage validation",
            "the evaluation partition does not alter calibration or select candidate subsets",
        ],
        "product_source_sha256": hashlib.sha256((ROOT / "products/p4/window.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
