"""Held-out null challenge for clustered uncertainty under severe group imbalance.

The optional statsmodels path is a qualified reference for the legacy
count-only cluster sandwich. Product inference must remain calibrated when
cluster sizes are balanced and abstain when observation-count concentration
makes the declared cluster count misleading.
"""
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
SEED = 781041


def wilson(successes: int, total: int, z: float = 1.959963984540054):
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * ((p*(1-p)/total + z*z/(4*total*total))**0.5) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def _trial(rng, sizes):
    treated = set(rng.sample(range(30), 15))
    group_effects = [rng.gauss(0, 1.0) for _ in range(30)]
    rows, x_values, y_values, groups = [], [], [], []
    for group, size in enumerate(sizes):
        x = float(group in treated)
        for replicate in range(size):
            y = group_effects[group] + rng.gauss(0, 0.35)
            rows.append({"factors": {"x": x}, "metrics": {"y": y}, "lot_id": f"LOT-{group:02d}"})
            x_values.append(x)
            y_values.append(y)
            groups.append(group)
    return rows, x_values, y_values, groups


def main():
    rng = random.Random(SEED)
    scenarios = {
        "balanced": [12] * 30,
        "one_dominant_cluster": [360] + [12] * 29,
    }
    results = {}
    parity_max = 0.0
    for scenario, sizes in scenarios.items():
        product_covered = 0
        product_inferred = 0
        product_abstained = 0
        product_widths = []
        reference_covered = 0
        reference_widths = []
        for trial_index in range(TRIALS):
            rows, xs, ys, groups = _trial(rng, sizes)
            report, _ = fit_linear_model(
                rows, {"x": {"role": "controllable", "unit": "u"}}, "y",
                {"covariance": "cluster", "cluster_field": "lot_id",
                 "independent_unit_field": "lot_id", "minimum_clusters": 30})
            term = report.get("terms", {}).get("x", {})
            interval = term.get("ci95")
            if interval is None:
                product_abstained += 1
            else:
                product_inferred += 1
                product_covered += interval[0] <= 0 <= interval[1]
                product_widths.append(interval[1] - interval[0])

            reference = sm.OLS(ys, sm.add_constant(xs)).fit(
                cov_type="cluster",
                cov_kwds={"groups": groups, "use_correction": True, "df_correction": True},
                use_t=True,
            )
            reference_interval = reference.conf_int(alpha=0.05)[1]
            reference_covered += reference_interval[0] <= 0 <= reference_interval[1]
            reference_widths.append(float(reference_interval[1] - reference_interval[0]))
            if trial_index < 25 and interval is not None:
                parity_max = max(
                    parity_max,
                    abs(term["estimate"] - float(reference.params[1])),
                    abs(term["standard_error"] - float(reference.bse[1])),
                )
        shares = [size / sum(sizes) for size in sizes]
        effective = 1 / sum(share*share for share in shares)
        results[scenario] = {
            "rows": sum(sizes),
            "nominal_clusters": len(sizes),
            "effective_clusters_by_row_count": effective,
            "dominant_cluster_row_share": max(shares),
            "product": {
                "inferred_trials": product_inferred,
                "abstained_trials": product_abstained,
                "coverage_among_inferred": product_covered / product_inferred if product_inferred else None,
                "coverage_wilson95": wilson(product_covered, product_inferred),
                "false_positive_rate_among_inferred": (product_inferred-product_covered) / product_inferred if product_inferred else None,
                "mean_interval_width": sum(product_widths) / len(product_widths) if product_widths else None,
            },
            "statsmodels_count_only_cluster_reference": {
                "inferred_trials": TRIALS,
                "coverage": reference_covered / TRIALS,
                "coverage_wilson95": wilson(reference_covered, TRIALS),
                "false_positive_rate": (TRIALS-reference_covered) / TRIALS,
                "mean_interval_width": sum(reference_widths) / TRIALS,
            },
        }

    imbalanced = results["one_dominant_cluster"]
    balanced = results["balanced"]
    passed = (
        balanced["product"]["inferred_trials"] == TRIALS
        and 0.90 <= balanced["product"]["coverage_among_inferred"] <= 0.98
        and imbalanced["product"]["abstained_trials"] == TRIALS
        and imbalanced["statsmodels_count_only_cluster_reference"]["false_positive_rate"] >= 0.20
        and parity_max < 1e-7
    )
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
    source = ROOT / "products/p4/regression.py"
    script = Path(__file__)
    payload = {
        "schema": "p4-d01-cluster-imbalance-benchmark/v1",
        "qualification": "PASS" if passed else "FAIL",
        "synthetic_only": True,
        "source_commit": commit,
        "product_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "seed": SEED,
        "trials_per_scenario": TRIALS,
        "data_generating_process": {
            "estimand": "zero slope for a cluster-assigned binary factor under the null",
            "independent_units": 30,
            "independent_cluster_effect_sd": 1.0,
            "within_cluster_noise_sd": 0.35,
            "assignment": "15 of 30 clusters assigned factor level 1 independently per trial",
            "held_out_scenarios": scenarios,
        },
        "reference": {"name": "statsmodels clustered OLS", "version": sm.__version__,
                      "role": "independent baseline for the count-only cluster sandwich"},
        "metrics": results,
        "parity_max_abs_difference_first_25_per_scenario": parity_max,
        "decision": "Use cluster-count and inverse-Herfindahl row-share screening together. If severe size concentration reduces the conservative effective cluster count below the configured minimum, withhold intervals; this diagnostic is not a coverage guarantee.",
    }
    out = ROOT / "qualification/results/D01_CLUSTER_IMBALANCE_BENCHMARK.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
