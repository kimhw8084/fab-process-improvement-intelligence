"""Stress the supported D02 confirmation-planning domain against SciPy's exact oracle."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from scipy.stats import nct, t

from products.p4.design import propose_window_confirmation


ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ["pressure"]
BOUNDS = {"pressure": [0.0, 1.0]}
METRICS = {"quality": {"unit": "synthetic score", "direction": "maximize", "min": 0.0}}
CANDIDATE = {"pressure": 0.5}
REFERENCE = {"pressure": 0.0}
WINDOW = {"status": "VALID", "candidate_cells": [{
    "factors": CANDIDATE, "region_class": "observed", "supported_candidate": True,
    "predictions": {"quality": {"predictive_interval95": [1.0, 2.0]}}
}]}


def run() -> dict:
    design_path = ROOT / "products/p4/design.py"
    alphas = [round(value / 100, 2) for value in range(1, 11)]
    targets = [0.8, 0.85, 0.9]
    effects = [0.04, 0.06, 0.08, 0.12, 0.2, 0.35, 0.5, 0.8, 1.2, 2.0, 3.0, 5.0]
    cases = []
    parameters = [(effect, alpha, target) for effect in effects for alpha in alphas for target in targets]
    rng = random.Random(20261124)
    parameters.extend((round(10 ** rng.uniform(-1.4, 0.7), 6),
                       round(rng.uniform(0.01, 0.1), 6),
                       round(rng.uniform(0.8, 0.9), 6)) for _ in range(200))
    for effect, alpha, target in parameters:
        spec = {
            "run_budget": 100_000, "seed": 811,
            "candidate_factors": CANDIDATE, "comparison_factors": REFERENCE,
            "target_metric": "quality", "objective_statement": "Synthetic oracle qualification only.",
            "paired_difference_sd": 1.0, "paired_difference_sd_source": "SYN-ORACLE-SD",
            "paired_difference_sd_basis": "ENGINEER_APPROVED_HARD_BOUND",
            "minimum_detectable_effect": effect, "minimum_detectable_effect_source": "SYN-ORACLE-MDE",
            "alpha": alpha, "target_power": target,
        }
        proposal = propose_window_confirmation(WINDOW, CONTROLS, BOUNDS, spec, [], METRICS)
        if proposal.get("status") != "PROPOSED":
            raise AssertionError({"effect": effect, "alpha": alpha, "target": target,
                                 "proposal": proposal})
        pairs = proposal["power"]["required_complete_pairs"]
        df = pairs - 1
        critical = float(t.ppf(1.0 - alpha / 2.0, df))
        noncentrality = effect * pairs**0.5
        achieved = float(nct.cdf(-critical, df, noncentrality)
                         + nct.sf(critical, df, noncentrality))
        cases.append({"standardized_mde": effect, "alpha": alpha, "target_power": target,
                      "proposed_pairs": pairs, "oracle_achieved_power": achieved,
                      "power_margin": achieved - target})

    refusal_cases = []
    for alpha, target in ((0.001, 0.8), (0.005, 0.8), (0.15, 0.8),
                          (0.05, 0.75), (0.05, 0.95)):
        spec = {
            "run_budget": 100_000, "seed": 811,
            "candidate_factors": CANDIDATE, "comparison_factors": REFERENCE,
            "target_metric": "quality", "objective_statement": "Synthetic refusal qualification.",
            "paired_difference_sd": 1.0, "paired_difference_sd_source": "SYN-ORACLE-SD",
            "paired_difference_sd_basis": "ENGINEER_APPROVED_HARD_BOUND",
            "minimum_detectable_effect": 0.5, "minimum_detectable_effect_source": "SYN-ORACLE-MDE",
            "alpha": alpha, "target_power": target,
        }
        result = propose_window_confirmation(WINDOW, CONTROLS, BOUNDS, spec, [], METRICS)
        refused = result.get("status") == "REFUSED" and result.get("run_count") == 0
        refusal_cases.append({"alpha": alpha, "target_power": target, "refused_without_runs": refused})

    margins = [case["power_margin"] for case in cases]
    underpowered = [case for case in cases if case["power_margin"] < -1e-10]
    source_sha = hashlib.sha256(design_path.read_bytes()).hexdigest()
    script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "schema": "p4-d04-confirmation-domain-benchmark/v1",
        "status": "PASS" if not underpowered and all(case["refused_without_runs"] for case in refusal_cases) else "FAIL",
        "oracle": "SciPy central Student-t critical and noncentral-t two-sided power; qualification-only, not a runtime dependency",
        "assumptions": ["independent normally distributed paired differences",
                        "supplied SD is a valid conservative upper bound",
                        "the MDE and target population are prespecified and relevant"],
        "supported_domain": {"alpha": [0.01, 0.1], "target_power": [0.8, 0.9]},
        "standardized_mde_grid": effects,
        "alpha_grid": alphas,
        "target_power_grid": targets,
        "case_count": len(cases),
        "randomized_interior_draws": 200,
        "underpowered_cases": len(underpowered),
        "minimum_oracle_power_margin": min(margins),
        "minimum_oracle_achieved_power": min(case["oracle_achieved_power"] for case in cases),
        "maximum_pair_count": max(case["proposed_pairs"] for case in cases),
        "out_of_domain_refusal_cases": refusal_cases,
        "product_source_sha256": source_sha,
        "benchmark_script_sha256": script_sha,
        "scope": "Finite deterministic normal-theory oracle grid only; no power or distribution guarantee for production or nonnormal/dependent paired differences.",
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "qualification/results/D04_CONFIRMATION_DOMAIN_BENCHMARK.json")
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
