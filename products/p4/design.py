"""Small, bounded DOE builders; suggestions are never executed."""
from __future__ import annotations

from itertools import combinations, product
from math import erf, exp, isfinite, pi, sqrt
from random import Random

from products.p4.regression import fit_linear_model, _get_field
from products.p4.window import _hull, _inside_polygon


class DesignError(ValueError):
    pass


def assign_blocks(runs, controls, block_count, seed, cancel=None):
    """Balance main-effect factor levels across explicit nuisance blocks."""
    if not runs or not isinstance(block_count, int) or isinstance(block_count, bool) or not 1 <= block_count <= len(runs):
        raise DesignError("blocks must be positive and no greater than the run count")
    rng = Random(seed)
    capacities = [len(runs)//block_count + (1 if i < len(runs) % block_count else 0)
                  for i in range(block_count)]
    level_totals = {name: {} for name in controls}
    for run in runs:
        for name in controls:
            key = repr(run[name])
            level_totals[name][key] = level_totals[name].get(key, 0)+1
    counts = [{name: {level: 0 for level in level_totals[name]} for name in controls}
              for _ in range(block_count)]
    sizes = [0]*block_count
    tie_order = list(range(block_count))
    rng.shuffle(tie_order)
    assignments = []
    for run in runs:
        if cancel and cancel():
            raise InterruptedError("DOE blocking assignment cancelled")
        feasible = [block for block in tie_order if sizes[block] < capacities[block]]
        scores = []
        for block in feasible:
            score = 0.0
            for name in controls:
                level = repr(run[name])
                target = level_totals[name][level]/block_count
                before = counts[block][name][level]-target
                after = counts[block][name][level]+1-target
                score += after*after-before*before
            scores.append((score, block))
        best_score = min(score for score, _ in scores)
        best_blocks = [block for score, block in scores if abs(score-best_score) <= 1e-12]
        block = rng.choice(best_blocks)
        sizes[block] += 1
        assignments.append(block+1)
        for name in controls:
            counts[block][name][repr(run[name])] += 1

    def swap_delta(i, j):
        left, right = assignments[i]-1, assignments[j]-1
        if left == right:
            return 0.0
        delta = 0.0
        for name in controls:
            left_level, right_level = repr(runs[i][name]), repr(runs[j][name])
            if left_level == right_level:
                continue
            for block, add_level, remove_level in ((left, right_level, left_level),
                                                    (right, left_level, right_level)):
                target_add = level_totals[name][add_level]/block_count
                before_add = counts[block][name][add_level]-target_add
                delta += (before_add+1)**2-before_add**2
                target_remove = level_totals[name][remove_level]/block_count
                before_remove = counts[block][name][remove_level]-target_remove
                delta += (before_remove-1)**2-before_remove**2
        return delta

    pair_count = len(runs)*(len(runs)-1)//2
    for _sweep in range(12):
        if cancel and cancel():
            raise InterruptedError("DOE blocking refinement cancelled")
        if pair_count <= 20_000:
            pairs = list(combinations(range(len(runs)), 2))
        else:
            pairs = set()
            for _ in range(20_000):
                left, right = rng.sample(range(len(runs)), 2)
                pairs.add((min(left, right), max(left, right)))
            pairs = list(pairs)
        rng.shuffle(pairs)
        improved = False
        for index, (left_index, right_index) in enumerate(pairs):
            if index % 256 == 0 and cancel and cancel():
                raise InterruptedError("DOE blocking refinement cancelled")
            if swap_delta(left_index, right_index) < -1e-12:
                left, right = assignments[left_index]-1, assignments[right_index]-1
                assignments[left_index], assignments[right_index] = assignments[right_index], assignments[left_index]
                for name in controls:
                    left_level, right_level = repr(runs[left_index][name]), repr(runs[right_index][name])
                    if left_level != right_level:
                        counts[left][name][left_level] -= 1
                        counts[left][name][right_level] += 1
                        counts[right][name][right_level] -= 1
                        counts[right][name][left_level] += 1
                improved = True
        if not improved:
            break
    differences = {name: max((max(block[name][level] for block in counts)
                               - min(block[name][level] for block in counts))
                              for level in level_totals[name]) for name in controls}
    for run, block, order in zip(runs, assignments, range(1, len(runs)+1)):
        run["block"] = block
        run["run_order"] = order
    return {"count": block_count, "assignment": "seeded greedy balancing of each controllable factor level",
            "block_sizes": sizes, "factor_level_count_max_difference": differences,
            "pairwise_refinement": "pair swaps minimize factor-level imbalance while preserving block sizes",
            "analysis_requirement": "record the assigned block and adjust for it as a nuisance effect when the study design requires"}


