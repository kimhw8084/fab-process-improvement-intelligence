"""Challenge cross-step intervals when a rare metric has zero observed variance."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from products.p4.tradeoffs import cross_step_tradeoffs

ROOT = Path(__file__).resolve().parent.parent
TRIALS = 1000
SEED = 20261123
SETTINGS = ((1, 0.01), (2, 0.02), (3, 0.04))
UNITS_PER_SETTING = 30


def run_trial(trial, rng):
    rows = []
    defect_counts = {}
    for setting, defect_probability in SETTINGS:
        defect_counts[setting] = 0
        for index in range(UNITS_PER_SETTING):
            unit = f"SYN-TRIAL-{trial}-SETTING-{setting}-LOT-{index}"
            defect = int(rng.random() < defect_probability)
            defect_counts[setting] += defect
            rows.append({
                "id": f"PAIR-{trial}-{setting}-{index}",
                "unit_id": unit,
                "factors": {"pressure": float(setting)},
                "metrics": {"yield": 80.0 + 2.0 * (setting - 1) + rng.gauss(0.0, 0.2),
                            "defect": float(defect)},
                "source_ids": ["SYN-UPSTREAM", "SYN-DOWNSTREAM"],
                "upstream": {"unit_id": unit, "event_ts": "2026-01-01T00:00:00Z",
                             "population_id": "SYN-COHORT-01"},
                "downstream": {"unit_id": unit, "event_ts": "2026-01-01T03:00:00Z",
                               "population_id": "SYN-COHORT-01"},
            })

    metric_defs = {"yield": {"direction": "maximize", "unit": "%"},
                   "defect": {"direction": "minimize", "unit": "count"}}
    data = {
        "sources": [{"id": "SYN-UPSTREAM"}, {"id": "SYN-DOWNSTREAM"}],
        "objectives": [{"metric": "yield", "direction": "maximize"},
                       {"metric": "defect", "direction": "minimize"}],
        "linkage": {
            "approved": True, "relationship_id": "SYN-REL-01", "contract_version": "1.0.0",
            "approval_reference": "SYN-APPROVAL-01", "maximum_lag_seconds": 86400,
            "unit_field": "unit_id", "decision_factors": ["pressure"],
            "minimum_independent_units": UNITS_PER_SETTING,
            "upstream": {"source_id": "SYN-UPSTREAM", "key_field": "upstream.unit_id",
                         "event_time_field": "upstream.event_ts", "population_field": "upstream.population_id",
                         "population_id": "SYN-COHORT-01", "metric_field": "metrics.yield", "metric": "yield"},
            "downstream": {"source_id": "SYN-DOWNSTREAM", "key_field": "downstream.unit_id",
                           "event_time_field": "downstream.event_ts", "population_field": "downstream.population_id",
                           "population_id": "SYN-COHORT-01", "metric_field": "metrics.defect", "metric": "defect"},
        },
    }
    result = cross_step_tradeoffs(rows, metric_defs, data)
    by_setting = {int(candidate["factors"]["pressure"]): candidate
                  for candidate in result.get("candidate_settings", [])}
    legacy_false_pairs = 0
    reported_false_pairs = 0
    pairs = {tuple((item["dominant_setting_id"], item["dominated_setting_id"]))
             for item in result.get("interval_separated_dominance", [])}
    for lower, higher in ((1, 2), (1, 3), (2, 3)):
        if defect_counts[lower] != 0 or defect_counts[higher] != 0:
            continue
        lower_interval = by_setting[lower]["uncertainty"]["yield"]["marginal_ci95"]
        higher_interval = by_setting[higher]["uncertainty"]["yield"]["marginal_ci95"]
        if higher_interval and lower_interval and higher_interval[0] > lower_interval[1]:
            # Under the legacy zero-width rule, these settings appear separated
            # on yield and tied at zero defects, although the true defect risk is
            # strictly worse at the higher-yield setting.
            legacy_false_pairs += 1
            higher_id, lower_id = by_setting[higher]["id"], by_setting[lower]["id"]
            if (higher_id, lower_id) in pairs:
                reported_false_pairs += 1
    withheld_zero_variance = sum(
        candidate["uncertainty"]["defect"]["marginal_ci95"] is None
        and candidate["uncertainty"]["defect"]["marginal_ci95_status"] == "NOT_ESTIMABLE_ZERO_OBSERVED_VARIANCE"
        for candidate in by_setting.values()
    )
    return {
        "legacy_zero_width_false_preference_pairs": legacy_false_pairs,
        "product_reported_zero_width_false_preference_pairs": reported_false_pairs,
        "zero_variance_defect_intervals_withheld": withheld_zero_variance,
        "zero_variance_settings": sum(count == 0 for count in defect_counts.values()),
        "status": result.get("status"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("qualification/results/D03_ZERO_VARIANCE_BENCHMARK.json"))
    args = parser.parse_args()
    rng = random.Random(SEED)
    totals = {"legacy_zero_width_false_preference_pairs": 0,
              "product_reported_zero_width_false_preference_pairs": 0,
              "zero_variance_defect_intervals_withheld": 0,
              "zero_variance_settings": 0,
              "limited_scope_trials": 0}
    for trial in range(TRIALS):
        observation = run_trial(trial, rng)
        for key in totals:
            if key == "limited_scope_trials":
                totals[key] += observation["status"] == "LIMITED_SCOPE"
            else:
                totals[key] += observation[key]

    product_hash = hashlib.sha256((ROOT / "products/p4/tradeoffs.py").read_bytes()).hexdigest()
    result = {
        "schema": "p4-d03-zero-variance-benchmark/v1",
        "seed": SEED,
        "trials": TRIALS,
        "settings": [{"pressure": setting, "true_defect_probability": probability}
                     for setting, probability in SETTINGS],
        "independent_units_per_setting": UNITS_PER_SETTING,
        "generator": "Independent per-lot rare Bernoulli defects with strictly increasing true risk and separated normal yield means; the evaluator knows all generating probabilities.",
        "totals": totals,
        "metrics": {
            "legacy_zero_width_false_preference_pair_fraction": totals["legacy_zero_width_false_preference_pairs"] / TRIALS,
            "product_zero_width_false_preference_pair_fraction": totals["product_reported_zero_width_false_preference_pairs"] / TRIALS,
            "zero_variance_defect_interval_withholding_fraction": (totals["zero_variance_defect_intervals_withheld"]
                                                                   / max(totals["zero_variance_settings"], 1)),
            "limited_scope_trial_fraction": totals["limited_scope_trials"] / TRIALS,
        },
        "product_tradeoffs_sha256": product_hash,
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "fixed-seed independent synthetic stress; does not establish manufacturing incidence or model transfer",
        "qualification": "PASS" if (totals["legacy_zero_width_false_preference_pairs"] > 0
                                     and totals["product_reported_zero_width_false_preference_pairs"] == 0
                                     and totals["zero_variance_defect_intervals_withheld"] == totals["zero_variance_settings"]
                                     and totals["limited_scope_trials"] > 0) else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["qualification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
