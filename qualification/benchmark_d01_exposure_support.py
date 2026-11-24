"""Independent challenge for sparse cluster-level binary factor support.

The DGP randomly assigns a small number of independent lots to a binary
exposure and gives lot means heterogeneous variance. It compares the ordinary
one-way cluster sandwich with a Welch test on independent lot means. The latter
is a reference for this randomized, equal-lot-size challenge only. P4 should
withhold model uncertainty when either binary level has fewer than ten lots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import t
import statsmodels
import statsmodels.api as sm

from products.p4.regression import fit_linear_model


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "products/p4/regression.py"
SCRIPT = Path(__file__)
EXPOSURE_COUNTS = (3, 10)
CLUSTERS = 30
REPLICATES_PER_CLUSTER = 6


def wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    denominator = 1.0 + z*z/total
    center = (p + z*z/(2*total))/denominator
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def run(trials: int = 3000, seed: int = 917234) -> dict:
    if trials < 1000:
        raise ValueError("at least 1,000 trials are required for this qualification challenge")
    rng = random.Random(seed)
    scenarios = {}
    for exposed_lots in EXPOSURE_COUNTS:
        p4_covered = p4_inferred = p4_abstained = 0
        p4_widths = []
        cluster_covered = 0
        welch_covered = 0
        cluster_widths = []
        welch_widths = []
        max_p4_reference_ci_difference = 0.0
        for trial in range(trials):
            assigned = set(rng.sample(range(CLUSTERS), exposed_lots))
            scales = [math.exp(rng.gauss(0.0, 0.85)) for _ in range(CLUSTERS)]
            rows = []
            cluster_means = []
            response = []
            treatment = []
            group_ids = []
            for cluster in range(CLUSTERS):
                exposed = float(cluster in assigned)
                cluster_effect = rng.gauss(0.0, scales[cluster])
                values = []
                for replicate in range(REPLICATES_PER_CLUSTER):
                    value = cluster_effect + 0.08*rng.gauss(0.0, 1.0)
                    values.append(value)
                    response.append(value)
                    treatment.append(exposed)
                    group_ids.append(cluster)
                    rows.append({"id": f"SYN-{exposed_lots}-{trial}-{cluster}-{replicate}",
                                 "factors": {"exposed": exposed}, "metrics": {"y": value},
                                 "lot_id": f"LOT-{cluster:02d}"})
                cluster_means.append(sum(values) / REPLICATES_PER_CLUSTER)

            report, _ = fit_linear_model(
                rows, {"exposed": {"role": "measured", "unit": "binary"}}, "y",
                {"covariance": "cluster", "cluster_field": "lot_id",
                 "independent_unit_field": "lot_id", "minimum_clusters": CLUSTERS})
            term = report.get("terms", {}).get("exposed", {})
            interval = term.get("ci95")
            if interval is None:
                p4_abstained += 1
            else:
                p4_inferred += 1
                p4_covered += int(interval[0] <= 0.0 <= interval[1])
                p4_widths.append(interval[1] - interval[0])

            reference = sm.OLS(response, sm.add_constant(np.asarray(treatment))).fit(
                cov_type="cluster",
                cov_kwds={"groups": np.asarray(group_ids), "use_correction": True,
                          "df_correction": True}, use_t=True)
            ref_low, ref_high = (float(value) for value in reference.conf_int(alpha=0.05)[1])
            cluster_covered += int(ref_low <= 0.0 <= ref_high)
            cluster_widths.append(ref_high-ref_low)
            if interval is not None:
                max_p4_reference_ci_difference = max(
                    max_p4_reference_ci_difference,
                    abs(interval[0]-ref_low), abs(interval[1]-ref_high))

            exposed_values = [cluster_means[index] for index in assigned]
            control_values = [cluster_means[index] for index in range(CLUSTERS) if index not in assigned]
            mean_exposed = sum(exposed_values) / len(exposed_values)
            mean_control = sum(control_values) / len(control_values)
            var_exposed = sum((value-mean_exposed)**2 for value in exposed_values)/(len(exposed_values)-1)
            var_control = sum((value-mean_control)**2 for value in control_values)/(len(control_values)-1)
            exposed_term = var_exposed/len(exposed_values)
            control_term = var_control/len(control_values)
            standard_error = math.sqrt(exposed_term+control_term)
            welch_df = (exposed_term+control_term)**2 / (
                exposed_term**2/(len(exposed_values)-1)
                + control_term**2/(len(control_values)-1))
            critical = float(t.ppf(0.975, welch_df))
            welch_low = mean_exposed-mean_control-critical*standard_error
            welch_high = mean_exposed-mean_control+critical*standard_error
            welch_covered += int(welch_low <= 0.0 <= welch_high)
            welch_widths.append(welch_high-welch_low)

        p4_coverage = p4_covered/p4_inferred if p4_inferred else None
        cluster_coverage = cluster_covered/trials
        welch_coverage = welch_covered/trials
        scenarios[str(exposed_lots)] = {
            "exposed_lots": exposed_lots,
            "control_lots": CLUSTERS-exposed_lots,
            "trials": trials,
            "p4": {
                "inferred_trials": p4_inferred,
                "abstained_trials": p4_abstained,
                "coverage_among_inferred": p4_coverage,
                "coverage_wilson95": wilson(p4_covered, p4_inferred) if p4_inferred else None,
                "mean_interval_width": sum(p4_widths)/len(p4_widths) if p4_widths else None,
            },
            "ordinary_one_way_cluster_reference": {
                "coverage": cluster_coverage,
                "coverage_wilson95": wilson(cluster_covered, trials),
                "mean_interval_width": sum(cluster_widths)/len(cluster_widths),
            },
            "welch_independent_lot_mean_reference": {
                "coverage": welch_coverage,
                "coverage_wilson95": wilson(welch_covered, trials),
                "mean_interval_width": sum(welch_widths)/len(welch_widths),
            },
            "maximum_p4_vs_statsmodels_interval_endpoint_difference": max_p4_reference_ci_difference,
        }

    rare = scenarios["3"]
    supported = scenarios["10"]
    rare_ci = rare["ordinary_one_way_cluster_reference"]["coverage_wilson95"]
    welch_ci = rare["welch_independent_lot_mean_reference"]["coverage_wilson95"]
    supported_ci = supported["p4"]["coverage_wilson95"]
    passed = (
        rare["p4"]["abstained_trials"] == trials
        and rare["p4"]["inferred_trials"] == 0
        and rare_ci[1] < 0.95
        and welch_ci[0] >= 0.94
        and welch_ci[1] <= 0.99
        and supported["p4"]["abstained_trials"] == 0
        and supported["p4"]["inferred_trials"] == trials
        and supported_ci[0] <= 0.95 <= supported_ci[1]
        and supported["maximum_p4_vs_statsmodels_interval_endpoint_difference"] < 1e-7
    )
    return {
        "schema": "p4-d01-cluster-exposure-support-benchmark/v1",
        "seed": seed,
        "trials_per_scenario": trials,
        "data_generating_process": {
            "estimand": "zero difference in mean response between randomized binary exposure arms",
            "independent_units": CLUSTERS,
            "exposure_assignment": "fixed number of exposed lots selected uniformly without replacement per trial",
            "exposure_counts": list(EXPOSURE_COUNTS),
            "replicates_per_lot": REPLICATES_PER_CLUSTER,
            "lot_mean_sd": "independent lognormal scale exp(N(0, 0.85^2))",
            "within_lot_noise_sd": 0.08,
            "cluster_size": "equal across all independent lots",
        },
        "references": {
            "ordinary_cluster": {"library": "statsmodels", "version": statsmodels.__version__,
                                 "method": "CR1 one-way cluster covariance with t(G-1) inference"},
            "welch": {"library": "scipy", "version": scipy.__version__,
                      "method": "Welch two-sample t interval on independent lot means"},
        },
        "scenarios": scenarios,
        "qualification": "PASS" if passed else "FAIL",
        "product_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "runtime_dependencies_added": False,
        "limitations": [
            "fixed-seed randomized synthetic challenge with equal lot sizes; no FAB error rate or coverage guarantee",
            "the Welch reference applies only to this randomized two-arm cluster-mean challenge",
            "the ten-lots-per-level rule is a conservative abstention heuristic; passing does not validate inference",
            "observational assignment mechanisms may have additional confounding not represented here",
        ],
        "scope": "independent method challenge for binary factors constant within declared clusters; no general small-sample or production claim",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=917234)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "qualification/results/D01_CLUSTER_EXPOSURE_SUPPORT_BENCHMARK.json")
    args = parser.parse_args()
    report = run(args.trials, args.seed)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if report["qualification"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
