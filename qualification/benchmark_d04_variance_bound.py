"""Stress D04 planning power when paired SD is estimated from a small history.

Historical pairs are independent normal differences with true SD 1.0. The
baseline uses the observed sample SD as if known. The qualified-input path uses
the one-sided chi-square upper confidence limit (SciPy qualification oracle),
then the same P4 sample-size rule. Exact achieved power is measured with the
noncentral-t distribution. No generated values represent FAB data.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import scipy
from scipy.stats import chi2, nct, t

from products.p4.design import _confirmation_t_critical


def _required_pairs(planning_sd: float, mde: float, alpha: float, target: float) -> int:
    distribution = NormalDist()
    z_alpha = distribution.inv_cdf(1-alpha/2)
    z_power = distribution.inv_cdf(target)
    normal_pairs = max(2, math.ceil(((z_alpha+z_power)*planning_sd/mde)**2))
    for pair_count in range(max(11, normal_pairs), 100_001):
        critical = _confirmation_t_critical(1-alpha/2, pair_count-1)
        if (mde/planning_sd)*math.sqrt(pair_count) >= critical+z_power:
            return pair_count+1
    raise RuntimeError("pair search exceeded qualification bound")


def _achieved_power(pairs: int, true_sd: float, mde: float, alpha: float) -> float:
    df = pairs-1
    critical = float(t.ppf(1-alpha/2, df))
    noncentrality = mde/true_sd*math.sqrt(pairs)
    return float(nct.cdf(-critical, df, noncentrality) + nct.sf(critical, df, noncentrality))


def _wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes/total
    den = 1+z*z/total
    center = (p+z*z/(2*total))/den
    half = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [center-half, center+half]


def run(trials: int = 2000, seed: int = 20261123) -> dict:
    rng = np.random.default_rng(seed)
    true_sd, mde, alpha, target, confidence = 1.0, 0.5, 0.05, 0.8, 0.95
    scenarios = []
    for historical_df in (5, 10, 30, 100):
        underpowered = {"point_estimate_as_known": 0, "one_sided_upper_bound": 0}
        pair_counts = {"point_estimate_as_known": [], "one_sided_upper_bound": []}
        upper_quantile = float(chi2.ppf(1-confidence, historical_df))
        for _ in range(trials):
            sd_estimate = true_sd*math.sqrt(float(rng.chisquare(historical_df))/historical_df)
            sd_upper = sd_estimate*math.sqrt(historical_df/upper_quantile)
            plans = {
                "point_estimate_as_known": _required_pairs(sd_estimate, mde, alpha, target),
                "one_sided_upper_bound": _required_pairs(sd_upper, mde, alpha, target),
            }
            for method, pairs in plans.items():
                achieved = _achieved_power(pairs, true_sd, mde, alpha)
                underpowered[method] += int(achieved+1e-12 < target)
                pair_counts[method].append(pairs)
        scenarios.append({
            "historical_sd_degrees_of_freedom": historical_df,
            "trials": trials,
            "sd_upper_bound_multiplier_on_sample_sd": math.sqrt(historical_df/upper_quantile),
            "methods": {
                method: {"underpowered_plans": count,
                         "underpowered_fraction": count/trials,
                         "underpowered_wilson95": _wilson(count, trials),
                         "mean_complete_pairs": sum(pair_counts[method])/trials,
                         "median_complete_pairs": float(np.median(pair_counts[method]))}
                for method, count in underpowered.items()
            },
        })
    return {
        "schema": "p4-d04-variance-bound-benchmark/v1",
        "seed": seed,
        "generator": {"historical_paired_differences": "independent normal",
                      "true_sd": true_sd, "MDE": mde, "alpha": alpha,
                      "target_power": target, "upper_bound_confidence": confidence,
                      "historical_df_grid": [5, 10, 30, 100]},
        "planner_rule": "P4 three-term Cornish-Fisher critical approximation + normal power tail + one-pair margin",
        "independent_oracle": f"SciPy {scipy.__version__}: chi-square one-sided SD bound and exact Student-t/noncentral-t achieved power",
        "scenarios": scenarios,
        "interpretation": "The P4 planner now accepts only a caller-asserted conservative SD bound. This challenge estimates underpower risk if the input were merely a noisy point SD versus a one-sided 95% normal-theory upper bound; P4 does not compute or authenticate that bound.",
        "scope": "qualification-only synthetic method challenge; not FAB observations or a universal power guarantee",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.trials, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "scenarios"}, indent=2, sort_keys=True))
    for scenario in report["scenarios"]:
        print(json.dumps(scenario, sort_keys=True))


if __name__ == "__main__":
    main()
