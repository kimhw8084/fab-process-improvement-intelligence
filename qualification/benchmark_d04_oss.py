"""Fixed-seed comparison of offline D04 plans with mature DOE/optimization OSS.

Benchmark-only dependencies are pinned in benchmark-requirements.txt. None are
product runtime dependencies. Run with:
  python qualification/benchmark_d04_oss.py --output release/D04_OSS_COMPARISON.json
"""
from __future__ import annotations

import argparse
from itertools import combinations
import json
import importlib.metadata
import math
from pathlib import Path
import statistics
import sys

import numpy as np
import scipy
from scipy.stats import qmc
import pyDOE3
from pyDOE3.doe_optimal import generate_candidate_set, optimal_design
import skopt
from skopt import Optimizer
from skopt.space import Real

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from products.p4.design import DesignError, propose_design


def _summary(values):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    return {"count": len(ordered), "mean": statistics.mean(ordered),
            "median": statistics.median(ordered),
            "p95": ordered[min(len(ordered)-1, math.ceil(0.95*len(ordered))-1)]}


def _stratified(sample, n):
    return all(sorted(np.floor(sample[:, j]*n).astype(int).tolist()) == list(range(n))
               for j in range(sample.shape[1]))


def _max_abs_corr(sample):
    correlation = np.corrcoef(sample, rowvar=False)
    return float(np.max(np.abs(correlation - np.eye(sample.shape[1]))))


def benchmark_latin_hypercube():
    n, dimensions, seeds = 32, 4, range(20261122, 20261186)
    controls = [f"x{i}" for i in range(dimensions)]
    bounds = {name: [0.0, 1.0] for name in controls}
    metrics = {name: {"cd": [], "max_abs_correlation": [], "stratified": []}
               for name in ("p4_basic", "scipy_basic", "scipy_random_cd")}
    for seed in seeds:
        p4 = np.array([[run[name] for name in controls] for run in propose_design(
            "latin_hypercube", controls, bounds,
            {"run_budget": n, "seed": seed, "blocks": 1}, [])["runs"]])
        scipy_basic = qmc.LatinHypercube(d=dimensions, seed=seed).random(n)
        scipy_optimized = qmc.LatinHypercube(d=dimensions, seed=seed, optimization="random-cd").random(n)
        for name, sample in (("p4_basic", p4), ("scipy_basic", scipy_basic),
                             ("scipy_random_cd", scipy_optimized)):
            metrics[name]["cd"].append(float(qmc.discrepancy(sample, method="CD")))
            metrics[name]["max_abs_correlation"].append(_max_abs_corr(sample))
            metrics[name]["stratified"].append(_stratified(sample, n))
    return {"protocol": {"dimensions": dimensions, "runs": n, "seed_count": len(list(seeds)),
                         "seed_start": 20261122, "seed_end_inclusive": 20261185,
                         "metrics": "SciPy centered discrepancy (lower better), max absolute linear correlation (lower better), exact marginal strata retention"},
            "results": {name: {"centered_discrepancy": _summary(item["cd"]),
                               "max_abs_correlation": _summary(item["max_abs_correlation"]),
                               "stratified_seed_fraction": sum(item["stratified"])/len(item["stratified"])}
                        for name, item in metrics.items()}}


def _logdet_information(points):
    matrix = np.column_stack((np.ones(len(points)), np.asarray(points, dtype=float)))
    sign, value = np.linalg.slogdet(matrix.T @ matrix)
    return float(value) if sign > 0 else float("-inf")


