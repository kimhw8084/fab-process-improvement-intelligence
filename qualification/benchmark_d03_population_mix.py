"""Held-out D03 challenge for composition-driven false Pareto dominance."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from fractions import Fraction
from pathlib import Path

from products.p4.tradeoffs import cross_step_tradeoffs


TRIALS = 250
SEED = 86117
METRIC_DEFS = {"quality": {"unit": "score", "direction": "maximize"},
               "defect": {"unit": "count", "direction": "minimize"}}
OBJECTIVES = [{"metric": "quality", "direction": "maximize"},
              {"metric": "defect", "direction": "minimize"}]
LINKAGE = {
    "approved": True, "relationship_id": "SYN-D03-MIX-01", "contract_version": "1.1.0",
    "approval_reference": "SYN-D03-MIX-APPROVAL", "maximum_lag_seconds": 86400,
    "unit_field": "unit_id", "decision_factors": ["pressure"], "minimum_independent_units": 30,
    "population_composition_fields": [{
        "name": "product_family", "upstream_field": "upstream.product_family",
        "downstream_field": "downstream.product_family"}],
    "upstream": {"source_id": "SYN-UP", "key_field": "upstream.unit_id",
                  "event_time_field": "upstream.event_ts", "population_field": "upstream.population_id",
                  "population_id": "SYN-COHORT", "metric_field": "metrics.quality", "metric": "quality"},
    "downstream": {"source_id": "SYN-DOWN", "key_field": "downstream.unit_id",
                    "event_time_field": "downstream.event_ts", "population_field": "downstream.population_id",
                    "population_id": "SYN-COHORT", "metric_field": "metrics.defect", "metric": "defect"},
}


def _rows(rng: random.Random, counts_a: tuple[int, int, int], sizes=(30, 30, 30),
          process_effects=((0.0, 0.0), (0.0, 0.0), (0.0, 0.0))):
    rows = []
    for setting, (count_a, size, (quality_effect, defect_effect)) in enumerate(
            zip(counts_a, sizes, process_effects), 1):
        families = ["A"] * count_a + ["B"] * (size-count_a)
        rng.shuffle(families)
        for unit_index, family in enumerate(families):
            unit_id = f"SYN-{setting}-{unit_index:03d}"
            quality_base, defect_base = ((90.0, 1.0) if family == "A" else (70.0, 10.0))
            quality = quality_base + quality_effect + rng.gauss(0.0, 0.08)
            defect = defect_base + defect_effect + rng.gauss(0.0, 0.05)
            rows.append({
                "id": f"SYN-PAIR-{setting}-{unit_index:03d}", "unit_id": unit_id,
                "factors": {"pressure": float(setting)},
                "metrics": {"quality": quality, "defect": defect},
                "source_ids": ["SYN-UP", "SYN-DOWN"],
                "upstream": {"unit_id": unit_id, "event_ts": "2026-01-01T00:00:00Z",
                             "population_id": "SYN-COHORT", "product_family": family},
                "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T02:00:00Z",
                               "population_id": "SYN-COHORT", "product_family": family},
            })
    return rows


def _data():
    return {"sources": [{"id": "SYN-UP"}, {"id": "SYN-DOWN"}],
            "objectives": OBJECTIVES, "linkage": LINKAGE}


def _naive_front(rows):
    setting_means = {}
    for row in rows:
        setting = row["factors"]["pressure"]
        values = setting_means.setdefault(setting, {"quality": [], "defect": []})
        for metric in values:
            values[metric].append(row["metrics"][metric])
    means = {setting: {metric: sum(values)/len(values) for metric, values in metrics.items()}
             for setting, metrics in setting_means.items()}
    dominated = set()
    for candidate, target in means.items():
        for other, source in means.items():
            if other == candidate:
                continue
            if (source["quality"] >= target["quality"] and source["defect"] <= target["defect"]
                    and (source["quality"] > target["quality"] or source["defect"] < target["defect"])):
                dominated.add(candidate)
                break
    return means, dominated


def _composition_oracle(rows):
    counts = {}
    for row in rows:
        setting = row["factors"]["pressure"]
        families = counts.setdefault(setting, {"A": 0, "B": 0})
        families[row["upstream"]["product_family"]] += 1
    distributions = {setting: {family: Fraction(count, sum(families.values()))
                               for family, count in families.items()}
                     for setting, families in counts.items()}
    reference = next(iter(distributions.values()))
    return counts, all(profile == reference for profile in list(distributions.values())[1:])


def run_benchmark(trials=TRIALS, seed=SEED):
    if trials < 100:
        raise ValueError("benchmark requires at least 100 independent trials")
    rng = random.Random(seed)
    mismatched_refusals = naive_false_fronts = oracle_mismatch = 0
    matched_fronts = matched_oracle_agreements = 0
    examples = {}
    for trial in range(trials):
        counts_a = (rng.randint(27, 30), rng.randint(12, 18), rng.randint(0, 3))
        rows = _rows(rng, counts_a)
        counts, same_mix = _composition_oracle(rows)
        result = cross_step_tradeoffs(rows, METRIC_DEFS, _data())
        _, naive_dominated = _naive_front(rows)
        oracle_mismatch += int(not same_mix)
        naive_false_fronts += int(not same_mix and len(naive_dominated) >= 2)
        mismatched_refusals += int(
            result.get("population_composition_audit", {}).get("status")
            == "MISMATCHED_DECLARED_STRATUM_DISTRIBUTIONS"
            and result.get("status") == "LIMITED_SCOPE"
            and result.get("mean_pareto_setting_ids") == []
            and result.get("pareto_observation_ids") == [])
        if trial == 0:
            examples["mismatched"] = {"oracle_counts": counts,
                                       "naive_dominated_setting_count": len(naive_dominated),
                                       "p4_status": result.get("status"),
                                       "p4_composition_status": result.get("population_composition_audit", {}).get("status"),
                                       "p4_front": result.get("mean_pareto_setting_ids")}

        # Different sample sizes, same exact 1:1 stratum proportions, with
        # genuine within-stratum process tradeoffs; the compatible front stays available.
        sizes = (30, 40, 50)
        matched_rows = _rows(rng, tuple(size//2 for size in sizes), sizes,
                             ((2.0, 0.8), (0.0, 0.0), (-2.0, -0.8)))
        matched_counts, matched_mix = _composition_oracle(matched_rows)
        matched_result = cross_step_tradeoffs(matched_rows, METRIC_DEFS, _data())
        matched_ok = (matched_mix
                      and matched_result.get("population_composition_audit", {}).get("status")
                      == "MATCHED_DECLARED_STRATUM_DISTRIBUTIONS"
                      and matched_result.get("status") == "VALID"
                      and len(matched_result.get("mean_pareto_setting_ids", [])) > 0)
        matched_fronts += int(matched_ok)
        matched_oracle_agreements += int(matched_mix and matched_ok)
        if trial == 0:
            examples["matched_different_sizes"] = {"oracle_counts": matched_counts,
                "p4_status": matched_result.get("status"),
                "p4_composition_status": matched_result.get("population_composition_audit", {}).get("status"),
                "p4_front_count": len(matched_result.get("mean_pareto_setting_ids", []))}

    mismatch_rate = mismatched_refusals/trials
    naive_rate = naive_false_fronts/trials
    matched_rate = matched_fronts/trials
    passed = (oracle_mismatch == trials and naive_rate >= 0.95
              and mismatch_rate == 1.0 and matched_rate == 1.0
              and matched_oracle_agreements == trials)
    root = Path(__file__).resolve().parents[1]
    product_path = root / "products" / "p4" / "tradeoffs.py"
    script_path = Path(__file__)
    return {
        "schema": "p4-d03-population-mix-benchmark/v1",
        "status": "PASS" if passed else "FAIL",
        "benchmark": "D03_CROSS_STEP_COMPOSITION_SHIFT_FALSE_PARETO",
        "synthetic_only": True, "seed": seed, "trials": trials,
        "mismatched_trials_with_mix_only_naive_dominance": naive_false_fronts,
        "mismatched_population_oracle_trials": oracle_mismatch,
        "p4_composition_refusals": mismatched_refusals,
        "naive_mix_only_false_dominance_rate": naive_rate,
        "p4_mismatch_refusal_rate": mismatch_rate,
        "matched_mix_front_available_rate": matched_rate,
        "matched_mix_oracle_agreements": matched_oracle_agreements,
        "examples": examples,
        "oracle": "independent exact Fraction comparison of product-family proportions and manual two-objective mean dominance",
        "limitations": ["fixed two-stratum synthetic generator; no fab population or effect size claim",
                        "matching observed proportions does not establish exchangeability, randomization, or causal effects",
                        "only source-declared categorical fields can be audited; unmeasured mix differences remain unknown"],
        "product_source_sha256": hashlib.sha256(product_path.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
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
