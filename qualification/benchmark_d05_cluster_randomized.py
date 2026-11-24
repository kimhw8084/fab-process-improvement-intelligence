#!/usr/bin/env python3
"""Held-out coverage challenge for explicit cluster-randomized inference."""
from __future__ import annotations

import argparse
import hashlib
import json
from math import exp, sqrt
import random
from pathlib import Path
from statistics import variance
import subprocess
import sys

from scipy.stats import t

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from products.p4.engine import _effectiveness


def wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    p = successes / trials
    den = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / den
    half = z * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5) / den
    return [center - half, center + half]


def cluster_shock(rng: random.Random, distribution: str) -> float:
    if distribution == "normal":
        return rng.gauss(0, 1)
    if distribution == "t4_standardized":
        # Student t(4), standardized to unit variance.
        return rng.gauss(0, 1) / (rng.gammavariate(2, 2) ** 0.5)
    if distribution.startswith("lognormal_sigma_"):
        sigma = float(distribution.removeprefix("lognormal_sigma_"))
        expected = exp(sigma * sigma / 2)
        standard_deviation = sqrt((exp(sigma * sigma) - 1) * exp(sigma * sigma))
        return (rng.lognormvariate(0, sigma) - expected) / standard_deviation
    raise ValueError(f"unsupported cluster shock: {distribution}")


def study(trial: int, rng: random.Random, clusters_per_arm: int, distribution: str) -> tuple[dict, list[float], list[float]]:
    rows, ledger = [], []
    arm_means = {"treatment": [], "control": []}
    for group in ("treatment", "control"):
        for cluster_index in range(clusters_per_arm):
            cluster_id = f"SYN-{trial}-{group}-CH-{cluster_index}"
            shock = cluster_shock(rng, distribution)
            outcomes = []
            for lot_index in range(6):
                unit_id = f"SYN-{trial}-{group}-{cluster_index}-{lot_index}"
                outcome = 100 + shock + rng.gauss(0, 0.25)
                outcomes.append(outcome)
                rows.append({"unit_id": unit_id, "group": group, "quality": outcome,
                             "chamber_id": cluster_id})
                ledger.append({"unit_id": unit_id, "group": group,
                               "shared_groups": {"chamber_id": cluster_id}})
            arm_means[group].append(sum(outcomes) / len(outcomes))
    request = {"effectiveness": {
        "authorized": True, "design": "randomized", "randomized": True,
        "intervention_id": "SYN-D05-CLUSTER-TRIAL", "authorization_id": "SYN-D05-CLUSTER-AUTH",
        "randomization_evidence": "SYN-D05-COMPLETE-CLUSTER-RANDOMIZATION",
        "metric": "quality", "assignment_ledger": ledger, "observations": rows,
        "shared_dependence_fields": ["chamber_id"], "randomization_cluster_field": "chamber_id"}}
    return request, arm_means["treatment"], arm_means["control"]


def run(trials_per_case: int = 1000, seed: int = 20261124) -> dict:
    rng = random.Random(seed)
    cases = {}
    distributions = ("normal", "t4_standardized", "lognormal_sigma_0.8", "lognormal_sigma_1.5")
    for distribution in distributions:
        for count in (5, 10, 20):
            covered = oracle_covered = emitted = conservative_intervals = 0
            maximum_anti_conservative_shortfall = 0.0
            for trial_index in range(trials_per_case):
                request, treated, control = study(trial_index, rng, count, distribution)
                result = _effectiveness(request)
                interval = result.get("ci95_welch_t_approximation")
                if result.get("status") != "ESTIMATED" or result.get("inference_unit") != "declared_randomization_cluster":
                    continue
                emitted += 1
                covered += int(interval[0] <= 0 <= interval[1])
                estimate = sum(treated) / len(treated) - sum(control) / len(control)
                a = variance(treated) / len(treated)
                b = variance(control) / len(control)
                se = (a + b) ** 0.5
                denominator = a * a / (len(treated) - 1) + b * b / (len(control) - 1)
                df = (a + b) ** 2 / denominator if denominator else 1000
                radius = float(t.ppf(0.975, df)) * se
                oracle_interval = [estimate - radius, estimate + radius]
                oracle_covered += int(oracle_interval[0] <= 0 <= oracle_interval[1])
                conservative = interval[0] <= oracle_interval[0] and interval[1] >= oracle_interval[1]
                conservative_intervals += int(conservative)
                shortfall = max(0.0, interval[0] - oracle_interval[0], oracle_interval[1] - interval[1])
                maximum_anti_conservative_shortfall = max(maximum_anti_conservative_shortfall, shortfall)
            total = trials_per_case
            key = f"{distribution}_clusters_{count}_per_arm"
            cases[key] = {
                "trials": total, "intervals_emitted": emitted,
                "p4_null_coverage": covered / total, "p4_wilson95": wilson(covered, total),
                "scipy_t_quantile_oracle_coverage": oracle_covered / total,
                "oracle_wilson95": wilson(oracle_covered, total),
                "oracle_interval_contained_count": conservative_intervals,
                "maximum_anti_conservative_shortfall": maximum_anti_conservative_shortfall,
                "cluster_estimand": "equal-weight average outcome across randomized clusters",
            }
    expected_cases = {f"{distribution}_clusters_{count}_per_arm"
                      for distribution in distributions for count in (5, 10, 20)}
    checks = {
        "all_predeclared_distribution_cluster_count_cells_present": set(cases) == expected_cases,
        "every_prequalified_case_emitted_an_interval": all(x["intervals_emitted"] == x["trials"] for x in cases.values()),
        "all_p4_wilson_lower_bounds_above_0_90": all(x["p4_wilson95"][0] > 0.90 for x in cases.values()),
        "all_p4_coverage_within_0_02_of_scipy_oracle": all(
            abs(x["p4_null_coverage"] - x["scipy_t_quantile_oracle_coverage"]) <= 0.02 for x in cases.values()),
        "all_p4_intervals_contain_scipy_oracle_interval": all(
            x["oracle_interval_contained_count"] == x["trials"] for x in cases.values()),
    }
    provenance = {
        "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                         capture_output=True, text=True).stdout.strip(),
        "engine_sha256": hashlib.sha256((ROOT / "products/p4/engine.py").read_bytes()).hexdigest(),
        "regression_sha256": hashlib.sha256((ROOT / "products/p4/regression.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return {
        "schema": "p4-d05-cluster-randomized-benchmark/v1", "trials_per_case": trials_per_case,
        "seed": seed, "cases": cases, "qualification_checks": checks,
        "qualification_status": "PASS" if all(checks.values()) else "FAIL",
        "reference": "independent SciPy Student-t quantile and separately aggregated cluster outcomes",
        "scope": "Synthetic complete balanced cluster-randomized null cases, 5/10/20 independent clusters per arm, normal, standardized t(4), and strongly right-skewed standardized lognormal cluster shocks (sigma 0.8 and 1.5). Equal cluster weighting defines the estimand. This does not establish coverage for informative cluster size, arbitrary dependence, untested cluster distributions, or a manufacturing population.",
        "source_provenance": provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--output", type=Path, default=ROOT / "qualification/results/D05_CLUSTER_RANDOMIZED_BENCHMARK.json")
    args = parser.parse_args()
    result = run(args.trials, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["qualification_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
