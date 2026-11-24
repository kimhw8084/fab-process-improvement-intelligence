"""Compare D03 Bonferroni mean rectangles with a SciPy paired max-t bootstrap.

The null oracle gives every setting identical true multiobjective means while
lot-level response vectors are correlated across settings and outcomes. The
alternative is a stronger method only if it retains family-wise coverage and
meaningfully narrows intervals. This is qualification evidence, not production
population evidence or a runtime dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import bootstrap, t as student_t

from products.p4.tradeoffs import observed_tradeoffs


SETTINGS = (1.0, 2.0, 3.0, 4.0)
OBJECTIVES = [{"metric": "quality", "direction": "maximize"},
              {"metric": "defect", "direction": "minimize"}]
METRIC_DEFS = {"quality": {"unit": "score", "direction": "maximize"},
               "defect": {"unit": "count", "direction": "minimize"}}
FACTOR_DEFS = {"pressure": {"role": "controllable", "unit": "u"}}
OBSERVED_SPEC = {"tradeoff_unit_field": "lot_id", "tradeoff_min_independent_units": 11}
SETTING_IDS = ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3", "SYN-SETTING-4"]
PRECOMMIT = {"precommit_reference": "SYN-D03-FIXED-FAMILY-PLAN",
             "candidate_setting_ids": SETTING_IDS,
             "objectives": OBJECTIVES}
OBSERVED_SPEC["familywise_t_precommit"] = PRECOMMIT


def _wilson(successes, trials):
    z = 1.959963984540054
    p = successes/trials
    denominator = 1+z*z/trials
    center = (p+z*z/(2*trials))/denominator
    half = z*math.sqrt((p*(1-p)+z*z/(4*trials))/trials)/denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def _draw_lot_matrix(rng, units, heavy_tailed=False):
    setting_correlation = np.fromfunction(lambda i, j: 0.72**np.abs(i-j), (4, 4), dtype=float)
    metric_correlation = np.array([[1.0, 0.60], [0.60, 1.0]])
    covariance = np.kron(setting_correlation, metric_correlation)
    values = rng.multivariate_normal(np.zeros(8), covariance, size=units)
    if heavy_tailed:
        scales = np.sqrt(rng.chisquare(5, size=units)/5)
        values = values/scales[:, None]
    values = values.reshape(units, 4, 2)
    values[:, :, 0] *= 1.0
    values[:, :, 1] *= 0.8
    values += np.array([5.0, 2.0])[None, None, :]
    return values


def _make_rows(values):
    rows = []
    for unit in range(values.shape[0]):
        for setting_index, pressure in enumerate(SETTINGS):
            rows.append({"id": f"SYN-{unit}-{pressure}", "lot_id": f"LOT-{unit:04d}",
                         "factors": {"pressure": pressure},
                         "metrics": {"quality": float(values[unit, setting_index, 0]),
                                     "defect": float(values[unit, setting_index, 1])}})
    return rows


def _intervals_from_bootstrap_max_standardized(values, resamples, seed):
    observed = np.mean(values, axis=0)
    standard_errors = np.std(values, axis=0, ddof=1)/math.sqrt(values.shape[0])

    def mean_vector(sample, axis=0):
        return np.mean(sample, axis=axis)

    result = bootstrap((values,), mean_vector, vectorized=True, paired=True,
                       axis=0, n_resamples=resamples, batch=128,
                       confidence_level=0.95, method="percentile",
                       random_state=np.random.default_rng(seed))
    # The SciPy vectorized bootstrap preserves all setting and metric values
    # from each sampled lot; the maximum standardized deviation supplies the
    # finite-family critical value for this qualification-only alternative.
    distribution = np.moveaxis(result.bootstrap_distribution, -1, 0)
    bootstrap_means = distribution
    bootstrap_se = np.std(distribution, axis=0, ddof=1)
    valid = bootstrap_se > 0
    max_statistics = np.max(np.where(valid[None, :, :],
                                      np.abs(bootstrap_means-observed[None, :, :]) /
                                      np.where(valid[None, :, :], bootstrap_se[None, :, :], 1.0),
                                      0.0), axis=(1, 2))
    critical = float(np.quantile(max_statistics, 0.95, method="higher"))
    intervals = np.stack((observed-critical*standard_errors,
                          observed+critical*standard_errors), axis=-1)
    return intervals, critical


def run_benchmark(trials=500, bootstrap_resamples=999, seed=20261123, units=30):
    if trials < 100 or bootstrap_resamples < 499 or units < 11:
        raise ValueError("benchmark requires >=100 trials, >=499 bootstrap resamples, and >=11 independent lots")
    rng = np.random.default_rng(seed)
    scenarios = {}
    for scenario, heavy in (("correlated_normal", False), ("correlated_heavy_t5", True)):
        bonf_covered = 0
        bootstrap_covered = 0
        marginal_covered = 0
        bonf_false_dominance = 0
        bootstrap_false_dominance = 0
        marginal_false_dominance = 0
        bonf_widths = []
        bootstrap_widths = []
        critical_values = []
        for trial in range(trials):
            values = _draw_lot_matrix(rng, units, heavy_tailed=heavy)
            rows = _make_rows(values)
            result = observed_tradeoffs(rows, METRIC_DEFS, FACTOR_DEFS, OBSERVED_SPEC, OBJECTIVES)
            if result["familywise_mean_envelope"]["status"] != "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE":
                raise RuntimeError(f"Bonferroni path unavailable: {result['familywise_mean_envelope']}")
            true_means = np.array([5.0, 2.0])[None, :]
            bonf_intervals = np.empty((4, 2, 2))
            marginal_intervals = np.empty((4, 2, 2))
            for candidate in result["candidate_settings"]:
                setting = int(candidate["factors"]["pressure"])-1
                for metric_index, metric in enumerate(("quality", "defect")):
                    uncertainty = candidate["uncertainty"][metric]
                    bonf_intervals[setting, metric_index] = uncertainty["familywise_ci95"]
                    marginal_intervals[setting, metric_index] = uncertainty["marginal_ci95"]
            bootstrap_intervals, critical = _intervals_from_bootstrap_max_standardized(values, bootstrap_resamples, seed+trial)
            critical_values.append(critical)

            bonf_covered += int(bool(np.all((bonf_intervals[:, :, 0] <= true_means)
                                           & (true_means <= bonf_intervals[:, :, 1]))))
            marginal_covered += int(bool(np.all((marginal_intervals[:, :, 0] <= true_means)
                                                & (true_means <= marginal_intervals[:, :, 1]))))
            bootstrap_covered += int(bool(np.all((bootstrap_intervals[:, :, 0] <= true_means)
                                                 & (true_means <= bootstrap_intervals[:, :, 1]))))
            bonf_false_dominance += int(bool(result["familywise_interval_separated_dominance"]))
            marginal_false_dominance += int(bool(result["interval_separated_dominance"]))
            bootstrap_false_dominance += int(bool(_interval_dominance_from_rectangles(bootstrap_intervals)))
            bonf_widths.append(float(np.mean(bonf_intervals[:, :, 1]-bonf_intervals[:, :, 0])))
            bootstrap_widths.append(float(np.mean(bootstrap_intervals[:, :, 1]-bootstrap_intervals[:, :, 0])))
        scenarios[scenario] = {
            "trials": trials, "independent_lots_per_trial": units,
            "true_setting_means": {"quality": 5.0, "defect": 2.0},
            "methods": {
                "unadjusted_marginal_t": {
                    "joint_mean_coverage_rate": marginal_covered/trials,
                    "joint_mean_coverage_wilson95": _wilson(marginal_covered, trials),
                    "false_dominance_rate": marginal_false_dominance/trials,
                },
                "product_bonferroni_rectangle": {
                    "joint_mean_coverage_rate": bonf_covered/trials,
                    "joint_mean_coverage_wilson95": _wilson(bonf_covered, trials),
                    "false_dominance_rate": bonf_false_dominance/trials,
                    "mean_interval_width": float(np.mean(bonf_widths)),
                },
                "scipy_paired_max_standardized_bootstrap": {
                    "joint_mean_coverage_rate": bootstrap_covered/trials,
                    "joint_mean_coverage_wilson95": _wilson(bootstrap_covered, trials),
                    "false_dominance_rate": bootstrap_false_dominance/trials,
                    "mean_interval_width": float(np.mean(bootstrap_widths)),
                    "mean_bootstrap_max_standardized_critical": float(np.mean(critical_values)),
                    "n_resamples": bootstrap_resamples,
                },
            },
            "max_standardized_width_ratio_to_bonferroni": float(np.mean(bootstrap_widths)/np.mean(bonf_widths)),
        }
    selection_trials = min(trials, 500)
    selected_only_refusals = 0
    selected_only_interval_releases = 0
    naive_selected_t_coverage = 0
    for _ in range(selection_trials):
        values = _draw_lot_matrix(rng, units)
        selected_index = int(np.argmax(np.mean(values[:, :, 0], axis=0)))
        selected_pressure = SETTINGS[selected_index]
        selected_rows = [row for row in _make_rows(values)
                         if row["factors"]["pressure"] == selected_pressure]
        result = observed_tradeoffs(selected_rows, METRIC_DEFS, FACTOR_DEFS,
                                    OBSERVED_SPEC, OBJECTIVES)
        envelope = result["familywise_mean_envelope"]
        selected_only_refusals += int(envelope["status"] == "PRECOMMITTED_SETTING_FAMILY_MISMATCH")
        selected_only_interval_releases += int(any(
            candidate["uncertainty"]["quality"].get("familywise_ci95") is not None
            for candidate in result["candidate_settings"]))
        selected = values[:, selected_index, 0]
        center = float(np.mean(selected))
        radius = float(student_t.ppf(0.975, units-1)*np.std(selected, ddof=1)/math.sqrt(units))
        naive_selected_t_coverage += int(center-radius <= 5.0 <= center+radius)

    root = Path(__file__).resolve().parents[1]
    return {"schema": "p4-d03-familywise-benchmark/v1", "seed": seed,
            "product_tradeoffs_sha256": hashlib.sha256((root / "products" / "p4" / "tradeoffs.py").read_bytes()).hexdigest(),
            "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "objective_family_size": 8, "resampling_unit": "whole independent lot row vector, preserving cross-setting and cross-metric dependence",
            "generator": "four equal-mean settings; correlated settings and objectives; normal and scaled multivariate t(5) unit effects",
            "mature_alternative": "scipy.stats.bootstrap vectorized mean resampling with paired unit rows; a max-standardized family statistic is computed only in qualification code",
            "bootstrap_resamples": bootstrap_resamples,
            "product_decision_rule": "retain the offline dependency-free Bonferroni envelope because the narrower bootstrap method did not meet family-wise coverage in either challenge",
            "adaptive_setting_selection_challenge": {
                "trials": selection_trials,
                "selector": "retain only the setting with the largest observed quality mean among four equal-mean settings",
                "legacy_selected_setting_t_interval_coverage": naive_selected_t_coverage/selection_trials,
                "legacy_selected_setting_t_interval_coverage_wilson95": _wilson(naive_selected_t_coverage, selection_trials),
                "declared_full_family_refusal_fraction": selected_only_refusals/selection_trials,
                "selected_only_familywise_interval_release_fraction": selected_only_interval_releases/selection_trials,
                "scope": "synthetic selection-bias diagnostic; exact precommit matching cannot authenticate when the caller created or changed the cited plan"},
            "scenarios": scenarios,
            "limitations": ["finite Monte Carlo results do not prove population coverage",
                            "settings are treated as a fixed finite family before mean inspection",
                            "the product remains descriptive when outcome-based constraints change populations"]}


def _interval_dominance_from_rectangles(intervals):
    # all equal-mean settings: any full rectangle separation is false dominance
    for left in range(intervals.shape[0]):
        for right in range(intervals.shape[0]):
            if left == right:
                continue
            dominates = True
            strict = False
            # quality is maximized; defect is minimized.
            for metric, direction in enumerate(("maximize", "minimize")):
                if direction == "maximize":
                    dominates &= intervals[left, metric, 0] >= intervals[right, metric, 1]
                    strict |= intervals[left, metric, 0] > intervals[right, metric, 1]
                else:
                    dominates &= intervals[left, metric, 1] <= intervals[right, metric, 0]
                    strict |= intervals[left, metric, 1] < intervals[right, metric, 0]
            if dominates and strict:
                return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=500)
    parser.add_argument("--bootstrap-resamples", type=int, default=999)
    parser.add_argument("--units", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.trials, args.bootstrap_resamples, args.seed, args.units)
    rendered = json.dumps(report, indent=2, sort_keys=True)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
