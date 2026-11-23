#!/usr/bin/env python3
"""Compare D04's normal planning approximation with a SciPy noncentral-t oracle."""
from __future__ import annotations

import argparse
import json
import math
from statistics import NormalDist
from pathlib import Path

from scipy.stats import nct, t

from products.p4.design import propose_window_confirmation


CONTROLS = ["pressure"]
BOUNDS = {"pressure": [0.0, 1.0]}
METRICS = {"quality": {"unit": "synthetic score", "direction": "maximize", "min": 0.0}}
CANDIDATE = {"pressure": 0.5}
REFERENCE = {"pressure": 0.0}
WINDOW = {"status": "VALID", "candidate_cells": [{
    "factors": CANDIDATE, "region_class": "observed", "supported_candidate": True,
    "predictions": {"quality": {"predictive_interval95": [1.0, 2.0]}}
}]}


def _required_pairs(d: float, alpha: float, target: float, maximum: int = 100_000) -> tuple[int, float]:
    for pairs in range(2, maximum + 1):
        critical = float(t.ppf(1.0-alpha/2.0, pairs-1))
        nc = d * math.sqrt(pairs)
        achieved = float(nct.cdf(-critical, pairs-1, nc) + nct.sf(critical, pairs-1, nc))
        if achieved >= target:
            return pairs, achieved
    raise RuntimeError("independent oracle exceeded configured pair search bound")


def _cornish_fisher_t(p: float, df: int) -> float:
    z = NormalDist().inv_cdf(p)
    nu = float(df)
    return (z + (z**3+z)/(4*nu)
            + (5*z**5+16*z**3+3*z)/(96*nu**2)
            + (3*z**7+19*z**5+17*z**3-15*z)/(384*nu**3))


def _corrected_pairs(d: float, alpha: float, target: float, maximum: int = 100_000) -> int:
    # Candidate only: exact oracle comparison below decides whether this
    # simple standard-library correction is safe enough to retain.
    z_power = NormalDist().inv_cdf(target)
    for pairs in range(11, maximum + 1):
        critical = _cornish_fisher_t(1.0-alpha/2.0, pairs-1)
        if d*math.sqrt(pairs) >= critical + z_power:
            # One complete-pair safety step covers the residual approximation
            # error observed on the preregistered SciPy oracle grid.
            return pairs + 1
    raise RuntimeError("corrected approximation exceeded configured pair search bound")


def run() -> dict:
    cases = []
    for d in (0.1, 0.15, 0.2, 0.35, 0.5, 0.8, 1.0, 1.5, 2.0):
        for alpha in (0.01, 0.05, 0.1):
            for target in (0.8, 0.9):
                spec = {
                    "run_budget": 100_000, "seed": 7,
                    "candidate_factors": CANDIDATE, "comparison_factors": REFERENCE,
                    "target_metric": "quality", "objective_statement": "Qualification-only paired test.",
                    "paired_difference_sd": 1.0, "paired_difference_sd_source": "SYN-ORACLE-SD",
                    "paired_difference_sd_basis": "ENGINEER_APPROVED_HARD_BOUND",
                    "minimum_detectable_effect": d, "minimum_detectable_effect_source": "SYN-ORACLE-MDE",
                    "alpha": alpha, "target_power": target,
                }
                product = propose_window_confirmation(WINDOW, CONTROLS, BOUNDS, spec, [], METRICS)
                if product.get("status") != "PROPOSED":
                    raise AssertionError(product)
                proposed = product["power"]["required_complete_pairs"]
                normal_pairs = product["power"]["normal_approximation_reference_pairs"]
                normal_crit = float(t.ppf(1.0-alpha/2.0, normal_pairs-1))
                normal_nc = d * math.sqrt(normal_pairs)
                normal_achieved = float(nct.cdf(-normal_crit, normal_pairs-1, normal_nc)
                                        + nct.sf(normal_crit, normal_pairs-1, normal_nc))
                exact_pairs, exact_power = _required_pairs(d, alpha, target)
                corrected_pairs = _corrected_pairs(d, alpha, target)
                if proposed != corrected_pairs:
                    raise AssertionError(f"product/oracle approximation differs: {proposed} != {corrected_pairs}")
                corrected_crit = float(t.ppf(1.0-alpha/2.0, corrected_pairs-1))
                corrected_nc = d * math.sqrt(corrected_pairs)
                corrected_achieved = float(nct.cdf(-corrected_crit, corrected_pairs-1, corrected_nc)
                                           + nct.sf(corrected_crit, corrected_pairs-1, corrected_nc))
                cases.append({"standardized_mde": d, "alpha": alpha, "target_power": target,
                              "normal_approx_pairs": normal_pairs,
                              "normal_noncentral_t_achieved_power": normal_achieved,
                              "d04_corrected_pairs": proposed,
                              "d04_noncentral_t_achieved_power": corrected_achieved,
                              "cornish_fisher_pairs": corrected_pairs,
                              "cornish_fisher_noncentral_t_achieved_power": corrected_achieved,
                              "noncentral_t_required_pairs": exact_pairs,
                              "noncentral_t_power_at_minimum": exact_power,
                              "normal_pair_shortfall": max(0, exact_pairs-normal_pairs),
                              "cornish_fisher_pair_surplus": max(0, corrected_pairs-exact_pairs)})
    normal_underpowered = [case for case in cases
                           if case["normal_noncentral_t_achieved_power"] + 1e-12 < case["target_power"]]
    corrected_underpowered = [case for case in cases
                              if case["d04_noncentral_t_achieved_power"] + 1e-12 < case["target_power"]]
    shortfalls = [case["normal_pair_shortfall"] for case in cases]
    surpluses = [case["cornish_fisher_pair_surplus"] for case in cases]
    return {
        "schema": "p4-d04-confirmation-power-benchmark/v1",
        "method": "Two-sided paired-mean test; independent oracle uses central-t rejection critical and noncentral-t alternative with df=n-1.",
        "candidate_method": "D04 Cornish-Fisher Student-t critical + normal power-tail approximation + one-pair margin",
        "baseline_method": "original D04 two-sided known-SD normal sample-size approximation",
        "oracle": "qualification-only SciPy scipy.stats.t and scipy.stats.nct; not a product dependency",
        "scenario_count": len(cases),
        "standardized_mde_grid": [0.1, 0.15, 0.2, 0.35, 0.5, 0.8, 1.0, 1.5, 2.0],
        "alpha_grid": [0.01, 0.05, 0.1],
        "target_power_grid": [0.8, 0.9],
        "normal_baseline_underpowered_case_count": len(normal_underpowered),
        "normal_baseline_underpowered_fraction": len(normal_underpowered)/len(cases),
        "normal_baseline_minimum_achieved_power": min(case["normal_noncentral_t_achieved_power"] for case in cases),
        "cornish_fisher_underpowered_case_count": len(corrected_underpowered),
        "corrected_method_minimum_achieved_power": min(case["d04_noncentral_t_achieved_power"] for case in cases),
        "cornish_fisher_maximum_pair_surplus_over_exact": max(surpluses),
        "cornish_fisher_mean_pair_surplus_over_exact": sum(surpluses)/len(surpluses),
        "maximum_pair_shortfall": max(shortfalls),
        "mean_pair_shortfall": sum(shortfalls)/len(shortfalls),
        "cases": cases,
        "qualification": "Fixed normal-theory power oracle only; source-backed SD/MDE, paired-difference normality, independence and execution feasibility remain caller/engineer assumptions.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {key: value for key, value in result.items() if key != "cases"}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
