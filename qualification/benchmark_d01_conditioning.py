"""Known-effect sensitivity challenge for D01 near-collinear factor designs.

Each predictor design is fixed before outcomes. The response includes two
known separate effects plus independent homoskedastic noise. Across generated
outcomes, this records coefficient sign error, marginal interval coverage,
and interval width while checking that the product surfaces its descriptive
QR-condition heuristic. It does not validate arbitrary data-generating models.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from products.p4.regression import fit_linear_model


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "products" / "p4" / "regression.py"
SCRIPT = Path(__file__)
FACTORS = {"x": {"role": "measured", "unit": "u"},
           "z": {"role": "measured", "unit": "u"}}
TRUE_COEFFICIENTS = {"x": 2.0, "z": -1.0}
JITTER_LEVELS = (0.2, 0.05, 0.02, 0.01, 0.003)


def _wilson(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    denominator = 1.0 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * math.sqrt((p*(1-p) + z*z/(4*total))/total) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def _median(values: list[float]) -> float:
    return statistics.median(values)


def run_benchmark(trials: int = 250, seed: int = 20261123,
                  observations: int = 120) -> dict:
    if trials < 100 or observations < 40:
        raise ValueError("requires at least 100 trials and 40 observations")
    scenario_results = {}
    for level_index, jitter in enumerate(JITTER_LEVELS):
        design_rng = random.Random(seed + 1009 * level_index)
        x_values = [design_rng.gauss(0.0, 1.0) for _ in range(observations)]
        z_noise = [design_rng.gauss(0.0, 1.0) for _ in range(observations)]
        z_values = [x + jitter*noise for x, noise in zip(x_values, z_noise)]
        condition_values = []
        sign_errors = {factor: 0 for factor in TRUE_COEFFICIENTS}
        covered = {factor: 0 for factor in TRUE_COEFFICIENTS}
        widths = {factor: [] for factor in TRUE_COEFFICIENTS}
        valid_fits = 0
        elevated_flags = 0
        severe_flags = 0
        noise_rng = random.Random(seed + 7919 * (level_index + 1))
        for trial in range(trials):
            rows = []
            for index, (x, z) in enumerate(zip(x_values, z_values)):
                y = 1.0 + TRUE_COEFFICIENTS["x"]*x + TRUE_COEFFICIENTS["z"]*z
                y += noise_rng.gauss(0.0, 0.5)
                rows.append({"id": f"J{level_index}-{trial}-{index}",
                             "factors": {"x": x, "z": z}, "metrics": {"y": y}})
            report, _ = fit_linear_model(rows, FACTORS, "y")
            if report.get("status") != "VALID":
                continue
            valid_fits += 1
            diagnostics = report.get("diagnostics", {})
            condition_values.append(float(diagnostics["condition_proxy"]))
            severity = diagnostics.get("condition_proxy_interpretation", {}).get("status")
            elevated_flags += int(severity in {"ELEVATED_HEURISTIC", "SEVERE_HEURISTIC"})
            severe_flags += int(severity == "SEVERE_HEURISTIC")
            for factor, truth in TRUE_COEFFICIENTS.items():
                term = report["terms"][factor]
                sign_errors[factor] += int(float(term["estimate"]) * truth < 0)
                low, high = term["ci95"]
                covered[factor] += int(low <= truth <= high)
                widths[factor].append(float(high - low))
        if valid_fits != trials:
            raise RuntimeError(f"full-rank design did not yield valid fits for jitter {jitter}: {valid_fits}/{trials}")
        scenario_results[f"{jitter:g}"] = {
            "jitter_sd_added_to_z": jitter,
            "trials": trials,
            "median_condition_proxy": _median(condition_values),
            "valid_fit_fraction": valid_fits / trials,
            "heuristic_warning_fraction": elevated_flags / trials,
            "severe_heuristic_fraction": severe_flags / trials,
            "per_factor": {
                factor: {
                    "true_coefficient": truth,
                    "wrong_sign_fraction": sign_errors[factor] / trials,
                    "wrong_sign_wilson95": _wilson(sign_errors[factor], trials),
                    "marginal_ci95_coverage": covered[factor] / trials,
                    "median_ci95_width": _median(widths[factor]),
                }
                for factor, truth in TRUE_COEFFICIENTS.items()
            },
            "interpretation": "known-effect fixed-design Monte Carlo; coefficient intervals are marginal and not simultaneous",
        }

    baseline = scenario_results["0.2"]
    severe = scenario_results["0.003"]
    minimum_severe_sign_error = min(
        value["wrong_sign_fraction"] for value in severe["per_factor"].values())
    minimum_width_ratio = min(
        severe["per_factor"][factor]["median_ci95_width"]
        / baseline["per_factor"][factor]["median_ci95_width"]
        for factor in TRUE_COEFFICIENTS)
    return {
        "schema": "p4-d01-conditioning-benchmark/v1",
        "method": "fixed-design independent Gaussian-noise Monte Carlo with known separate coefficients",
        "seed": seed,
        "trials_per_design": trials,
        "observations_per_trial": observations,
        "true_coefficients": TRUE_COEFFICIENTS,
        "noise_sd": 0.5,
        "designs": scenario_results,
        "challenge_contrast": {
            "well_conditioned_median_proxy": baseline["median_condition_proxy"],
            "near_collinear_median_proxy": severe["median_condition_proxy"],
            "minimum_near_collinear_wrong_sign_fraction": minimum_severe_sign_error,
            "minimum_near_collinear_to_baseline_interval_width_ratio": minimum_width_ratio,
        },
        "heuristic_decision": {
            "elevated_threshold": 100.0,
            "severe_threshold": 1000.0,
            "well_conditioned_warning_fraction": baseline["heuristic_warning_fraction"],
            "near_collinear_warning_fraction": severe["heuristic_warning_fraction"],
            "interpretation": "descriptive alert thresholds only; not a universal collinearity cutoff, causal diagnostic, or identifiability certificate",
        },
        "product_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "limitations": [
            "predictor designs and Gaussian noise are synthetic and known to the evaluator",
            "factor coefficients remain associational and conditional on the supplied linear model",
            "marginal intervals are not adjusted over factors, model formulas, or post-selection claims",
            "the QR diagonal-ratio proxy is a descriptive conditioning screen rather than an exact matrix condition number",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    baseline = result["designs"]["0.2"]
    severe = result["designs"]["0.003"]
    contrast = result["challenge_contrast"]
    if (result["trials_per_design"] < 100
            or baseline["heuristic_warning_fraction"] != 0.0
            or severe["severe_heuristic_fraction"] != 1.0
            or contrast["minimum_near_collinear_wrong_sign_fraction"] < 0.20
            or contrast["minimum_near_collinear_to_baseline_interval_width_ratio"] < 10.0):
        raise SystemExit("D01 near-collinearity challenge did not meet its frozen diagnostic criteria")
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
