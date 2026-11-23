"""Independent size-of-test stress for a cluster field that splits lots.

Uses statsmodels as the covariance reference and a fixed, paired assignment of
one treated and one control lot per chamber-pair. Each lot appears in two
chambers, so chamber clusters are not independent even though there are 40 of
them. This is a method stress generator, not a FAB population model.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import statsmodels
import statsmodels.api as sm

from products.p4.regression import fit_linear_model


def wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    den = 1 + z*z/total
    center = (p + z*z/(2*total))/den
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/den
    return [center-half, center+half]


def run(trials: int = 2000, seed: int = 20261123) -> dict:
    rng = np.random.default_rng(seed)
    false_positive = {"incorrect_chamber_clusters": 0, "correct_lot_clusters": 0}
    diagnostic = None
    for trial in range(trials):
        x = np.zeros(40)
        for pair in range(20):
            treated_position = int(rng.integers(0, 2))
            x[2*pair + treated_position] = 1.0
        lot_effect = rng.normal(0.0, 1.0, 40)
        xs, ys, lot_groups, chamber_groups, rows = [], [], [], [], []
        for lot in range(40):
            for repeat in range(2):
                y = lot_effect[lot] + rng.normal(0.0, 0.2)
                chamber = f"C{repeat}-{lot // 2}"
                xs.append(x[lot]); ys.append(y)
                lot_groups.append(lot); chamber_groups.append(chamber)
                rows.append({"id": f"T{trial}-L{lot}-R{repeat}",
                             "factors": {"treated": float(x[lot])}, "metrics": {"outcome": float(y)},
                             "lot_id": f"L{lot}", "chamber": chamber})
        design = sm.add_constant(np.asarray(xs))
        for label, groups in (("incorrect_chamber_clusters", chamber_groups),
                              ("correct_lot_clusters", lot_groups)):
            fit = sm.OLS(ys, design).fit(
                cov_type="cluster",
                cov_kwds={"groups": groups, "use_correction": True, "df_correction": True},
                use_t=True)
            low, high = fit.conf_int()[1]
            false_positive[label] += int(low > 0 or high < 0)
        if trial == 0:
            diagnostic, _ = fit_linear_model(
                rows, {"treated": {"role": "measured", "unit": "binary"}}, "outcome",
                {"covariance": "cluster", "cluster_field": "chamber",
                 "independent_unit_field": "lot_id", "minimum_clusters": 30})

    return {
        "schema": "p4-d01-cluster-nesting-benchmark/v1",
        "seed": seed,
        "trials": trials,
        "generator": {
            "independent_units": 40,
            "rows_per_unit": 2,
            "assignment": "one randomized treated lot and one control lot per pair; 20 pairs",
            "lot_effect_sd": 1.0,
            "within_lot_measurement_sd": 0.2,
            "true_effect": 0.0,
            "independence_structure": "lots independent; each lot is observed in two distinct chamber clusters",
        },
        "reference": {"name": "statsmodels clustered OLS", "version": statsmodels.__version__,
                      "confidence_level": 0.95, "test": "two-sided null rejection rate"},
        "results": {
            label: {"false_positives": count, "rate": count/trials,
                    "wilson_95": wilson(count, trials)}
            for label, count in false_positive.items()
        },
        "p4_behavior": {"status": diagnostic["status"],
                        "reason": diagnostic.get("reason"),
                        "cluster_nesting": diagnostic.get("inference", {}).get("cluster_nesting")},
        "scope": "synthetic method qualification only; not a process model, field error rate, or authorization",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.trials, args.seed)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
