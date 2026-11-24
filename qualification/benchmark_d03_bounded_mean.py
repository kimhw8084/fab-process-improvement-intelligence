"""Independent skewed-support challenge for D03's optional Hoeffding envelope.

The generator and truth are defined in qualification code. Product output is
tested on a repeated-lot, four-setting, two-objective family with equal true
means. This finite challenge validates the implementation against its stated
bounded-iid assumptions; it does not authenticate caller bounds or prove any
manufacturing-population guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from products.p4.tradeoffs import observed_tradeoffs
from qualification.benchmark import product_source_fingerprint


SETTINGS = (1.0, 2.0, 3.0, 4.0)
OBJECTIVES = [{"metric": "quality", "direction": "maximize"},
              {"metric": "defect", "direction": "minimize"}]
METRIC_DEFS = {"quality": {"unit": "score", "direction": "maximize"},
               "defect": {"unit": "fraction", "direction": "minimize"}}
FACTOR_DEFS = {"pressure": {"role": "controllable", "unit": "u"}}
OBSERVED_SPEC = {"tradeoff_unit_field": "lot_id", "tradeoff_min_independent_units": 11}
BOUNDS_CONTRACT = {
    "precommit_reference": "SYNTHETIC-CHALLENGE-PLAN-v1",
    "bounds_source_reference": "SYNTHETIC-GENERATOR-SUPPORT-v1",
    "candidate_setting_ids": [f"SYN-SETTING-{setting:g}" for setting in SETTINGS],
    "metric_units": {"quality": "score", "defect": "fraction"},
    "metric_bounds": {"quality": [0.0, 1.0], "defect": [0.0, 1.0]},
}
T_PRECOMMIT = {
    "precommit_reference": "SYNTHETIC-T-FAMILY-PLAN-v1",
    "candidate_setting_ids": [f"SYN-SETTING-{setting:g}" for setting in SETTINGS],
    "objectives": OBJECTIVES,
}
TRUTH = {"quality": 0.45 / 2.45,
         "defect": 1.0 - 0.45 / 2.45}


def wilson(successes: int, trials: int) -> list[float]:
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z*z/trials
    center = (p + z*z/(2*trials))/denominator
    half = z*math.sqrt((p*(1-p) + z*z/(4*trials))/trials)/denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def draw_rows(rng: random.Random, units: int) -> list[dict]:
    rows = []
    for unit in range(units):
        common_quality = rng.betavariate(0.45, 2.0)
        common_defect = 1.0 - rng.betavariate(0.45, 2.0)
        for setting in SETTINGS:
            quality = 0.65*common_quality + 0.35*rng.betavariate(0.45, 2.0)
            defect = 0.65*common_defect + 0.35*(1.0-rng.betavariate(0.45, 2.0))
            rows.append({"id": f"SYN-OBS-{unit}-{setting:g}", "lot_id": f"SYN-LOT-{unit:04d}",
                         "factors": {"pressure": setting},
                         "metrics": {"quality": quality, "defect": defect}})
    return rows


def evaluate_method(rows: list[dict], units: int, bounded: bool) -> tuple[bool, bool, float]:
    data = dict(OBSERVED_SPEC)
    # The approximate t path is available only for this exact declared family.
    # The synthetic reference tests matching, not that the caller precommitted.
    data["familywise_t_precommit"] = T_PRECOMMIT
    if bounded:
        data["familywise_mean_bounds"] = BOUNDS_CONTRACT
    result = observed_tradeoffs(rows, METRIC_DEFS, FACTOR_DEFS, data, OBJECTIVES)
    envelope = result["familywise_mean_envelope"]
    expected_status = ("AVAILABLE_BOUNDED_HOEFFDING_ENVELOPE" if bounded
                       else "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE")
    if envelope.get("status") != expected_status:
        raise RuntimeError(f"D03 method did not qualify: {envelope}")
    intervals = []
    for candidate in result["candidate_settings"]:
        if candidate["independent_units"] != units:
            raise RuntimeError("D03 lost independent units in the fixed challenge panel")
        for metric, truth in TRUTH.items():
            interval = candidate["uncertainty"][metric]["familywise_ci95"]
            intervals.append((interval[0] <= truth <= interval[1], interval[1]-interval[0]))
    jointly_covered = all(covered for covered, _ in intervals)
    false_familywise_dominance = bool(result["familywise_interval_separated_dominance"])
    mean_width = sum(width for _, width in intervals) / len(intervals)
    return jointly_covered, false_familywise_dominance, mean_width


def run_benchmark(trials: int = 500, seed: int = 20261123) -> dict:
    if trials < 200:
        raise ValueError("D03 bounded-mean challenge requires at least 200 trials per sample size")
    rng = random.Random(seed)
    results = {}
    for units in (30, 60):
        counts = {"bonferroni_t": {"covered": 0, "false_dominance": 0, "widths": []},
                  "bounded_hoeffding": {"covered": 0, "false_dominance": 0, "widths": []}}
        for _ in range(trials):
            rows = draw_rows(rng, units)
            for method, bounded in (("bonferroni_t", False), ("bounded_hoeffding", True)):
                covered, false_dominance, width = evaluate_method(rows, units, bounded)
                counts[method]["covered"] += int(covered)
                counts[method]["false_dominance"] += int(false_dominance)
                counts[method]["widths"].append(width)
        results[str(units)] = {
            "independent_units_per_setting": units,
            "trials": trials,
            "true_means": TRUTH,
            "methods": {
                method: {
                    "joint_mean_coverage_rate": value["covered"] / trials,
                    "joint_mean_coverage_wilson95": wilson(value["covered"], trials),
                    "false_familywise_dominance_rate": value["false_dominance"] / trials,
                    "mean_interval_width": sum(value["widths"]) / len(value["widths"]),
                }
                for method, value in counts.items()
            },
        }
    source_hashes, source_manifest_hash = product_source_fingerprint()
    script_path = Path(__file__).resolve()
    return {
        "schema": "p4-d03-bounded-mean-benchmark/v1",
        "status": "PASS" if all(
            item["methods"]["bounded_hoeffding"]["joint_mean_coverage_wilson95"][0] >= 0.95
            and item["methods"]["bounded_hoeffding"]["false_familywise_dominance_rate"] <= 0.05
            for item in results.values()) else "FAIL",
        "product_source_sha256": source_hashes,
        "product_source_manifest_sha256": source_manifest_hash,
        "qualification_script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "seed": seed,
        "objective_family_size": 8,
        "t_family_precommit_contract": {
            "reference": T_PRECOMMIT["precommit_reference"],
            "candidate_setting_ids": T_PRECOMMIT["candidate_setting_ids"],
            "objectives": T_PRECOMMIT["objectives"],
            "authentication": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
        },
        "candidate_settings": list(BOUNDS_CONTRACT["candidate_setting_ids"]),
        "support": "Each independent-lot aggregate is a convex combination of Beta draws and lies in [0,1].",
        "generator": "Highly right-skewed quality Beta(0.45,2) and reflected defect; a shared lot component induces cross-setting correlation while preserving independent lots and the exact marginal means.",
        "bounds_contract": "Synthetic generator support is [0,1] in the declared metric units. Product callers must supply independently justified hard bounds; P4 never infers them from observed extrema and never authenticates references.",
        "scenario_results": results,
        "limitations": [
            "Monte Carlo evidence on one bounded skewed generator does not prove distribution-free coverage; the theorem depends on independent units and truthful hard support bounds.",
            "Candidate IDs and metric family are matched exactly at runtime, but the supplied precommit reference is not authenticated.",
            "The approximate t-envelope challenge uses a fixed synthetic caller-declared setting/objective family; it does not establish that real users selected the family before seeing outcomes.",
            "Wide Hoeffding intervals can prevent useful dominance decisions; interval separation is neither causal nor population harmonization.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.trials, args.seed)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
