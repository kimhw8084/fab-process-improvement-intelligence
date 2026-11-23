"""Independent null challenge for crossed chamber/product residual shocks.

The data generator randomizes treatment within every chamber-product cell while
allowing chamber and product specific treatment-response shocks. A lot is the
observation unit, so one-way lot clustering does not account for correlation
shared across lots in the same chamber or product. Statsmodels' two-way
chamber/product covariance is an established reference for this two-dimension
generator; P4 is expected to withhold inference when those dimensions are
declared because its production estimator currently supports one-way clustering
only. This synthetic benchmark does not represent a FAB population.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import t
import statsmodels
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_cluster_2groups

from products.p4.regression import fit_linear_model


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "products/p4/regression.py"
SCRIPT = Path(__file__)


def wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    den = 1 + z*z/total
    center = (p + z*z/(2*total))/den
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/den
    return [center-half, center+half]


def generate_trial(rng, trial: int, groups_per_dimension: int = 30):
    chamber_intercepts = rng.normal(0.0, 0.8, groups_per_dimension)
    product_intercepts = rng.normal(0.0, 0.8, groups_per_dimension)
    chamber_slopes = rng.normal(0.0, 0.45, groups_per_dimension)
    product_slopes = rng.normal(0.0, 0.45, groups_per_dimension)
    rows, x_values, y_values, lot_groups, chamber_groups, product_groups = [], [], [], [], [], []
    lot = 0
    for chamber in range(groups_per_dimension):
        for product in range(groups_per_dimension):
            assignment = rng.permutation(np.asarray([0.0, 1.0]))
            for treatment in assignment:
                noise = rng.normal(0.0, 0.35)
                outcome = (chamber_intercepts[chamber] + product_intercepts[product]
                           + (chamber_slopes[chamber] + product_slopes[product]) * treatment
                           + noise)
                row = {"id": f"T{trial}-LOT{lot}", "factors": {"treated": float(treatment)},
                       "metrics": {"outcome": float(outcome)}, "lot_id": f"T{trial}-LOT{lot}",
                       "chamber": f"C{chamber}", "product": f"P{product}"}
                rows.append(row)
                x_values.append(float(treatment)); y_values.append(float(outcome))
                lot_groups.append(lot); chamber_groups.append(chamber); product_groups.append(product)
                lot += 1
    return rows, np.asarray(x_values), np.asarray(y_values), np.asarray(lot_groups), \
        np.asarray(chamber_groups), np.asarray(product_groups)


def summarize(count: int, total: int) -> dict:
    return {"false_positives": count, "false_positive_rate": count/total,
            "wilson_95": wilson(count, total)}


def run(trials: int = 1200, seed: int = 20261123, p4_checks: int = 8) -> dict:
    if trials < 100 or p4_checks < 1:
        raise ValueError("at least 100 trials and one P4 diagnostic check are required")
    rng = np.random.default_rng(seed)
    rejected = {"one_way_lot_cluster": 0, "two_way_chamber_product": 0}
    invalid_two_way_variances = 0
    p4_diagnostics = []
    groups_per_dimension = 30
    sample_size = groups_per_dimension * groups_per_dimension * 2
    for trial in range(trials):
        rows, x, y, lot_groups, chamber_groups, product_groups = generate_trial(rng, trial, groups_per_dimension)
        design = sm.add_constant(x)
        one_way = sm.OLS(y, design).fit(
            cov_type="cluster",
            cov_kwds={"groups": lot_groups, "use_correction": True, "df_correction": True},
            use_t=True)
        one_way_low, one_way_high = one_way.conf_int()[1]
        rejected["one_way_lot_cluster"] += int(one_way_low > 0 or one_way_high < 0)

        pooled = sm.OLS(y, design).fit()
        covariance, _, _ = cov_cluster_2groups(
            pooled, chamber_groups, product_groups, use_correction=True)
        variance = float(covariance[1, 1])
        if not math.isfinite(variance) or variance <= 0:
            invalid_two_way_variances += 1
        else:
            standard_error = math.sqrt(variance)
            critical = float(t.ppf(0.975, groups_per_dimension - 1))
            low = float(pooled.params[1] - critical*standard_error)
            high = float(pooled.params[1] + critical*standard_error)
            rejected["two_way_chamber_product"] += int(low > 0 or high < 0)

        if trial < p4_checks:
            report, model = fit_linear_model(
                rows, {"treated": {"role": "measured", "unit": "binary"}}, "outcome",
                {"covariance": "cluster", "cluster_field": "lot_id",
                 "independent_unit_field": "lot_id", "minimum_clusters": 30,
                 "shared_dependence_fields": ["chamber", "product"]})
            diagnostic = report.get("inference", {}).get("shared_dependence", {})
            p4_diagnostics.append({"trial": trial, "status": report.get("status"),
                                   "model_available": model is not None,
                                   "interval_available": report.get("terms", {}).get("treated", {}).get("ci95") is not None,
                                   "crossed_dependence_status": diagnostic.get("status"),
                                   "crossed_groups_by_field": {
                                       item.get("field"): item.get("crossed_group_count")
                                       for item in diagnostic.get("fields", [])}})

    p4_abstained = sum(item["status"] == "INCONCLUSIVE" and not item["interval_available"]
                       and item["crossed_dependence_status"] == "CROSSED_DEPENDENCE_DETECTED"
                       for item in p4_diagnostics)
    metrics = {name: summarize(count, trials) for name, count in rejected.items()}
    candidate = metrics["two_way_chamber_product"]
    two_way_calibrated = (candidate["wilson_95"][0] <= 0.05 <= candidate["wilson_95"][1]
                          and invalid_two_way_variances == 0)
    p4_refusal_pass = p4_abstained == p4_checks
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    script_hash = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    return {
        "schema": "p4-d01-crossed-dependence-benchmark/v1",
        "seed": seed,
        "trials": trials,
        "generating_mechanism": {
            "true_treatment_effect": 0.0,
            "independent_units": sample_size,
            "chambers": groups_per_dimension,
            "products": groups_per_dimension,
            "observations_per_chamber_product_cell": 2,
            "assignment": "one treated and one control lot randomized within every chamber-product cell",
            "shared_random_effect_sd": {"chamber_intercept": 0.8, "product_intercept": 0.8,
                                         "chamber_treatment_slope": 0.45,
                                         "product_treatment_slope": 0.45},
            "lot_noise_sd": 0.35,
            "independence": "lot noise is independent; residual treatment response is shared across lots by chamber and by product",
        },
        "reference": {"library": "statsmodels", "version": statsmodels.__version__,
                      "two_way_method": "Cameron-Gelbach-Miller inclusion-exclusion covariance via cov_cluster_2groups",
                      "two_way_df": groups_per_dimension - 1,
                      "confidence_level": 0.95,
                      "scipy_version": scipy.__version__},
        "metrics": metrics,
        "two_way_invalid_covariance_trials": invalid_two_way_variances,
        "p4_behavior": {"checks": p4_checks, "crossed_dependence_abstentions": p4_abstained,
                         "all_checks_abstained": p4_refusal_pass,
                         "diagnostics": p4_diagnostics},
        "qualification": "PASS" if two_way_calibrated and p4_refusal_pass else "FAIL",
        "product_source_sha256": source_hash,
        "benchmark_script_sha256": script_hash,
        "runtime_dependencies_added": False,
        "interpretation": "the two-way Statsmodels candidate is benchmark-qualified only for this two-dimension synthetic generator; P4 deliberately withholds intervals because the product workflow has no production-qualified multiway covariance engine and real dependence mappings remain caller supplied",
        "scope": "synthetic null-method challenge only; no causal, manufacturing, conditional-coverage, or production claim",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--p4-checks", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT / "qualification/results/D01_CROSSED_DEPENDENCE_BENCHMARK.json")
    args = parser.parse_args()
    report = run(args.trials, args.seed, args.p4_checks)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