def _grouped_surface_validation(rows, factor_defs, metric, model_options, unit_field, cancel=None):
    """Compare the requested quadratic response surface with linear terms.

    Entire independent units are held out together. Validation estimates are
    point predictions; no inference is drawn from the fold scores.
    """
    groups = sorted({str(_get_field(row, unit_field)) for row in rows})
    if len(groups) < 10:
        raise DesignError("next_best requires at least 10 independent groups for grouped response validation")
    fold_count = min(5, len(groups))
    folds = [[] for _ in range(fold_count)]
    for index, group in enumerate(groups):
        folds[index % fold_count].append(group)
    quadratic_errors, linear_errors = {}, {}
    for held_out_groups in folds:
        if cancel and cancel():
            raise InterruptedError("sequential DOE validation cancelled")
        held = set(held_out_groups)
        training = [row for row in rows if str(_get_field(row, unit_field)) not in held]
        validation = [row for row in rows if str(_get_field(row, unit_field)) in held]
        quadratic_options = dict(model_options or {})
        quadratic_options["covariance"] = "classical"
        linear_options = dict(quadratic_options)
        linear_options["quadratic"] = False
        quadratic_fit, quadratic_model = fit_linear_model(training, factor_defs, metric, quadratic_options, cancel=cancel)
        linear_fit, linear_model = fit_linear_model(training, factor_defs, metric, linear_options, cancel=cancel)
        if quadratic_model is None or linear_model is None:
            raise DesignError("next_best grouped validation found a non-identifiable quadratic or linear fold")
        fixed_fields = quadratic_fit["model_specification"]["fixed_effect_fields"]
        for row in validation:
            if cancel and cancel():
                raise InterruptedError("sequential DOE validation cancelled")
            fixed_effects = {field: _get_field(row, field) for field in fixed_fields}
            observed = float(row["metrics"][metric])
            group = str(_get_field(row, unit_field))
            quadratic_errors.setdefault(group, []).append((observed-quadratic_model.predict(row["factors"], fixed_effects)["estimate"])**2)
            linear_errors.setdefault(group, []).append((observed-linear_model.predict(row["factors"], fixed_effects)["estimate"])**2)
    quadratic_rmse = sqrt(sum(sum(errors)/len(errors) for errors in quadratic_errors.values())/len(quadratic_errors))
    linear_rmse = sqrt(sum(sum(errors)/len(errors) for errors in linear_errors.values())/len(linear_errors))
    return {"method": "five-fold grouped by independent unit",
            "independent_groups": len(groups), "held_out_group_count": len(quadratic_errors),
            "linear_rmse": linear_rmse, "quadratic_rmse": quadratic_rmse,
            "quadratic_relative_rmse_improvement": (linear_rmse-quadratic_rmse)/max(linear_rmse, 1e-15),
            "qualification": "group-held-out point-prediction comparison; not a guarantee of future process performance"}


