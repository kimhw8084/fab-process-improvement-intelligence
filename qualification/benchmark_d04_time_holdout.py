#!/usr/bin/env python3
"""Compare random grouped and chronological holdouts under a hidden time shift."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from random import Random
from math import sqrt
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from products.p4.design import propose_design


FACTORS = ["a", "b"]
BOUNDS = {"a": [0.0, 2.0], "b": [0.0, 2.0]}
METRICS = {"quality": {"direction": "maximize"}}
MODEL = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
         "quadratic": True, "interactions": True}


def _wilson(successes: int, trials: int, z: float = 1.959963984540054) -> list[float]:
    proportion = successes/trials
    denominator = 1.0+z*z/trials
    center = (proportion+z*z/(2.0*trials))/denominator
    radius = z*sqrt(proportion*(1.0-proportion)/trials+z*z/(4.0*trials*trials))/denominator
    lower = 0.0 if successes == 0 else max(0.0, center-radius)
    upper = 1.0 if successes == trials else min(1.0, center+radius)
    return [lower, upper]


def _rows(seed: int) -> list[dict]:
    rng = Random(seed)
    rows = []
    for lot in range(36):
        day = lot + 1
        timestamp = f"2026-01-{day:02d}T00:00:00Z" if day <= 31 else f"2026-02-{day-31:02d}T00:00:00Z"
        drift = 0.5 if lot >= 30 else 0.0
        lot_effect = rng.uniform(-0.02, 0.02)
        for a in (0.0, 1.0, 2.0):
            for b in (0.0, 1.0, 2.0):
                response = 10-(a-1)**2-1.5*(b-1)**2+drift+lot_effect+rng.uniform(-0.01, 0.01)
                rows.append({"factors": {"a": a, "b": b}, "metrics": {"quality": response},
                             "lot_id": f"SYN-LOT-{lot:03d}", "event_ts": timestamp})
    return rows


def _spec(seed: int, chronological: bool) -> dict:
    spec = {"run_budget": 1, "seed": seed, "validation_seed": seed,
            "blocks": 1, "target_metric": "quality", "candidate_levels": 9,
            "independent_unit_field": "lot_id", "min_independent_units": 30,
            "maximum_grouped_validation_rmse": 0.2}
    if chronological:
        spec["validation_time_split"] = {
            "timestamp_field": "event_ts", "training_end": "2026-01-30T00:00:00Z",
            "evaluation_start": "2026-01-31T00:00:00Z", "split_reference": "SYN-D04-TIME-BENCHMARK"}
    return spec


def run(trials: int = 30, seed: int = 20261124) -> dict:
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError("trials must be a positive integer")
    outcomes = {"random_group": [], "time_ordered": []}
    for trial in range(trials):
        rows = _rows(seed+trial)
        for mode, chronological in (("random_group", False), ("time_ordered", True)):
            spec = _spec(seed+trial, chronological)
            try:
                proposal = propose_design("next_best", FACTORS, BOUNDS, spec, [], rows, METRICS, MODEL)
                validation = proposal["grouped_surface_validation"]
                outcomes[mode].append({"accepted": proposal["status"] == "PROPOSED",
                                       "evaluation_rmse": validation["independent_evaluation"]["rmse"],
                                       "refusal_reason": None})
            except ValueError as exc:
                match = re.search(r"evaluation error ([0-9.eE+-]+) exceeds", str(exc))
                observed_rmse = float(match.group(1)) if match else None
                reason = "ENGINEER_RMSE_LIMIT_EXCEEDED" if match else "OTHER_REFUSAL"
                outcomes[mode].append({"accepted": False, "evaluation_rmse": observed_rmse,
                                       "refusal_reason": reason})
    summaries = {}
    for mode, values in outcomes.items():
        accepted_count = sum(item["accepted"] for item in values)
        accepted_rmse = [item["evaluation_rmse"] for item in values if item["accepted"]]
        refused_rmse = [item["evaluation_rmse"] for item in values
                        if not item["accepted"] and item["evaluation_rmse"] is not None]
        reasons = {}
        for item in values:
            if item["refusal_reason"]:
                reasons[item["refusal_reason"]] = reasons.get(item["refusal_reason"], 0)+1
        summaries[mode] = {
            "accepted_count": accepted_count,
            "accepted_fraction": accepted_count/trials,
            "accepted_fraction_wilson95": _wilson(accepted_count, trials),
            "mean_reported_rmse_when_accepted": (sum(accepted_rmse)/len(accepted_rmse)
                                                 if accepted_rmse else None),
            "mean_reported_rmse_when_refused_by_limit": (sum(refused_rmse)/len(refused_rmse)
                                                         if refused_rmse else None),
            "maximum_reported_rmse_when_refused_by_limit": max(refused_rmse) if refused_rmse else None,
            "refusal_reason_counts": reasons,
        }
    return {
        "schema": "p4-d04-time-holdout-benchmark/v1",
        "seed": seed,
        "trials": trials,
        "generator": "known quadratic surface with independent lot noise and a +0.5 late-period shift on the final 6 of 36 lots",
        "acceptance_threshold_rmse": 0.2,
        "comparison": summaries,
        "interpretation": "Random group holdouts can mix future-shifted lots into development and evaluation; chronological holdout tests transfer to the supplied later period only. Split boundaries and reference are caller supplied and unauthenticated.",
        "scope": "synthetic software qualification; no manufacturing performance or future guarantee",
        "product_source_sha256": hashlib.sha256((ROOT/"products/p4/design.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "qualification": "PASS" if summaries["time_ordered"]["accepted_count"] == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--output", type=Path, default=ROOT/"qualification/results/D04_TIME_HOLDOUT_BENCHMARK.json")
    args = parser.parse_args()
    result = run(args.trials, args.seed)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["qualification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
