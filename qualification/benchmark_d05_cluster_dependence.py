#!/usr/bin/env python3
"""Independent D05 null challenge for repeated cluster shocks across units."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
import subprocess
import sys

from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from products.p4.engine import _effectiveness


def wilson(successes: int, trials: int) -> list[float]:
    if not trials:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = successes / trials
    den = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / den
    half = z * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5) / den
    return [center - half, center + half]


def study_for_trial(trial: int, rng: random.Random) -> dict:
    rows, ledger = [], []
    arm_cluster_changes = {"treatment": [[] for _ in range(5)], "control": [[] for _ in range(5)]}
    cluster_shocks = {f"{group}-{cluster}": rng.gauss(0, 1.5)
                      for group in ("treatment", "control") for cluster in range(5)}
    for group in ("treatment", "control"):
        for unit in range(30):
            unit_id = f"SYN-{trial}-{group}-{unit}"
            chamber_index = unit // 6
            chamber_id = f"SYN-CHAMBER-{group}-{chamber_index}"
            shock = cluster_shocks[f"{group}-{chamber_index}"]
            baseline = 100.0 + 0.02 * unit
            ledger.append({"unit_id": unit_id, "group": group})
            arm_cluster_changes[group][chamber_index].append(shock)
            for period, value, timestamp in (
                ("pre2", baseline, "2025-11-01T00:00:00Z"),
                ("pre", baseline + 0.1, "2025-12-01T00:00:00Z"),
                ("post", baseline + 0.1 + shock, "2026-02-01T00:00:00Z"),
            ):
                rows.append({"unit_id": unit_id, "group": group, "period": period,
                             "quality": value, "timestamp": timestamp,
                             "product_id": "SYN-A" if unit < 15 else "SYN-B",
                             "chamber_id": chamber_id,
                             "concurrent_intervention_id": "none"})
    study = {
        "authorized": True, "design": "difference_in_differences",
        "intervention_id": f"SYN-D05-CLUSTER-{trial}", "authorization_id": f"SYN-D05-AUTH-{trial}",
        "metric": "quality", "metric_unit": "synthetic quality unit",
        "assignment_ledger": ledger, "intervention_time": "2026-01-01T00:00:00Z",
        "population_fields": ["product_id"],
        "differential_trend_bound": 4.0, "differential_trend_bound_source": "SYN-BOUND",
        "differential_trend_bound_method": "SYN-ORACLE-BOUND",
        "differential_trend_bound_unit": "synthetic quality unit",
        "pretrend_equivalence_bound": 0.25, "pretrend_equivalence_bound_source": "SYN-PRE",
        "pretrend_equivalence_bound_method": "SYN-ORACLE-EQUIVALENCE",
        "pretrend_equivalence_bound_unit": "synthetic quality unit",
        "observations": rows,
    }
    cluster_means = {group: [sum(values) / len(values) for values in arm_cluster_changes[group]]
                     for group in arm_cluster_changes}
    return study, cluster_means


def run(trials: int = 1000, seed: int = 20261124) -> dict:
    rng = random.Random(seed)
    naive_coverage = cluster_reference_coverage = 0
    declared_refusals = declared_intervals = declared_causal_claims = declared_descriptive = 0
    naive_examples = []
    for trial in range(trials):
        study, cluster_means = study_for_trial(trial, rng)
        naive = _effectiveness({"effectiveness": study})
        interval = naive.get("ci95_welch_t_approximation")
        if naive.get("status") != "ESTIMATED" or not isinstance(interval, list):
            raise AssertionError(f"undeclared unit analysis did not produce its baseline interval: {naive}")
        naive_coverage += int(interval[0] <= 0.0 <= interval[1])
        if len(naive_examples) < 3:
            naive_examples.append({"estimate": naive["estimate"], "ci95": interval})
        reference = stats.ttest_ind(cluster_means["treatment"], cluster_means["control"], equal_var=False)
        ref_ci = reference.confidence_interval(confidence_level=0.95)
        cluster_reference_coverage += int(ref_ci.low <= 0.0 <= ref_ci.high)

        declared = dict(study, shared_dependence_fields=["chamber_id"])
        result = _effectiveness({"effectiveness": declared})
        declared_refusals += int(result.get("status") == "INCONCLUSIVE" and result.get("uncertainty_status") == "WITHHELD_SHARED_GROUP_DEPENDENCE")
        declared_intervals += int("ci95_welch_t_approximation" in result)
        declared_causal_claims += int(bool(result.get("causal_claim")))
        declared_descriptive += int(isinstance(result.get("descriptive_did_estimate"), (int, float)))
    checks = {
        "naive_unit_interval_coverage_below_0_75": naive_coverage / trials < 0.75,
        "independent_chamber_mean_reference_wilson_lower_above_0_90": wilson(cluster_reference_coverage, trials)[0] > 0.90,
        "declared_shared_chamber_structure_withheld_every_interval": declared_refusals == trials and declared_intervals == 0,
        "declared_dependence_emitted_no_causal_claim": declared_causal_claims == 0,
        "declared_dependence_retained_only_descriptive_did_contrast": declared_descriptive == trials,
    }
    provenance = {
        "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                         capture_output=True, text=True).stdout.strip(),
        "engine_sha256": hashlib.sha256((ROOT / "products/p4/engine.py").read_bytes()).hexdigest(),
        "regression_sha256": hashlib.sha256((ROOT / "products/p4/regression.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return {
        "schema": "p4-d05-cluster-dependence-benchmark/v1", "trials": trials, "seed": seed,
        "generator": {"true_did_effect": 0.0, "clusters_per_arm": 5, "units_per_cluster": 6,
                      "cluster_shock_sd": 1.5, "cluster_assignment": "nested within arm; independent normal shocks"},
        "reference": "SciPy Welch t interval over independently generated chamber mean changes",
        "naive_unit_welch_coverage": {"count": naive_coverage, "rate": naive_coverage / trials,
                                      "wilson95": wilson(naive_coverage, trials),
                                      "examples": naive_examples},
        "cluster_mean_reference_coverage": {"count": cluster_reference_coverage,
                                            "rate": cluster_reference_coverage / trials,
                                            "wilson95": wilson(cluster_reference_coverage, trials)},
        "declared_dependence_behavior": {"withheld_refusals": declared_refusals,
                                         "intervals_emitted": declared_intervals,
                                         "causal_claims": declared_causal_claims,
                                         "descriptive_estimates": declared_descriptive},
        "qualification_checks": checks,
        "qualification_status": "PASS" if all(checks.values()) else "FAIL",
        "source_provenance": provenance,
        "scope": "Fixed synthetic nested-cluster null challenge only. The caller must declare valid grouping semantics; absent declarations, unobserved or unlisted dependence is not detected. This finite challenge is not a fab coverage estimate.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--output", type=Path, default=ROOT / "qualification/results/D05_CLUSTER_DEPENDENCE_BENCHMARK.json")
    args = parser.parse_args()
    result = run(args.trials, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["qualification_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