def _forbidden(settings, regions):
    for region in regions:
        if not isinstance(region, dict) or not region:
            raise DesignError("forbidden regions must be nonempty factor-to-range maps")
        match = True
        for name, bounds in region.items():
            if name not in settings:
                raise DesignError(f"unknown factor in forbidden region: {name}")
            pair = bounds if isinstance(bounds, (list, tuple)) and len(bounds) == 2 else [bounds, bounds]
            if len(pair) != 2 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not isfinite(v) for v in pair) or pair[0] > pair[1]:
                raise DesignError("forbidden region bounds must be finite and ordered")
            match = match and pair[0] <= settings[name] <= pair[1]
        if match:
            return True
    return False


def _design_vector(settings, controls, bounds):
    return [1.0] + [2*(settings[name]-bounds[name][0])/(bounds[name][1]-bounds[name][0])-1 for name in controls]


def _inverse(matrix):
    n = len(matrix)
    augmented = [list(row)+[1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(augmented[i][col]))
        if abs(augmented[pivot][col]) < 1e-15:
            raise DesignError("D-optimal information matrix became singular")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [value/scale for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            scale = augmented[row][col]
            augmented[row] = [a-scale*b for a, b in zip(augmented[row], augmented[col])]
    return [row[n:] for row in augmented]


def _proposal(strategy, runs, controls, seed, blocks, reason, additional=None, cancel=None):
    rng = Random(seed)
    rng.shuffle(runs)
    blocking = assign_blocks(runs, controls, blocks, seed, cancel=cancel)
    result = {"status": "PROPOSED", "design": strategy, "factors": controls, "run_count": len(runs),
              "runs": runs, "randomization_seed": seed,
              "blocking": blocking,
              "authorization_fields": ["engineer_approval_id", "process_owner_approval_id", "safety_review_id"],
              "executed": False, "actuation": "none"}
    if additional:
        result.update(additional)
    return result


def propose_design(strategy, controls, bounds, spec, forbidden_regions, rows=None, metric_defs=None, model_options=None, cancel=None):
    seed = spec.get("seed", 20261122)
    budget, blocks = spec.get("run_budget"), spec.get("blocks", 1)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise DesignError("seed must be an integer")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise DesignError("run_budget must be a positive integer")
    if not isinstance(blocks, int) or isinstance(blocks, bool) or not 1 <= blocks <= budget:
        raise DesignError("blocks must be a positive integer no greater than run_budget")
    if len(controls) > 10:
        raise DesignError("DOE is limited to 10 controllable factors")
    if strategy == "full_factorial":
        points = list(product(*[(bounds[name][0], bounds[name][1]) for name in controls]))
        runs = [dict(zip(controls, point)) for point in points if not _forbidden(dict(zip(controls, point)), forbidden_regions)]
        replicates = spec.get("replicates", 1)
        if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates < 1:
            raise DesignError("replicates must be a positive integer")
        runs = [dict(run, replicate=replicate+1) for replicate in range(replicates) for run in runs]
        if not runs or len(runs) > budget:
            raise DesignError(f"full factorial requires {len(runs)} runs; budget is {budget}")
        return _proposal("randomized full factorial at approved bounds", runs, controls, seed, blocks, "factorial", cancel=cancel)
    if strategy == "fractional_factorial":
        if len(controls) < 4:
            raise DesignError("a resolution IV or better regular half-fraction requires at least four factors")
        points = []
        excluded = 0
        for basis in product((-1, 1), repeat=len(controls)-1):
            signs = list(basis)+[1]
            signs[-1] = 1
            for sign in basis:
                signs[-1] *= sign
            point = {name: bounds[name][0] if sign < 0 else bounds[name][1] for name, sign in zip(controls, signs)}
            if not _forbidden(point, forbidden_regions):
                points.append(point)
            else:
                excluded += 1
        if excluded:
            raise DesignError("forbidden regions remove runs from the regular fraction; resolution/alias guarantees are not retained")
        if len(points) > budget:
            raise DesignError(f"resolution-IV-or-better half-fraction requires {len(points)} runs; budget is {budget}")
        return _proposal("regular half-fraction factorial", points, controls, seed, blocks,
                         "fractional_factorial", {"fraction": "one-half", "resolution": len(controls),
                         "generator": f"{controls[-1]} = product({', '.join(controls[:-1])})",
                         "alias_note": "main effects are clear of two-factor interactions for resolution IV+; higher-order aliasing remains"}, cancel=cancel)
    if strategy == "latin_hypercube":
        if budget > 10000:
            raise DesignError("Latin hypercube output is bounded to 10000 runs")
        rng = Random(seed)
        samples = {name: [(i+rng.random())/budget for i in range(budget)] for name in controls}
        for name in controls:
            rng.shuffle(samples[name])
        runs = []
        for index in range(budget):
            point = {name: bounds[name][0]+samples[name][index]*(bounds[name][1]-bounds[name][0]) for name in controls}
            if not _forbidden(point, forbidden_regions):
                runs.append(point)
        if len(runs) < budget:
            raise DesignError("forbidden regions removed Latin-hypercube points; no unbalanced replacement is made")
        return _proposal("randomized Latin hypercube", runs, controls, seed, blocks, "latin_hypercube",
                         {"strata_per_factor": budget, "marginal_stratification": "one point in every equal-width stratum"}, cancel=cancel)
    if strategy == "d_optimal":
        levels = spec.get("candidate_levels", 3)
        if not isinstance(levels, int) or isinstance(levels, bool) or not 2 <= levels <= 7:
            raise DesignError("candidate_levels must be an integer from 2 to 7")
        axes = [[bounds[name][0]+i*(bounds[name][1]-bounds[name][0])/(levels-1) for i in range(levels)] for name in controls]
        candidates = [dict(zip(controls, point)) for point in product(*axes)]
        candidates = [point for point in candidates if not _forbidden(point, forbidden_regions)]
        if len(candidates) > 3000 or budget > 100:
            raise DesignError("D-optimal search is bounded to 3000 candidates and 100 runs")
        if budget < len(controls)+1 or budget > len(candidates):
            raise DesignError("D-optimal design needs at least p runs and no more than the distinct candidate count")
        vectors = [_design_vector(point, controls, bounds) for point in candidates]
        p = len(controls)+1
        inverse = [[(1e6 if i == j else 0.0) for j in range(p)] for i in range(p)]
        selected = []
        remaining = list(range(len(candidates)))
        for _ in range(budget):
            if cancel and cancel():
                raise InterruptedError("DOE design cancelled")
            best_i, best_gain = None, -1.0
            for candidate_i in remaining:
                x = vectors[candidate_i]
                gain = sum(x[i]*inverse[i][j]*x[j] for i in range(p) for j in range(p))
                if gain > best_gain:
                    best_i, best_gain = candidate_i, gain
            x = vectors[best_i]
            inv_x = [sum(inverse[i][j]*x[j] for j in range(p)) for i in range(p)]
            denom = 1.0+sum(x[i]*inv_x[i] for i in range(p))
            inverse = [[inverse[i][j]-inv_x[i]*inv_x[j]/denom for j in range(p)] for i in range(p)]
            selected.append(candidates[best_i]); remaining.remove(best_i)
        return _proposal("greedy D-optimal linear main-effects design", selected, controls, seed, blocks, "d_optimal",
                         {"candidate_grid_levels": levels, "candidate_count": len(candidates),
                          "model_terms": ["intercept", *controls],
                          "qualification": "locally D-optimal for a first-order model on the declared finite grid; interactions and curvature are not covered"}, cancel=cancel)
    if strategy == "next_best":
        if not rows or not metric_defs:
            raise DesignError("next_best requires existing observations and a defined target metric")
        metric = spec.get("target_metric")
        if metric not in metric_defs:
            raise DesignError("next_best requires target_metric from the defined metric list")
        if budget != 1:
            raise DesignError("sequential next_best proposes exactly one run per analysis")
        unit_field = spec.get("independent_unit_field") or (model_options or {}).get("cluster_field")
        if not isinstance(unit_field, str) or not unit_field:
            raise DesignError("next_best requires an explicit independent_unit_field or cluster_field")
        minimum_units = spec.get("min_independent_units", 10)
        if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 3:
            raise DesignError("min_independent_units must be at least 3")
        unit_ids = [str(_get_field(row, unit_field)) for row in rows]
        if len(set(unit_ids)) < len(unit_ids) and (
                (model_options or {}).get("covariance", "HC3") != "cluster"
                or (model_options or {}).get("cluster_field") != unit_field):
            raise DesignError("repeated independent units require cluster-robust uncertainty clustered on the same declared unit")
        levels = spec.get("candidate_levels", 21)
        if not isinstance(levels, int) or isinstance(levels, bool) or not 3 <= levels <= 41 or levels**len(controls) > 4096:
            raise DesignError("candidate_levels must be 3..41 and the finite grid may not exceed 4096 points")
        fit, model = fit_linear_model(rows, {name: {"role": "controllable", "unit": "unspecified"} for name in controls},
                                      metric, model_options or {}, cancel=cancel)
        if model is None or fit.get("status") != "VALID":
            raise DesignError("next_best requires an identifiable response model with estimable uncertainty")
        observed = {tuple(row["factors"][name] for name in controls) for row in rows}
        ranges = {name: [min(row["factors"][name] for row in rows), max(row["factors"][name] for row in rows)] for name in controls}
        if any(ranges[name][0] >= ranges[name][1] for name in controls):
            raise DesignError("next_best requires observed variation in every controllable factor")
        axes = [[bounds[name][0]+i*(bounds[name][1]-bounds[name][0])/(levels-1) for i in range(levels)] for name in controls]
        model_factors = fit["model_specification"]["factors"]
        if any(name not in controls for name in model_factors):
            raise DesignError("next_best model may use only declared controllable factors")
        omitted_varying = [name for name in controls if name not in model_factors
                           and len({row["factors"][name] for row in rows}) > 1]
        if omitted_varying:
            raise DesignError(f"next_best model omits varying controllable factors: {', '.join(omitted_varying)}")
        quadratic_terms = fit["model_specification"]["quadratic"]
        if not quadratic_terms:
            raise DesignError("next_best requires an explicitly specified quadratic response term")
        grouped_validation = _grouped_surface_validation(
            rows, {name: {"role": "controllable", "unit": "unspecified"} for name in controls},
            metric, model_options or {}, unit_field, cancel=cancel)
        if grouped_validation["quadratic_rmse"] >= grouped_validation["linear_rmse"]:
            raise DesignError("next_best refuses because the quadratic model did not improve grouped held-out prediction error")
        maximum_validation_rmse = spec.get("maximum_grouped_validation_rmse")
        if not isinstance(maximum_validation_rmse, (int, float)) or isinstance(maximum_validation_rmse, bool) or not isfinite(maximum_validation_rmse) or maximum_validation_rmse <= 0:
            raise DesignError("next_best requires an engineer-specified positive maximum_grouped_validation_rmse")
        grouped_validation["engineer_specified_maximum_rmse"] = float(maximum_validation_rmse)
        if grouped_validation["quadratic_rmse"] > maximum_validation_rmse:
            raise DesignError("next_best refuses because grouped held-out error exceeds maximum_grouped_validation_rmse")
        support_points = [tuple((row["factors"][name]-ranges[name][0])/(ranges[name][1]-ranges[name][0]) for name in controls) for row in rows]
        fixed_effects = spec.get("fixed_effects", {})
        if not isinstance(fixed_effects, dict):
            raise DesignError("fixed_effects must be an object")
        for field in fit["model_specification"]["fixed_effect_fields"]:
            if field not in fixed_effects:
                raise DesignError(f"next_best requires an explicit fixed effect value for {field}")
        # The incumbent is the best independently aggregated setting mean,
        # never the largest/smallest noisy individual measurement.
        incumbent_units = {}
        for row in rows:
            setting = tuple(row["factors"][name] for name in controls)
            unit = str(_get_field(row, unit_field))
            incumbent_units.setdefault(setting, {}).setdefault(unit, []).append(float(row["metrics"][metric]))
        incumbent_candidates = []
        for setting, by_unit in incumbent_units.items():
            if len(by_unit) >= minimum_units:
                unit_means = [sum(values)/len(values) for values in by_unit.values()]
                incumbent_candidates.append((setting, sum(unit_means)/len(unit_means), len(by_unit)))
        if not incumbent_candidates:
            raise DesignError("next_best requires at least one observed setting meeting the independent-unit minimum")
        direction = metric_defs[metric].get("direction", "maximize")
        maximizing = direction == "maximize"
        incumbent_setting, best_y, incumbent_n = (max(incumbent_candidates, key=lambda entry: entry[1]) if maximizing
                                                   else min(incumbent_candidates, key=lambda entry: entry[1]))
        top = None
        for point in product(*axes):
            if cancel and cancel():
                raise InterruptedError("sequential DOE cancelled")
            settings = dict(zip(controls, point))
            if tuple(point) in observed or any(not ranges[name][0] <= settings[name] <= ranges[name][1] for name in controls):
                continue
            if len(controls) == 2:
                normalized = tuple((settings[name]-ranges[name][0])/(ranges[name][1]-ranges[name][0]) for name in controls)
                observed_norm = sorted(set(support_points))
                hull = _hull(observed_norm)
                if len(hull) < 3 or not _inside_polygon(normalized, hull):
                    continue
            normalized = tuple((settings[name]-ranges[name][0])/(ranges[name][1]-ranges[name][0]) for name in controls)
            distances = [sqrt(sum((a-b)**2 for a, b in zip(normalized, other))) for other in support_points]
            nearby = [row for row, distance in zip(rows, distances) if distance <= 0.75]
            if len({str(_get_field(row, unit_field)) for row in nearby}) < minimum_units:
                continue
            prediction = model.predict(settings, fixed_effects)
            if prediction.get("status") != "ESTIMATED" or prediction["mean_standard_error"] <= 0:
                continue
            mu = prediction["estimate"] if maximizing else -prediction["estimate"]
            best = best_y if maximizing else -best_y
            sigma = prediction["mean_standard_error"]
            z = (mu-best)/sigma
            cdf = 0.5*(1+erf(z/sqrt(2)))
            density = exp(-0.5*z*z)/sqrt(2*pi)
            ei = max(0.0, (mu-best)*cdf+sigma*density)
            if top is None or ei > top["expected_improvement"]:
                top = {"settings": settings, "expected_improvement": ei, "prediction": prediction,
                       "nearest_normalized_distance": min(distances), "nearby_observation_count": sum(d <= 0.75 for d in distances)}
        if top is None:
            raise DesignError("no unobserved candidate has both local support and estimable uncertainty")
        return _proposal("sequential expected-improvement next experiment", [top["settings"]], controls, seed, 1,
                         "next_best", {"target_metric": metric, "objective_direction": direction,
                         "acquisition": "Gaussian expected improvement using mean-estimation standard error",
                         "expected_improvement": top["expected_improvement"], "prediction": top["prediction"],
                         "observed_incumbent": {"settings": dict(zip(controls, incumbent_setting)),
                                                "mean": best_y, "independent_units": incumbent_n},
                         "support": {"nearest_normalized_distance": top["nearest_normalized_distance"],
                                     "nearby_observations": top["nearby_observation_count"],
                                     "independent_unit_field": unit_field, "minimum_independent_units": minimum_units},
                         "model_diagnostics": fit,
                         "grouped_surface_validation": grouped_validation,
                         "qualification": "one-step advisory proposal inside observed support; grouped response error met an engineer-specified limit; no intervention guarantee"}, cancel=cancel)
    raise DesignError("strategy must be full_factorial, fractional_factorial, latin_hypercube, d_optimal, or next_best")
