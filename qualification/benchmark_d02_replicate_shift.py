"""Independent finite-panel challenge for a shifted observation-count design.

Calibration units have one observation at each of nine exact settings. The
held-out unit has one, two, or four observations per setting. Only the first
scenario preserves the precommitted panel score distribution. This benchmark
isolates row-count shift; it does not model any manufacturing population.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _wilson(successes: int, trials: int):
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z*z/trials
    center = (rate + z*z/(2*trials)) / denominator
    half = z * math.sqrt((rate*(1-rate) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def run_benchmark(trials: int = 5000, seed: int = 20261123,
                  calibration_units: int = 39, exact_settings: int = 9):
    if trials < 1000 or calibration_units < 19 or exact_settings < 2:
        raise ValueError("benchmark requires at least 1,000 trials, 19 calibration units, and 2 settings")
    rng = random.Random(seed)
    target = 0.95
    rank = math.ceil((calibration_units + 1) * target)
    counts = {replicates: 0 for replicates in (1, 2, 4)}
    for _ in range(trials):
        calibration_scores = [
            max(abs(rng.gauss(0.0, 1.0)) for _ in range(exact_settings))
            for _ in range(calibration_units)
        ]
        radius = sorted(calibration_scores)[rank-1]
        for future_replicates in counts:
            future_score = max(abs(rng.gauss(0.0, 1.0))
                               for _ in range(exact_settings * future_replicates))
            counts[future_replicates] += int(future_score <= radius)

    scenarios = {
        str(replicates): {"observations_per_setting": replicates,
                          "covered": covered, "coverage": covered/trials,
                          "wilson95": _wilson(covered, trials),
                          "matches_precommitted_count": replicates == 1}
        for replicates, covered in counts.items()
    }
    window_path = ROOT / "products" / "p4" / "window.py"
    benchmark_path = Path(__file__)
    return {
        "schema": "p4-d02-replicate-shift-benchmark/v1",
        "method": "independent split-conformal maximum absolute normal residual oracle over nine exact settings",
        "generator": "iid standard-normal residuals; 39 independent calibration units and one future unit per trial",
        "seed": seed,
        "trials": trials,
        "calibration_units": calibration_units,
        "calibration_observations_per_setting": 1,
        "exact_settings": exact_settings,
        "order_statistic_rank": rank,
        "target_coverage": target,
        "scenarios": scenarios,
        "product_source_sha256": hashlib.sha256(window_path.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        "limitations": [
            "this is a fixed-generator challenge of panel row-count shift, not process evidence",
            "coverage applies only when calibration and future independent-unit panel structures are exchangeable",
            "the product can diagnose an observed evaluation-panel mismatch but cannot verify an unobserved future sampling plan",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    matching = result["scenarios"]["1"]
    shifted_two = result["scenarios"]["2"]
    shifted_four = result["scenarios"]["4"]
    if (not matching["wilson95"][0] <= 0.95 <= matching["wilson95"][1]
            or shifted_two["coverage"] >= 0.93 or shifted_four["coverage"] >= 0.86):
        raise SystemExit("replicate-shift benchmark failed to reproduce the precommitted coverage challenge")
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