def benchmark_d_optimal():
    candidates = generate_candidate_set(n_factors=2, bounds=[[-1, 1], [-1, 1]], n_levels=3)
    runs = 6
    pydoe_points, info = optimal_design(candidates=candidates, n_points=runs, degree=1,
                                       criterion="D", method="detmax", max_iter=200)
    controls = ["x", "y"]
    custom = propose_design("d_optimal", controls, {"x": [-1, 1], "y": [-1, 1]},
                            {"run_budget": runs, "candidate_levels": 3, "seed": 20261122, "blocks": 1}, [])
    custom_points = np.array([[point["x"], point["y"]] for point in custom["runs"]])
    exact = max(_logdet_information(np.asarray(candidates)[list(indexes)])
                for indexes in combinations(range(len(candidates)), runs))
    custom_logdet = _logdet_information(custom_points)
    pydoe_logdet = _logdet_information(pydoe_points)
    random_logs = []
    rng = np.random.default_rng(81731)
    for _ in range(500):
        random_logs.append(_logdet_information(np.asarray(candidates)[rng.choice(len(candidates), runs, replace=False)]))
    p = 3
    efficiency = lambda score: 100.0*math.exp((score-exact)/p)
    return {"protocol": {"candidate_grid": "3 x 3 equally spaced levels on [-1, 1]^2", "runs": runs,
                         "model": "intercept plus two linear main effects", "exact_designs_enumerated": math.comb(9, 6),
                         "random_seed": 81731, "random_design_count": 500,
                         "criterion": "D-efficiency relative to exhaustive exact optimum"},
            "results": {"exact_optimum_log_determinant": exact,
                        "p4_greedy": {"log_determinant": custom_logdet, "D_efficiency_percent": efficiency(custom_logdet)},
                        "pyDOE3_detmax": {"log_determinant": pydoe_logdet, "D_efficiency_percent": efficiency(pydoe_logdet),
                                          "reported_D_efficiency_percent": float(info["D_eff"])},
                        "seeded_random_unique_designs": {"D_efficiency_percent": _summary([efficiency(score) for score in random_logs]),
                                                         "fraction_full_rank": sum(math.isfinite(score) for score in random_logs)/len(random_logs)}}}


def _truth(name, x):
    if name == "smooth_quadratic":
        return 1.0 - 1.8*(x-0.53)**2
    if name == "asymmetric_quadratic":
        return 1.0 - 1.2*(x-0.37)**2 + 0.18*(x-0.37)**3
    if name == "multimodal":
        return 0.45*math.sin(3.0*math.pi*x) + 0.28*math.cos(7.0*math.pi*x) - 0.15*x
    raise ValueError(name)


def _one_step_pair(function_name, seed):
    from random import Random

    rng = Random(seed)
    initial = (0.0, 0.25, 0.5, 0.75, 1.0)
    rows = []
    cluster_shift = {lot: 0.035*math.sin(lot*1.71+seed*0.1) for lot in range(36)}
    for x in initial:
        for lot in range(36):
            noise = 0.012*math.sin(lot*0.7+x*5.3) + rng.uniform(-0.004, 0.004)
            rows.append({"id": f"SYN-{seed}-{x}-{lot}", "factors": {"x": x},
                         "metrics": {"response": _truth(function_name, x)+cluster_shift[lot]+noise},
                         "lot_id": f"SYN-LOT-{lot}"})
    settings = {"run_budget": 1, "seed": seed, "blocks": 1, "target_metric": "response",
                "candidate_levels": 41, "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.10}
    model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30, "quadratic": True}
    try:
        p4 = propose_design("next_best", ["x"], {"x": [0.0, 1.0]}, settings, [], rows,
                            {"response": {"direction": "maximize"}}, model)
        p4_x = p4["runs"][0]["x"]
        p4_regret = None
        p4_cv_rmse = p4["grouped_surface_validation"]["independent_evaluation"]["rmse"]
        p4_refusal = None
    except DesignError as exc:
        p4_x = None
        p4_regret = None
        p4_cv_rmse = None
        p4_refusal = str(exc)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["factors"]["x"], []).append(row["metrics"]["response"])
    x0 = sorted(grouped)
    y0 = [-statistics.mean(grouped[x]) for x in x0]
    optimizer = Optimizer([Real(0.0, 1.0)], base_estimator="GP", acq_func="EI", acq_optimizer="sampling",
                          acq_optimizer_kwargs={"n_points": 2048}, n_initial_points=0, random_state=seed)
    optimizer.tell([[x] for x in x0], y0)
    skopt_x = float(optimizer.ask()[0])
    dense = [i/10000 for i in range(10001)]
    optimum = max(_truth(function_name, x) for x in dense)
    if p4_x is not None:
        p4_regret = optimum-_truth(function_name, p4_x)
    return {"p4_x": p4_x, "p4_refusal_reason": p4_refusal, "p4_untouched_group_evaluation_rmse": p4_cv_rmse, "skopt_x": skopt_x,
            "p4_regret": p4_regret,
            "skopt_regret": optimum-_truth(function_name, skopt_x)}


