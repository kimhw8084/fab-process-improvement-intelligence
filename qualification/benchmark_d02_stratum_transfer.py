"""Independent held-out challenge for D02 tool/time calibration transfer.

Calibration lots have a 90:10 Tool-A/Tool-B mixture. Future evaluation lots
come from (1) the same mixture, (2) a shifted mixture over known strata, or
(3) a mixture containing a new Tool-C/2027 stratum. Lot residuals are
correlated across nine exact settings and their scale depends on stratum.
The coverage oracle is a direct split-conformal maximum-score calculation;
product diagnostics are used only to verify descriptive transfer statuses.
This synthetic challenge does not establish any manufacturing guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from products.p4.window import (
    _calibration_transfer_assessment,
    _evaluation_panel_compatibility,
    _partition_composition_diagnostic,
)


SETTINGS = [(float(x), float(y)) for x in (0, 1, 2) for y in (0, 1, 2)]
STRATA = {
    "A": {"tool_id": "TOOL-A", "event_year": 2026, "scale": 1.0},
    "B": {"tool_id": "TOOL-B", "event_year": 2026, "scale": 4.0},
    "C": {"tool_id": "TOOL-C", "event_year": 2027, "scale": 6.0},
}
SCENARIOS = {
    "same_known_mix": {"A": 0.90, "B": 0.10},
    "shifted_known_mix": {"A": 0.10, "B": 0.90},
    "unseen_tool_period": {"A": 0.05, "B": 0.05, "C": 0.90},
}


def _draw_stratum(rng: random.Random, probabilities: dict[str, float]) -> str:
    draw = rng.random()
    cumulative = 0.0
    for key, probability in probabilities.items():
        cumulative += probability
        if draw < cumulative:
            return key
    return next(reversed(probabilities))


def _panel(rng: random.Random, unit: str, partition: str, stratum: str):
    spec = STRATA[stratum]
    scale = spec["scale"]
    common_lot_shock = rng.gauss(0.0, 0.6 * scale)
    rows = []
    scores = []
    for x, y in SETTINGS:
        residual = common_lot_shock + rng.gauss(0.0, 0.8 * scale)
        scores.append(abs(residual))
        rows.append({
            "id": f"{unit}-{x:g}-{y:g}",
            "lot_id": unit,
            "partition": partition,
            "tool_id": spec["tool_id"],
            "event_year": spec["event_year"],
            "factors": {"pressure": x, "power": y},
            "metrics": {"residual": residual},
        })
    return rows, max(scores)


def _sample_panel_set(rng: random.Random, count: int, prefix: str, partition: str,
                      probabilities: dict[str, float]):
    rows, scores, labels = [], [], []
    for index in range(count):
        label = _draw_stratum(rng, probabilities)
        unit_rows, score = _panel(rng, f"{prefix}-{index:03d}", partition, label)
        rows.extend(unit_rows)
        scores.append(score)
        labels.append(label)
    return rows, scores, labels


def _wilson(successes: int, trials: int):
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1 + z*z/trials
    center = (proportion + z*z/(2*trials)) / denominator
    half = z * math.sqrt((proportion*(1-proportion) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def run_benchmark(trials: int = 1000, seed: int = 20261123,
                  calibration_units: int = 39, evaluation_units: int = 40):
    if trials < 500 or calibration_units < 19 or evaluation_units < 10:
        raise ValueError("benchmark requires 500 trials, 19 calibration units, and 10 evaluation units")
    rng = random.Random(seed)
    target = 0.95
    rank = math.ceil((calibration_units + 1) * target)
    coverage = Counter()
    covered = Counter()
    statuses = {name: Counter() for name in SCENARIOS}
    mean_tv = Counter()
    for trial in range(trials):
        calibration_rows, calibration_scores, _ = _sample_panel_set(
            rng, calibration_units, f"CAL-{trial:04d}", "CALIBRATION", SCENARIOS["same_known_mix"])
        radius = sorted(calibration_scores)[rank - 1]
        for scenario, probabilities in SCENARIOS.items():
            evaluation_rows, evaluation_scores, _ = _sample_panel_set(
                rng, evaluation_units, f"EVAL-{trial:04d}-{scenario}", "EVALUATION", probabilities)
            for score in evaluation_scores:
                coverage[scenario] += 1
                covered[scenario] += int(score <= radius)

            composition = _partition_composition_diagnostic(
                {"CALIBRATION": calibration_rows, "EVALUATION": evaluation_rows},
                "lot_id", ["tool_id", "event_year"], "CALIBRATION", "EVALUATION")
            panel = _evaluation_panel_compatibility(
                evaluation_rows, "lot_id", ["pressure", "power"],
                [{"pressure": x, "power": y} for x, y in SETTINGS], 1)
            assessment = _calibration_transfer_assessment(
                "AVAILABLE", panel, composition, True, "CALIBRATION", "EVALUATION")
            statuses[scenario][assessment["status"]] += 1
            comparison = next((item for item in composition["comparisons"]
                               if item["from_partition"] == "CALIBRATION"
                               and item["to_partition"] == "EVALUATION"), None)
            if comparison and comparison["categorical_total_variation_distance"] is not None:
                mean_tv[scenario] += comparison["categorical_total_variation_distance"]

    scenarios = {}
    for name in SCENARIOS:
        scenarios[name] = {
            "evaluation_mix": SCENARIOS[name],
            "covered_future_independent_units": covered[name],
            "future_independent_units": coverage[name],
            "coverage": covered[name] / coverage[name],
            "wilson95": _wilson(covered[name], coverage[name]),
            "mean_observed_calibration_evaluation_total_variation": mean_tv[name] / trials,
            "transfer_status_counts": dict(sorted(statuses[name].items())),
        }
    source = ROOT / "products" / "p4" / "window.py"
    script = Path(__file__)
    return {
        "schema": "p4-d02-stratum-transfer-benchmark/v1",
        "method": "independent split-conformal order-statistic oracle over within-lot maximum absolute residual across nine exact settings",
        "generator": "independent lots; Gaussian lot-common and setting-specific residual components; scale 1/4/6 by tool-period stratum",
        "calibration_mix": SCENARIOS["same_known_mix"],
        "calibration_units": calibration_units,
        "evaluation_units_per_trial_and_scenario": evaluation_units,
        "exact_settings": len(SETTINGS),
        "target_marginal_panel_coverage": target,
        "order_statistic_rank": rank,
        "trials": trials,
        "seed": seed,
        "scenarios": scenarios,
        "product_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "limitations": [
            "all outcomes and strata are synthetic and the generator is known to the evaluator",
            "Wilson intervals treat generated future units as independent Bernoulli coverage outcomes within this fixed generator",
            "descriptive composition and panel statuses are counterevidence screens, not tests or certificates of exchangeability",
            "matching observed composition never validates future conditional or population coverage",
            "the benchmark does not qualify a manufacturing tool, period, process, or future sampling plan",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    same = result["scenarios"]["same_known_mix"]["coverage"]
    shifted = result["scenarios"]["shifted_known_mix"]["coverage"]
    unseen = result["scenarios"]["unseen_tool_period"]["coverage"]
    unseen_status = result["scenarios"]["unseen_tool_period"]["transfer_status_counts"]
    if (same < 0.90 or shifted >= same - 0.10 or unseen >= shifted - 0.20
            or unseen_status.get("COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA", 0) < int(args.trials * 0.90)):
        raise SystemExit("stratum-transfer challenge failed to separate fixed scenarios")
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
