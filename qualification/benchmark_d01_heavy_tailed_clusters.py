"""Held-out D01 challenge for heavy-tailed independent cluster errors."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import statsmodels.api as sm

from products.p4.regression import fit_linear_model

ROOT = Path(__file__).resolve().parents[1]
TRIALS = 1200
SEED = 32117
CLUSTERS = 50
REPLICATES_PER_CLUSTER = 4
TRUE_SLOPE = 0.7


def _wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z*z/trials
    center = (rate + z*z/(2*trials)) / denominator
    half = z * math.sqrt((rate*(1-rate) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def run_benchmark(trials: int = TRIALS, seed: int = SEED) -> dict:
    if trials < 1000:
        raise ValueError("the predeclared cluster challenge requires at least 1,000 trials")
    rng = random.Random(seed)
    inferred = refused = covered = reference_covered = 0
    parity_max = 0.0
    degrees_of_freedom = []
    for trial in range(trials):
        rows, xs, ys, groups = [], [], [], []
        for cluster in range(CLUSTERS):
            x = rng.uniform(-2.0, 2.0)
            # Standardized Student-t(4) has finite variance but heavy tails.
            cluster_effect = (rng.gauss(0.0, 1.0)
                              / math.sqrt(rng.gammavariate(2.0, 2.0) / 4.0)
                              / math.sqrt(2.0))
            for replicate in range(REPLICATES_PER_CLUSTER):
                y = 1.2 + TRUE_SLOPE*x + 1.5*cluster_effect + rng.gauss(0.0, 0.3)
                rows.append({"id": f"SYN-{trial}-{cluster}-{replicate}",
                             "lot_id": f"SYN-LOT-{cluster}",
                             "factors": {"x": x}, "metrics": {"y": y}})
                xs.append(x); ys.append(y); groups.append(cluster)
        report, _ = fit_linear_model(
            rows, {"x": {"role": "controllable", "unit": "synthetic-unit"}}, "y",
            {"covariance": "cluster", "cluster_field": "lot_id",
             "independent_unit_field": "lot_id", "minimum_clusters": 20})
        reference = sm.OLS(ys, sm.add_constant(xs)).fit(
            cov_type="cluster",
            cov_kwds={"groups": groups, "use_correction": True, "df_correction": True},
            use_t=True)
        reference_interval = reference.conf_int(alpha=0.05)[1]
        reference_covered += reference_interval[0] <= TRUE_SLOPE <= reference_interval[1]
        interval = report.get("terms", {}).get("x", {}).get("ci95")
        if interval is None:
            refused += 1
            continue
        inferred += 1
        covered += interval[0] <= TRUE_SLOPE <= interval[1]
        degrees_of_freedom.append(report["inference"]["inference_df"])
        parity_max = max(
            parity_max,
            abs(report["terms"]["x"]["estimate"] - float(reference.params[1])),
            abs(report["terms"]["x"]["standard_error"] - float(reference.bse[1])),
            abs(interval[0] - float(reference_interval[0])),
            abs(interval[1] - float(reference_interval[1])),
        )
    p4_coverage = covered / inferred if inferred else None
    reference_coverage = reference_covered / trials
    interval = _wilson(covered, inferred) if inferred else None
    passed = (inferred >= 0.95*trials and interval[0] <= 0.95 <= interval[1]
              and parity_max < 1e-6 and abs(p4_coverage-reference_coverage) <= 0.02
              and refused > 0)
    return {
        "schema": "p4-d01-heavy-tailed-cluster-benchmark/v1",
        "status": "PASS" if passed else "FAIL",
        "benchmark": "D01_CLUSTER_ROBUST_INFERENCE_HEAVY_TAILED_ERRORS",
        "synthetic_only": True,
        "seed": seed,
        "trials": trials,
        "clusters": CLUSTERS,
        "rows_per_cluster": REPLICATES_PER_CLUSTER,
        "true_slope": TRUE_SLOPE,
        "generator": "independent lots; x assigned once per lot; standardized t4 lot intercept plus Gaussian row noise; fixed linear formula and known slope",
        "p4": {"inferred_trials": inferred, "refused_trials": refused,
               "coverage_among_inferred": p4_coverage,
               "coverage_wilson95_monte_carlo": interval,
               "mean_inference_df": statistics.mean(degrees_of_freedom) if degrees_of_freedom else None},
        "statsmodels_clustered_ols_reference": {"version": sm.__version__,
                                                "coverage_all_trials": reference_coverage},
        "maximum_absolute_estimate_se_or_endpoint_difference": parity_max,
        "limitations": [
            "fixed synthetic linear generator; not a coverage guarantee for other error laws or fab populations",
            "the reference uses the same CR1 cluster-sandwich estimator and is an independent implementation, not an independent method",
            "Monte Carlo Wilson bounds quantify simulation error only",
            "the five low-information refusals remain excluded from coverage among inferred",
        ],
        "product_source_sha256": hashlib.sha256((ROOT / "products/p4/regression.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if result["status"] != "PASS":
        raise SystemExit(1)