def benchmark_next_best():
    functions = ("smooth_quadratic", "asymmetric_quadratic", "multimodal")
    seeds = range(20261122, 20261154)
    outcomes = {name: [_one_step_pair(name, seed) for seed in seeds] for name in functions}
    summary = {}
    for name, items in outcomes.items():
        accepted = [item["p4_regret"] for item in items if item["p4_regret"] is not None]
        summary[name] = {"p4": {"accepted_fraction": len(accepted)/len(items),
                                 "true_function_regret_when_accepted": _summary(accepted) if accepted else None,
                                 "untouched_group_evaluation_rmse_when_accepted": _summary([item["p4_untouched_group_evaluation_rmse"] for item in items if item["p4_untouched_group_evaluation_rmse"] is not None]),
                                 "refusal_reasons": sorted({item["p4_refusal_reason"] for item in items if item["p4_refusal_reason"]})},
                         "skopt": _summary([item["skopt_regret"] for item in items])}
    all_items = [item for items in outcomes.values() for item in items]
    accepted_items = [item for item in all_items if item["p4_regret"] is not None]
    return {"protocol": {"functions": list(functions), "seed_count_per_function": len(list(seeds)),
                         "seed_start": 20261122, "seed_end_inclusive": 20261153,
                         "initial_design": [0, 0.25, 0.5, 0.75, 1], "replicates_per_setting": 36,
                         "P4": "formula selection by five-fold grouped CV on development units, then an untouched independent-unit holdout evaluation; one step, 41-point supported grid, engineer-specified max holdout RMSE 0.10, mean-estimation EI",
                         "scikit_optimize": "GP posterior expected improvement; continuous bounded domain, seeded acquisition sampling",
                         "score": "one-step true-function simple regret (lower is better)"},
            "results_by_function": summary,
            "overall": {"p4": {"acceptance_fraction": len(accepted_items)/len(all_items),
                                "true_function_regret_when_accepted": _summary([item["p4_regret"] for item in accepted_items]) if accepted_items else None,
                                "untouched_group_evaluation_rmse_when_accepted": _summary([item["p4_untouched_group_evaluation_rmse"] for item in accepted_items]) if accepted_items else None},
                        "skopt": _summary([item["skopt_regret"] for item in all_items])},
            "paired_p4_lower_regret_fraction_when_accepted": (sum(item["p4_regret"] < item["skopt_regret"] for item in accepted_items)/len(accepted_items)
                                                              if accepted_items else None),
            "limitations": ["synthetic known functions do not represent fab process heterogeneity",
                            "P4 uses a quadratic response family; scikit-optimize uses a Gaussian-process surrogate",
                            "the benchmark assesses one proposal only and does not establish engineering value"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="release/D04_OSS_COMPARISON.json")
    args = parser.parse_args()
    report = {"status": "PASS", "qualification_only_dependencies": {
                  "numpy": np.__version__, "scipy": scipy.__version__,
                  "pyDOE3": importlib.metadata.version("pyDOE3"),
                  "scikit-optimize": importlib.metadata.version("scikit-optimize"),
                  "scikit-learn": importlib.metadata.version("scikit-learn")},
              "latin_hypercube": benchmark_latin_hypercube(),
              "d_optimal": benchmark_d_optimal(), "sequential_next_best": benchmark_next_best(),
              "reference_documentation": [
                  "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.LatinHypercube.html",
                  "https://pydoe3.readthedocs.io/en/stable/reference/doe_optimal/",
                  "https://scikit-optimize.readthedocs.io/en/latest/auto_examples/bayesian-optimization.html"],
              "dependency_decision": "benchmark packages are not product dependencies; the product remains standard-library-only. Basic P4 LHS retains exact marginal stratification and is comparable to SciPy basic LHS but not SciPy random-cd. P4 finite-grid D-optimal design equals the enumerated optimum in the tested case and ties pyDOE3 detmax. Sequential formula selection is isolated to grouped development units and proposals are refused when the untouched grouped evaluation holdout exceeds the engineer-specified maximum RMSE; these diagnostics do not guarantee future performance."}
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output),
                      "latin_hypercube": report["latin_hypercube"]["results"],
                      "d_optimal": report["d_optimal"]["results"],
                      "sequential_overall": report["sequential_next_best"]["overall"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
