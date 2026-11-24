"""Compare existing DOE geometries on an independent hidden-response aliasing case.

This is a deterministic geometry challenge, not an estimate of statistical
power, production risk, or a recommendation to execute any proposed run plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from products.p4.design import propose_design  # noqa: E402


BOUNDS = {"pressure": [0.0, 2.0], "power": [0.0, 2.0]}
CONTROLS = list(BOUNDS)
FOUR_FACTOR_CONTROLS = ["pressure", "power", "temperature", "flow"]
FOUR_FACTOR_BOUNDS = {name: [0.0, 2.0] for name in FOUR_FACTOR_CONTROLS}
SIGNAL_EPSILON = 1e-6
STRATEGIES = {
    "full_factorial": {"run_budget": 8, "blocks": 2, "replicates": 2},
    "central_composite": {"run_budget": 10, "blocks": 2, "center_replicates": 2},
    "d_optimal": {"run_budget": 8, "blocks": 2, "candidate_levels": 3},
    "latin_hypercube": {"run_budget": 10, "blocks": 2},
}
FOUR_FACTOR_STRATEGIES = {
    "fractional_factorial": {"run_budget": 8, "blocks": 2},
    "full_factorial": {"run_budget": 16, "blocks": 2},
    "central_composite": {"run_budget": 26, "blocks": 2},
    "d_optimal": {"run_budget": 12, "blocks": 2, "candidate_levels": 3},
    "latin_hypercube": {"run_budget": 12, "blocks": 2},
}


def _hidden_response_component(pressure: float, power: float, amplitude: float,
                               pressure_frequency: int, power_frequency: int) -> float:
    # Exact mathematical zero at the measured 3x3 integer design. The hidden
    # harmonic is nonzero between settings, where the aliasing challenge scores.
    if pressure.is_integer() or power.is_integer():
        return 0.0
    return amplitude * math.sin(pressure_frequency * math.pi * pressure) * math.sin(
        power_frequency * math.pi * power)


def _run_design(strategy: str, seed: int) -> list[dict]:
    spec = {**STRATEGIES[strategy], "seed": seed}
    result = propose_design(strategy, CONTROLS, BOUNDS, spec, [])
    if result.get("status") != "PROPOSED" or result.get("executed") is not False:
        raise RuntimeError(f"{strategy} did not return a non-executing proposal")
    return result["runs"]


def _run_four_factor_design(strategy: str, seed: int) -> list[dict]:
    result = propose_design(strategy, FOUR_FACTOR_CONTROLS, FOUR_FACTOR_BOUNDS,
                            {**FOUR_FACTOR_STRATEGIES[strategy], "seed": seed}, [])
    if result.get("status") != "PROPOSED" or result.get("executed") is not False:
        raise RuntimeError(f"four-factor {strategy} did not return a non-executing proposal")
    return result["runs"]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int((len(ordered)-1)*fraction))]


def run_benchmark(trials: int = 200, seed: int = 20261124) -> dict:
    if trials < 1:
        raise ValueError("at least one trial is required")
    maxima = {strategy: [] for strategy in STRATEGIES}
    run_signal_count = {strategy: 0 for strategy in STRATEGIES}
    run_total = {strategy: 0 for strategy in STRATEGIES}
    runs_per_strategy = {}
    four_factor_maxima = {strategy: [] for strategy in FOUR_FACTOR_STRATEGIES}
    four_factor_run_signal_count = {strategy: 0 for strategy in FOUR_FACTOR_STRATEGIES}
    four_factor_run_total = {strategy: 0 for strategy in FOUR_FACTOR_STRATEGIES}
    four_factor_runs_per_strategy = {}
    for trial in range(trials):
        trial_seed = seed + trial
        rng = random.Random(trial_seed)
        amplitude = rng.uniform(0.03, 0.11)
        pressure_frequency = rng.choice((1, 3, 5))
        power_frequency = rng.choice((1, 3, 5))
        for strategy in STRATEGIES:
            runs = _run_design(strategy, trial_seed)
            runs_per_strategy.setdefault(strategy, len(runs))
            if len(runs) != runs_per_strategy[strategy]:
                raise RuntimeError(f"{strategy} changed run count across fixed seeds")
            signals = [abs(_hidden_response_component(
                float(run["pressure"]), float(run["power"]), amplitude,
                pressure_frequency, power_frequency)) for run in runs]
            maxima[strategy].append(max(signals, default=0.0))
            run_signal_count[strategy] += sum(value > SIGNAL_EPSILON for value in signals)
            run_total[strategy] += len(signals)

        four_rng = random.Random(seed + 1_000_000 + trial)
        amplitude4 = four_rng.uniform(0.03, 0.11)
        frequencies4 = [four_rng.choice((1, 3, 5)) for _ in FOUR_FACTOR_CONTROLS]
        for strategy in FOUR_FACTOR_STRATEGIES:
            runs = _run_four_factor_design(strategy, trial_seed)
            four_factor_runs_per_strategy.setdefault(strategy, len(runs))
            if len(runs) != four_factor_runs_per_strategy[strategy]:
                raise RuntimeError(f"four-factor {strategy} changed run count across fixed seeds")
            signals = [abs(amplitude4 * math.prod(math.sin(
                frequency * math.pi * float(run[name]))
                for name, frequency in zip(FOUR_FACTOR_CONTROLS, frequencies4)))
                for run in runs]
            four_factor_maxima[strategy].append(max(signals, default=0.0))
            four_factor_run_signal_count[strategy] += sum(value > SIGNAL_EPSILON for value in signals)
            four_factor_run_total[strategy] += len(signals)

    strategies = {}
    for strategy in STRATEGIES:
        values = maxima[strategy]
        strategies[strategy] = {
            "runs_per_trial": runs_per_strategy[strategy],
            "trials_with_signal_over_epsilon": sum(value > SIGNAL_EPSILON for value in values),
            "trial_signal_fraction": sum(value > SIGNAL_EPSILON for value in values) / trials,
            "run_signal_fraction": run_signal_count[strategy] / run_total[strategy],
            "mean_trial_max_abs_hidden_response": statistics.mean(values),
            "median_trial_max_abs_hidden_response": statistics.median(values),
            "p95_trial_max_abs_hidden_response": _percentile(values, 0.95),
        }
    four_factor_strategies = {}
    for strategy, values in four_factor_maxima.items():
        four_factor_strategies[strategy] = {
            "runs_per_trial": four_factor_runs_per_strategy[strategy],
            "trials_with_signal_over_epsilon": sum(value > SIGNAL_EPSILON for value in values),
            "trial_signal_fraction": sum(value > SIGNAL_EPSILON for value in values) / trials,
            "run_signal_fraction": four_factor_run_signal_count[strategy] / four_factor_run_total[strategy],
            "mean_trial_max_abs_hidden_response": statistics.mean(values),
            "median_trial_max_abs_hidden_response": statistics.median(values),
            "p95_trial_max_abs_hidden_response": _percentile(values, 0.95),
        }
    geometry_pass = (
        all(strategies[name]["trials_with_signal_over_epsilon"] == 0
            for name in ("full_factorial", "central_composite", "d_optimal"))
        and strategies["latin_hypercube"]["trials_with_signal_over_epsilon"] > 0
        and all(four_factor_strategies[name]["trials_with_signal_over_epsilon"] == 0
                for name in ("fractional_factorial", "full_factorial", "central_composite", "d_optimal"))
        and four_factor_strategies["latin_hypercube"]["trials_with_signal_over_epsilon"] > 0
        and all(item["runs_per_trial"] > 0 for item in strategies.values())
        and all(item["runs_per_trial"] > 0 for item in four_factor_strategies.values())
    )
    return {
        "schema": "p4-d04-design-aliasing-benchmark/v2",
        "status": "PASS_GEOMETRY_CHALLENGE" if geometry_pass else "FAIL",
        "trials": trials,
        "seed": seed,
        "factor_bounds": BOUNDS,
        "observed_design": {"levels_per_factor": [0.0, 1.0, 2.0], "interpretation": "existing measured settings"},
        "hidden_surface": "amplitude times sin(k*pi*pressure)*sin(j*pi*power), frequencies independently chosen from {1,3,5}; exactly zero whenever either factor is at an integer setting",
        "signal_epsilon": SIGNAL_EPSILON,
        "strategies": strategies,
        "four_factor_controls": FOUR_FACTOR_CONTROLS,
        "four_factor_hidden_surface": "amplitude times the product of sin(k_i*pi*x_i) over four factors, with independent frequencies from {1,3,5}; the response is zero at every tested integer-level design point",
        "four_factor_strategies": four_factor_strategies,
        "statistical_power_evaluated": False,
        "decision": "In the two-factor challenge, two-level factorial, 3-level-grid D-optimal, and face-centered central-composite geometries are blind. In the four-factor challenge, the resolution-IV half-fraction is also blind to the constructed higher-order response. Latin-hypercube samples expose signal off-grid in the recorded trials; this geometry-only result does not establish inferential power or production safety.",
        "limitations": [
            "the known harmonic band is synthetic and finite; other hidden functions can evade any finite design",
            "measurement noise, lot/chamber blocking effects, multiplicity, effect estimation, cost, and operational feasibility are not modeled",
            "the result distinguishes design geometry only; it does not recommend executing a design or alter the runtime strategy selector",
        ],
        "product_design_sha256": hashlib.sha256((ROOT / "products/p4/design.py").read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--output", type=Path, default=ROOT / "qualification/results/D04_ALIASING_BENCHMARK.json")
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "trials": result["trials"],
                      "strategies": result["strategies"]}, indent=2))
    return 0 if result["status"] == "PASS_GEOMETRY_CHALLENGE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
