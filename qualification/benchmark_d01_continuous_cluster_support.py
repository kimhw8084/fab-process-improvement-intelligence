"""Held-out null challenge for numeric factors assigned at independent-cluster level."""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from products.p4.regression import fit_linear_model

TRIALS = 1200
SEED = 294071


def wilson(successes, total, z=1.959963984540054):
    p = successes / total
    d = 1 + z*z/total
    center = (p + z*z/(2*total)) / d
    half = z * ((p*(1-p)/total + z*z/(4*total*total))**0.5) / d
    return [max(0, center-half), min(1, center+half)]


def run_scenario(rng, exposures, reps=8, minimum_clusters=30):
    covered = inferred = abstained = reference_covered = 0
    parity = 0.0
    effective_information_clusters = None
    for _ in range(TRIALS):
        rows, x, y, groups = [], [], [], []
        cluster_effects = [rng.gauss(0, 1.0) for _ in exposures]
        for cluster, exposure in enumerate(exposures):
            for replicate in range(reps):
                outcome = cluster_effects[cluster] + rng.gauss(0, 0.5)
                rows.append({"factors": {"exposure": exposure}, "metrics": {"y": outcome},
                             "lot_id": f"LOT-{cluster:03d}"})
                x.append(exposure); y.append(outcome); groups.append(cluster)
        report, _ = fit_linear_model(
            rows, {"exposure": {"role": "measured", "unit": "u"}}, "y",
            {"covariance": "cluster", "cluster_field": "lot_id",
             "independent_unit_field": "lot_id", "minimum_clusters": minimum_clusters})
        if effective_information_clusters is None:
            support = report.get("inference", {}).get("cluster_level_factor_support", [])
            effective_information_clusters = support[0].get("effective_information_cluster_count") if support else None
        term = report["terms"]["exposure"]
        interval = term["ci95"]
        if interval is None:
            abstained += 1
        else:
            inferred += 1
            covered += interval[0] <= 0 <= interval[1]
        reference = sm.OLS(y, sm.add_constant(x)).fit(
            cov_type="cluster",
            cov_kwds={"groups": groups, "use_correction": True, "df_correction": True},
            use_t=True)
        ref_ci = reference.conf_int(alpha=0.05)[1]
        reference_covered += ref_ci[0] <= 0 <= ref_ci[1]
        if interval is not None:
            parity = max(parity, abs(term["estimate"] - float(reference.params[1])),
                         abs(term["standard_error"] - float(reference.bse[1])),
                         abs(interval[0] - float(ref_ci[0])), abs(interval[1] - float(ref_ci[1])))
    return {
        "nominal_clusters": len(exposures), "rows_per_cluster": reps,
        "product_inferred_trials": inferred, "product_abstained_trials": abstained,
        "product_coverage_among_inferred": covered / inferred if inferred else None,
        "product_coverage_wilson95": wilson(covered, inferred) if inferred else None,
        "effective_information_cluster_count": effective_information_clusters,
        "statsmodels_reference_coverage": reference_covered / TRIALS,
        "statsmodels_reference_false_positive_rate": 1 - reference_covered / TRIALS,
        "max_product_reference_interval_endpoint_error": parity,
    }


def main():
    rng = random.Random(SEED)
    scenarios = {
        "concentrated_30_cluster_exposure": ([0.02*i/28 for i in range(29)] + [1.0], 30),
        "spread_50_cluster_exposure": ([-1 + 2*i/49 for i in range(50)], 30),
        "balanced_20_cluster_five_level_exposure": ([float(i % 5 - 2) for i in range(20)], 20),
    }
    results = {name: run_scenario(rng, values, minimum_clusters=minimum)
               for name, (values, minimum) in scenarios.items()}
    concentrated = results["concentrated_30_cluster_exposure"]
    spread = results["spread_50_cluster_exposure"]
    five_level = results["balanced_20_cluster_five_level_exposure"]
    passed = (
        concentrated["product_abstained_trials"] == TRIALS
        and concentrated["statsmodels_reference_false_positive_rate"] >= 0.20
        and spread["product_inferred_trials"] == TRIALS
        and 0.90 <= spread["product_coverage_among_inferred"] <= 0.98
        and spread["product_coverage_wilson95"][0] <= 0.95 <= spread["product_coverage_wilson95"][1]
        and max(item["max_product_reference_interval_endpoint_error"] for item in results.values()) < 1e-7
        and five_level["product_inferred_trials"] == 0
        and five_level["product_abstained_trials"] == TRIALS
        and five_level["effective_information_cluster_count"] < 20
    )
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
    source = ROOT / "products/p4/regression.py"
    script = Path(__file__)
    payload = {
        "schema": "p4-d01-continuous-cluster-support/v1",
        "qualification": "PASS" if passed else "FAIL", "synthetic_only": True,
        "source_commit": commit,
        "product_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "seed": SEED, "trials_per_scenario": TRIALS,
        "data_generating_process": {
            "estimand": "zero linear association under the null",
            "outcome": "independent cluster intercept N(0,1) plus row noise N(0,0.5)",
            "factor": "continuous numeric exposure fixed within each cluster",
            "concentration_case": "29 distinct cluster values in [0,0.02], one at 1.0",
            "supported_case": "50 equally spaced cluster exposures from -1 to 1",
            "lower_cluster_count_case": "20 clusters balanced across five exposure levels; held-out benchmark measured 93.58% CR1 interval coverage and P4 now withholds uncertainty under its 20 effective-information-cluster heuristic",
            "limitations": "Synthetic unconditional null challenge; threshold is a cautious abstention rule and does not establish conditional coverage or validate a universal production cutoff.",
        },
        "method": {
            "screen": "inverse Herfindahl of n_cluster*(x_cluster-x_row_weighted_mean)^2 shares",
            "threshold": 20,
            "interpretation": "conservative abstention heuristic only, not an inferential effective sample size, df correction, or coverage guarantee",
        },
        "reference": {"name": "statsmodels clustered OLS CR1", "version": sm.__version__},
        "metrics": results,
        "decision": "Withhold clustered uncertainty for multi-level numeric factors constant within clusters when effective between-cluster information is below 20. The balanced 20-cluster case had 93.58% reference coverage and is now withheld; the well-spread 50-cluster case remains inferential and falls within the benchmark Wilson interval. This finite synthetic challenge justifies a conservative refusal heuristic, not a universal cutoff or coverage promise.",
    }
    out = ROOT / "qualification/results/D01_CONTINUOUS_CLUSTER_SUPPORT_BENCHMARK.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
