#!/usr/bin/env python3
"""Independent known-effect/confounder challenge for the D05 DiD bound gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
import subprocess

from products.p4.engine import _effectiveness

ROOT = Path(__file__).resolve().parent.parent


def wilson(successes: int, trials: int) -> list[float]:
    if trials == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = successes / trials
    den = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / den
    half = z * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5) / den
    return [center - half, center + half]


def run(trials: int = 1000, seed: int = 20261123) -> dict:
    rng = random.Random(seed)
    naive_covers = oracle_bound_covers = underbound_covers = 0
    underbound_eligible = underbound_assumptions_passed = assumptions_passed_wrong_direction = emitted_causal_claims = 0
    underbound_sensitivity = []
    for trial in range(trials):
        # The hidden post-period shock is deliberately larger than the true
        # intervention effect and has the opposite sign. Preperiods remain flat.
        true_effect = 0.5 if trial % 2 == 0 else -0.5
        bias_sign = -1 if true_effect > 0 else 1
        hidden_bias = bias_sign * rng.uniform(1.0, 2.0)
        oracle_bound = abs(hidden_bias)
        caller_underbound = oracle_bound * 0.25
        rows = []
        ledger = []
        for group in ("treatment", "control"):
            for unit in range(30):
                unit_id = f"SYN-{trial}-{group}-{unit}"
                ledger.append({"unit_id": unit_id, "group": group})
                base = 100.0 + unit * 0.02
                product = "SYN-A" if unit < 15 else "SYN-B"
                common = true_effect + hidden_bias if group == "treatment" else 0.0
                noise = rng.gauss(0.0, 1.0)
                period_times = {"pre2": "2025-11-01T00:00:00Z", "pre": "2025-12-01T00:00:00Z",
                                "post": "2026-02-01T00:00:00Z"}
                for period, value in (("pre2", base), ("pre", base + 0.1),
                                      ("post", base + 0.1 + common + noise)):
                    rows.append({"unit_id": unit_id, "group": group, "period": period,
                                 "quality": value, "timestamp": period_times[period], "product_id": product})
        study = {
            "authorized": True,
            "authorization_id": f"SYN-AUTH-{trial}",
            "intervention_id": f"SYN-CHANGE-{trial}",
            "design": "difference_in_differences",
            "intervention_time": "2026-01-01T00:00:00Z",
            "metric": "quality",
            "metric_unit": "synthetic quality unit",
            "assignment_ledger": ledger,
            "population_fields": ["product_id"],
            "pretrend_equivalence_bound": 0.25,
            "pretrend_equivalence_bound_unit": "synthetic quality unit",
            "pretrend_equivalence_bound_source": "SYN-PRE-SOURCE",
            "pretrend_equivalence_bound_method": "SYN-PRESPECIFIED",
            "differential_trend_bound": caller_underbound,
            "differential_trend_bound_unit": "synthetic quality unit",
            "differential_trend_bound_source": "SYN-UNDERBOUND-CHALLENGE",
            "differential_trend_bound_method": "one-quarter-known-hidden-shock",
            "observations": rows,
        }
        result = _effectiveness({"effectiveness": study})
        assert result["status"] == "ESTIMATED", result
        point = result["estimate"]
        raw_ci = result["ci95_welch_t_approximation"]
        expanded = result["sensitivity"]["ci95_under_bound"]
        naive_covers += raw_ci[0] <= true_effect <= raw_ci[1]
        oracle_bound_covers += raw_ci[0] - oracle_bound <= true_effect <= raw_ci[1] + oracle_bound
        underbound_covers += expanded[0] <= true_effect <= expanded[1]
        eligible = result["conditional_interpretation_eligible"]
        underbound_eligible += bool(eligible)
        gates_passed = result["conditional_assumptions_passed"]
        underbound_assumptions_passed += bool(gates_passed)
        wrong_direction = (point > 0 > true_effect) or (point < 0 < true_effect)
        assumptions_passed_wrong_direction += bool(gates_passed and wrong_direction)
        emitted_causal_claims += bool(result["causal_claim"])
        underbound_sensitivity.append(abs(point - true_effect))
    return {
        "schema": "p4-d05-known-confounder-benchmark/v1",
        "source_provenance": {
            "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                               capture_output=True, text=True).stdout.strip(),
            "engine_sha256": hashlib.sha256((ROOT / "products/p4/engine.py").read_bytes()).hexdigest(),
            "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "method": "independent-unit two-preperiod/one-post DiD; injected treatment-only post shock; fixed source-bound underestimation at 25% of the known shock",
        "seed": seed,
        "trials": trials,
        "true_effect_values": [-0.5, 0.5],
        "hidden_bias_abs_range": [1.0, 2.0],
        "observed_ci95_true_effect_coverage": {
            "count": naive_covers, "rate": naive_covers / trials,
            "wilson95": wilson(naive_covers, trials)},
        "sensitivity_ci95_coverage_with_oracle_adequate_bound": {
            "count": oracle_bound_covers, "rate": oracle_bound_covers / trials,
            "wilson95": wilson(oracle_bound_covers, trials)},
        "sensitivity_ci95_coverage_with_underbound": {
            "count": underbound_covers, "rate": underbound_covers / trials,
            "wilson95": wilson(underbound_covers, trials)},
        "underbound_cases_marked_interpretation_eligible": underbound_eligible,
        "underbound_cases_passing_numerical_assumption_gates": underbound_assumptions_passed,
        "underbound_cases_passing_numerical_gates_with_wrong_true_effect_direction": assumptions_passed_wrong_direction,
        "observational_did_causal_claims_emitted": emitted_causal_claims,
        "mean_absolute_naive_effect_bias": sum(underbound_sensitivity) / trials,
        "qualification": "Synthetic known-generator challenge only. The source-bound interval covers the true effect only when its assumed differential-trend bound is adequate; caller-supplied source/method labels cannot establish adequacy. P4 returns no observational DiD causal claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.trials, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
