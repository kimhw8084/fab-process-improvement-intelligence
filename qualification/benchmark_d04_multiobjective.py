"""Compare one-step multiobjective experiment selection on fixed synthetic oracles.

BoTorch qLogNEHVI is benchmark-only. This challenge compares its one-run
expected-hypervolume proposal with the current P4 target-plus-constraint path,
the new objective-specific P4 alternative slate, and deterministic maximin.
It measures latent one-step hypervolume gain, not engineering ROI or a
production guarantee. A best-of-slate oracle score is only an unattainable
upper bound unless the engineer already knows the generating surface.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import statistics
import sys
from time import perf_counter
from pathlib import Path

import torch
from botorch import fit_gpytorch_mll
from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
from botorch.models.gp_regression import SingleTaskGP
from botorch.models.model_list_gp_regression import ModelListGP
from botorch.models.transforms.outcome import Standardize
from botorch.sampling.normal import SobolQMCNormalSampler
from gpytorch.mlls.sum_marginal_log_likelihood import SumMarginalLogLikelihood

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from products.p4.design import propose_design, propose_multiobjective_next_best


BOUNDS = {"pressure": [0.0, 1.0], "power": [0.0, 1.0]}
LEVELS = (0.0, 0.25, 1.0)
INITIAL_SETTINGS = [(x, y) for x in LEVELS for y in LEVELS]
CANDIDATE_GRID = [(i / 20.0, j / 20.0) for i in range(21) for j in range(21)]
REF_POINT = (0.2, 0.2)
NOISE_SD = (0.025, 0.025)
REPLICATES_PER_SETTING = 12


def _surface(family: str, pressure: float, power: float) -> tuple[float, float]:
    quality = 0.96 - 0.68 * ((pressure - 0.18) ** 2 + (power - 0.78) ** 2)
    yield_index = 0.96 - 0.68 * ((pressure - 0.82) ** 2 + (power - 0.22) ** 2)
    if family == "hidden_alias":
        # Exactly zero on every point of the measured 3x3 starting grid; the effect is
        # intentionally unidentifiable from those observations.
        hidden = math.sin(4.0 * math.pi * pressure) * math.sin(4.0 * math.pi * power)
        quality += 0.16 * hidden
        yield_index -= 0.12 * hidden
    return quality, yield_index


def _draw_initial(seed: int, family: str):
    rng = random.Random(seed)
    rows = []
    for setting_index, (pressure, power) in enumerate(INITIAL_SETTINGS):
        quality, yield_index = _surface(family, pressure, power)
        for replicate in range(REPLICATES_PER_SETTING):
            unit = f"LOT-{setting_index:02d}-{replicate:02d}"
            rows.append({"id": unit, "lot_id": unit,
                         "factors": {"pressure": pressure, "power": power},
                         "metrics": {"quality": quality + rng.gauss(0.0, NOISE_SD[0]),
                                     "defect": 1.0 - yield_index + rng.gauss(0.0, NOISE_SD[1])}})
    return rows


def _hypervolume(points):
    points = [(max(REF_POINT[0], x), max(REF_POINT[1], y)) for x, y in points
              if x > REF_POINT[0] and y > REF_POINT[1]]
    if not points:
        return 0.0
    xs = sorted({x for x, _ in points})
    area = 0.0
    previous = REF_POINT[0]
    for x in xs:
        height = max(y for px, y in points if px >= x)
        area += (x - previous) * (height - REF_POINT[1])
        previous = x
    return area


def _hv_gain(family, point):
    initial = [_surface(family, *setting) for setting in INITIAL_SETTINGS]
    before = _hypervolume(initial)
    after = _hypervolume(initial + [_surface(family, *point)])
    return max(0.0, after - before)


def _wilson95(successes, trials):
    if not trials:
        return None
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z*z/trials
    center = (proportion + z*z/(2*trials)) / denominator
    half = z * math.sqrt(proportion*(1-proportion)/trials + z*z/(4*trials*trials)) / denominator
    return [center-half, center+half]


def _botorch_candidate(rows, seed):
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    dtype = torch.double
    x_by_setting = {}
    y_by_setting = {}
    for row in rows:
        setting = (row["factors"]["pressure"], row["factors"]["power"])
        y_by_setting.setdefault(setting, [[], []])
        y_by_setting[setting][0].append(row["metrics"]["quality"])
        y_by_setting[setting][1].append(1.0 - row["metrics"]["defect"])
    x = torch.tensor(list(INITIAL_SETTINGS), dtype=dtype)
    y = torch.tensor([[statistics.mean(y_by_setting[setting][objective]) for objective in range(2)]
                      for setting in INITIAL_SETTINGS], dtype=dtype)
    yvar = torch.tensor([[NOISE_SD[objective] ** 2 / REPLICATES_PER_SETTING for objective in range(2)]
                         for _ in INITIAL_SETTINGS], dtype=dtype)
    models = [SingleTaskGP(x, y[:, index:index + 1], yvar[:, index:index + 1],
                           outcome_transform=Standardize(m=1)) for index in range(2)]
    model = ModelListGP(*models)
    mll = SumMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll, options={"maxiter": 75})
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)
    acquisition = qLogNoisyExpectedHypervolumeImprovement(
        model=model, ref_point=list(REF_POINT), X_baseline=x,
        sampler=sampler, prune_baseline=True)
    candidates = [point for point in CANDIDATE_GRID if point not in INITIAL_SETTINGS]
    x_cand = torch.tensor(candidates, dtype=dtype).unsqueeze(1)
    with torch.no_grad():
        scores = acquisition(x_cand).reshape(-1)
    if not torch.isfinite(scores).any():
        raise RuntimeError("BoTorch qLogNEHVI returned no finite candidate scores")
    return candidates[int(torch.nan_to_num(scores, nan=-math.inf).argmax().item())]


def _p4_candidate(rows, seed):
    spec = {"run_budget": 1, "seed": seed, "blocks": 1,
            "target_metric": "quality", "candidate_levels": 21,
            "independent_unit_field": "lot_id", "min_independent_units": 6,
            "validation_min_training_groups": 20, "validation_fraction": 0.2,
            "maximum_grouped_validation_rmse": 0.12,
            "constraint_metrics": ["defect"],
            "maximum_grouped_validation_rmse_by_metric": {"defect": 0.12}}
    metrics = {"quality": {"direction": "maximize", "unit": "normalized-index"},
               "defect": {"direction": "minimize", "unit": "normalized-rate", "max": 0.62}}
    model = {"covariance": "cluster", "cluster_field": "lot_id",
             "minimum_clusters": 30, "quadratic": True, "interactions": True}
    proposal = propose_design("next_best", ["pressure", "power"], BOUNDS, spec, [],
                              rows, metrics, model)
    run = proposal["runs"][0]
    return (float(run["pressure"]), float(run["power"]))


def _p4_slate_options(rows, seed):
    spec = {"run_budget": 1, "blocks": 1, "seed": seed, "validation_seed": seed,
            "candidate_levels": 21, "independent_unit_field": "lot_id", "min_independent_units": 6,
            "validation_min_training_groups": 20, "validation_fraction": 0.2,
            "maximum_grouped_validation_rmse": 0.12}
    model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
             "quadratic": True, "interactions": True}
    plan = propose_multiobjective_next_best(
        ["pressure", "power"], BOUNDS, spec, [], rows,
        [{"metric": "quality", "direction": "maximize"},
         {"metric": "defect", "direction": "minimize"}],
        {"quality": {"direction": "maximize", "unit": "normalized-index"},
         "defect": {"direction": "minimize", "unit": "normalized-rate", "max": 0.62}}, model)
    return plan["run_options"]


def _maximin_candidate():
    return max((point for point in CANDIDATE_GRID if point not in INITIAL_SETTINGS),
               key=lambda point: (min(math.dist(point, existing) for existing in INITIAL_SETTINGS),
                                  -point[0], -point[1]))


def run_benchmark(trials: int = 30, seed: int = 20261124):
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 10:
        raise ValueError("at least 10 trials are required")
    outcomes = {family: {name: [] for name in ("botorch_qlognehvi", "p4_target_constraint", "maximin")}
                for family in ("smooth_tradeoff", "hidden_alias")}
    slate_outcomes = {family: [] for family in outcomes}
    p4_refusals = {family: {} for family in outcomes}
    for family in outcomes:
        for trial in range(trials):
            trial_seed = seed + trial
            rows = _draw_initial(trial_seed, family)
            elapsed = {}
            started = perf_counter()
            candidates = {"botorch_qlognehvi": _botorch_candidate(rows, trial_seed)}
            elapsed["botorch_qlognehvi"] = perf_counter() - started
            started = perf_counter()
            candidates["maximin"] = _maximin_candidate()
            elapsed["maximin"] = perf_counter() - started
            started = perf_counter()
            try:
                candidates["p4_target_constraint"] = _p4_candidate(rows, trial_seed)
            except ValueError as exc:
                p4_refusals[family][str(exc)] = p4_refusals[family].get(str(exc), 0) + 1
            elapsed["p4_target_constraint"] = perf_counter() - started
            for method, point in candidates.items():
                outcomes[family][method].append({"seed": trial_seed, "setting": list(point),
                                                  "latent_hypervolume_gain": _hv_gain(family, point),
                                                  "selection_seconds": elapsed[method]})
            started = perf_counter()
            options = _p4_slate_options(rows, trial_seed)
            slate_seconds = perf_counter() - started
            slate_outcomes[family].append({
                "seed": trial_seed,
                "selection_seconds": slate_seconds,
                "options": [{"objective_metric": option["objective_metric"],
                             "direction": option["objective_direction"],
                             "setting": [option["settings"]["pressure"], option["settings"]["power"]],
                             "expected_improvement": option["expected_improvement"],
                             "latent_hypervolume_gain": _hv_gain(
                                 family, (option["settings"]["pressure"], option["settings"]["power"]))}
                            for option in options],
            })

    summaries = {}
    for family, methods in outcomes.items():
        summaries[family] = {}
        for method, items in methods.items():
            gains = [item["latent_hypervolume_gain"] for item in items]
            durations = sorted(item["selection_seconds"] for item in items)
            summaries[family][method] = {
                "accepted_trials": len(items),
                "acceptance_fraction": len(items) / trials,
                "mean_latent_hypervolume_gain": statistics.mean(gains) if gains else None,
                "median_latent_hypervolume_gain": statistics.median(gains) if gains else None,
                "p95_latent_hypervolume_gain": sorted(gains)[math.ceil(0.95 * len(gains)) - 1] if gains else None,
                "median_selection_seconds": statistics.median(durations) if durations else None,
                "p95_selection_seconds": durations[math.ceil(0.95 * len(durations)) - 1] if durations else None,
                "candidate_settings": [item["setting"] for item in items],
            }
    paired = {}
    for family, methods in outcomes.items():
        for baseline in ("p4_target_constraint", "maximin"):
            left = {item["seed"]: item["latent_hypervolume_gain"]
                    for item in methods["botorch_qlognehvi"]}
            right = {item["seed"]: item["latent_hypervolume_gain"]
                     for item in methods[baseline]}
            common = sorted(set(left) & set(right))
            wins = sum(left[trial_seed] > right[trial_seed] for trial_seed in common)
            paired[family + "_vs_" + baseline] = {
                "paired_seed_count": len(common),
                "botorch_higher_gain_count": wins,
                "botorch_higher_gain_fraction": wins / len(common) if common else None,
                "botorch_higher_gain_wilson95": _wilson95(wins, len(common)),
            }
    slate_summaries = {}
    for family, trials_data in slate_outcomes.items():
        per_objective = {}
        objective_names = sorted({option["objective_metric"] for trial in trials_data
                                  for option in trial["options"]})
        for objective in objective_names:
            options = [option for trial in trials_data for option in trial["options"]
                       if option["objective_metric"] == objective]
            gains = [option["latent_hypervolume_gain"] for option in options]
            per_objective[objective] = {
                "option_count": len(options),
                "mean_latent_hypervolume_gain": statistics.mean(gains) if gains else None,
                "candidate_settings": [option["setting"] for option in options],
            }
        oracle_best = [max(option["latent_hypervolume_gain"] for option in trial["options"])
                       for trial in trials_data]
        seconds = sorted(trial["selection_seconds"] for trial in trials_data)
        slate_summaries[family] = {
            "accepted_trials": len(trials_data),
            "alternatives_per_trial": len(trials_data[0]["options"]) if trials_data else 0,
            "mean_oracle_best_option_hv_upper_bound": statistics.mean(oracle_best) if oracle_best else None,
            "median_selection_seconds": statistics.median(seconds) if seconds else None,
            "p95_selection_seconds": seconds[math.ceil(0.95 * len(seconds)) - 1] if seconds else None,
            "by_objective": per_objective,
            "trial_options": trials_data,
        }
        for baseline in ("botorch_qlognehvi", "p4_target_constraint", "maximin"):
            baseline_by_seed = {item["seed"]: item["latent_hypervolume_gain"]
                                for item in outcomes[family][baseline]}
            slate_by_seed = {trial["seed"]: max(option["latent_hypervolume_gain"] for option in trial["options"])
                             for trial in trials_data}
            common = sorted(set(baseline_by_seed) & set(slate_by_seed))
            wins = sum(slate_by_seed[trial_seed] > baseline_by_seed[trial_seed]
                       for trial_seed in common)
            paired[family + "_slate_oracle_upper_bound_vs_" + baseline] = {
                "paired_seed_count": len(common),
                "oracle_best_slate_option_higher_gain_count": wins,
                "oracle_best_slate_option_higher_gain_fraction": wins / len(common) if common else None,
                "oracle_best_slate_option_higher_gain_wilson95": _wilson95(wins, len(common)),
            }
    return {
        "schema": "p4-d04-multiobjective-method-benchmark/v1",
        "seed": seed,
        "trials_per_surface": trials,
        "surface_families": list(outcomes),
        "initial_design": {"levels": list(LEVELS), "independent_lots_per_setting": REPLICATES_PER_SETTING},
        "methods": {
            "botorch_qlognehvi": {"package": "botorch", "version": importlib.metadata.version("botorch"),
                                  "acquisition": "qLogNoisyExpectedHypervolumeImprovement; 128 Sobol MC samples; finite 21x21 candidate grid",
                                  "known_noise_variance_supplied": True},
            "p4_objective_specific_slate": {"method": "one independently grouped-validated single-objective expected-improvement option per objective; no joint covariance or scalar preference",
                                             "runtime_dependency_added": False},
            "p4_target_constraint": {"method": "current P4 grouped-holdout quadratic one-step EI with quality target and defect bound"},
            "maximin": {"method": "deterministic maximin distance to the initial design on the same candidate grid"},
        },
        "objective": "single proposed run's exact latent two-objective hypervolume gain against the initial finite design; maximize quality and yield index; fixed reference point [0.2,0.2]",
        "results": summaries,
        "p4_objective_specific_slate": slate_summaries,
        "p4_refusals": p4_refusals,
        "paired_comparisons": paired,
        "limitations": [
            "two synthetic objective surfaces do not represent fab outcomes or operational cost",
            "the hidden_alias surface is exactly unidentifiable on the initial 3x3 design; no method can infer its unobserved term from those rows",
            "BoTorch receives the generator's known replicate noise variance, which is extra information unavailable to P4",
            "the P4 slate contains one option per objective and does not estimate competing outcomes at each setting; oracle-best slate hypervolume is an unattainable evaluation upper bound, not the product's decision rule",
            "one-step latent hypervolume gain is not a posterior guarantee, production safety claim, or engineer ROI",
            "BoTorch is benchmark-only; no runtime dependency or product selection change is implied",
        ],
        "environment": {"python": __import__("platform").python_version(), "torch": torch.__version__,
                        "numpy": importlib.metadata.version("numpy"), "scipy": importlib.metadata.version("scipy"),
                        "gpytorch": importlib.metadata.version("gpytorch"),
                        "linear_operator": importlib.metadata.version("linear_operator")},
        "product_source_sha256": {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                                  for relative in ("products/p4/design.py", "products/p4/regression.py")},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "qualification": "EVALUATION_ONLY",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "qualification/results/D04_MULTIOBJECTIVE_METHOD_BENCHMARK.json")
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    result["benchmark_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
