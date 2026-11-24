"""Small, bounded DOE builders; suggestions are never executed."""
from __future__ import annotations

from itertools import combinations, product
from math import ceil, erf, exp, isfinite, pi, sqrt
from random import Random
from statistics import NormalDist, mean

from products.p4.regression import fit_linear_model, _get_field, _key, ModelError
from products.p4.window import _hull, _inside_polygon


class DesignError(ValueError):
    pass


def _independent_unit_key(row, unit_field):
    """Return a type-preserving key for an opaque independent-unit ID."""
    try:
        value = _get_field(row, unit_field)
    except ModelError as exc:
        raise DesignError(f"independent-unit field is missing: {unit_field}") from exc
    if (value is None or value == "" or isinstance(value, bool)
            or not isinstance(value, (str, int))):
        raise DesignError("independent-unit IDs must be nonempty strings or integers")
    return _key(value)


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


def _grouped_surface_validation(rows, factor_defs, metric, spec, model_options, unit_field, cancel=None):
    """Select a surface within development groups and evaluate it on untouched groups."""
    spec = spec or {}
    model_options = model_options or {}
    groups = sorted({_independent_unit_key(row, unit_field) for row in rows})
    minimum_training_groups = spec.get("validation_min_training_groups", spec.get("min_independent_units", 10))
    validation_fraction = spec.get("validation_fraction", 0.2)
    seed = spec.get("validation_seed", 20261122)
    if (not isinstance(minimum_training_groups, int) or isinstance(minimum_training_groups, bool)
            or minimum_training_groups < 10):
        raise DesignError("validation_min_training_groups must be at least 10")
    if (not isinstance(validation_fraction, (int, float)) or isinstance(validation_fraction, bool)
            or not isfinite(validation_fraction) or not 0.1 <= validation_fraction <= 0.4):
        raise DesignError("validation_fraction must be in [0.1, 0.4]")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise DesignError("validation_seed must be an integer")
    holdout_count = min(round(len(groups)*validation_fraction), len(groups)-minimum_training_groups)
    holdout_count = max(3, holdout_count)
    if len(groups) < minimum_training_groups+3 or holdout_count > len(groups)-minimum_training_groups:
        raise DesignError("next_best requires enough independent groups for separate model development and evaluation")
    shuffled_groups = groups[:]
    Random(seed).shuffle(shuffled_groups)
    evaluation_groups = set(shuffled_groups[:holdout_count])
    development_groups = set(groups)-evaluation_groups
    development_rows = [row for row in rows if _independent_unit_key(row, unit_field) in development_groups]
    evaluation_rows = [row for row in rows if _independent_unit_key(row, unit_field) in evaluation_groups]

    quadratic_options = dict(model_options)
    quadratic_options["covariance"] = "classical"
    quadratic_options.pop("independent_unit_field", None)
    linear_options = dict(quadratic_options)
    linear_options["quadratic"] = False
    linear_options["interactions"] = False
    linear_options["fixed_effect_interactions"] = []

    dev_groups = list(development_groups)
    Random(seed+1).shuffle(dev_groups)
    fold_count = min(5, max(2, len(dev_groups)//5))
    folds = [[] for _ in range(fold_count)]
    for index, group in enumerate(dev_groups):
        folds[index % fold_count].append(group)
    selection_errors = {"linear": {}, "quadratic": {}}
    for held_out_groups in folds:
        if cancel and cancel():
            raise InterruptedError("sequential DOE model selection cancelled")
        held = set(held_out_groups)
        training = [row for row in development_rows if _independent_unit_key(row, unit_field) not in held]
        validation = [row for row in development_rows if _independent_unit_key(row, unit_field) in held]
        q_fit, q_model = fit_linear_model(training, factor_defs, metric, quadratic_options, cancel=cancel)
        l_fit, l_model = fit_linear_model(training, factor_defs, metric, linear_options, cancel=cancel)
        if q_model is None or l_model is None:
            raise DesignError("next_best grouped model selection found a non-identifiable fold")
        fixed_fields = q_fit["model_specification"]["fixed_effect_fields"]
        for row in validation:
            if cancel and cancel():
                raise InterruptedError("sequential DOE model selection cancelled")
            fixed = {field: _get_field(row, field) for field in fixed_fields}
            actual = float(row["metrics"][metric])
            unit = _independent_unit_key(row, unit_field)
            selection_errors["quadratic"].setdefault(unit, []).append(
                (actual-q_model.predict(row["factors"], fixed)["estimate"])**2)
            selection_errors["linear"].setdefault(unit, []).append(
                (actual-l_model.predict(row["factors"], fixed)["estimate"])**2)

    def grouped_rmse(errors):
        return sqrt(mean(sum(values)/len(values) for values in errors.values()))

    linear_cv_rmse = grouped_rmse(selection_errors["linear"])
    quadratic_cv_rmse = grouped_rmse(selection_errors["quadratic"])
    selected_model = "quadratic" if quadratic_cv_rmse < linear_cv_rmse else "linear"
    selected_options = dict(model_options)
    selected_options["quadratic"] = (quadratic_options.get("quadratic") if selected_model == "quadratic" else False)
    if selected_model == "linear":
        selected_options["interactions"] = False
        selected_options["fixed_effect_interactions"] = []
    fit, model = fit_linear_model(development_rows, factor_defs, metric, selected_options, cancel=cancel)
    if model is None or fit.get("status") != "VALID":
        raise DesignError("next_best selected surface is not estimable on the development groups")

    fixed_fields = fit["model_specification"]["fixed_effect_fields"]
    squared_errors, errors = {}, []
    for row in evaluation_rows:
        if cancel and cancel():
            raise InterruptedError("sequential DOE holdout evaluation cancelled")
        fixed = {field: _get_field(row, field) for field in fixed_fields}
        actual = float(row["metrics"][metric])
        error = model.predict(row["factors"], fixed)["estimate"]-actual
        unit = _independent_unit_key(row, unit_field)
        squared_errors.setdefault(unit, []).append(error*error)
        errors.append(error)
    holdout_rmse = sqrt(mean(sum(values)/len(values) for values in squared_errors.values()))
    report = {"method": "grouped model-selection CV on development units plus untouched independent-unit evaluation holdout",
              "independent_group_count": len(groups), "development_group_count": len(development_groups),
              "evaluation_group_count": len(evaluation_groups), "development_row_count": len(development_rows),
              "evaluation_row_count": len(evaluation_rows), "validation_fraction": len(evaluation_groups)/len(groups),
              "validation_seed": seed, "model_selection": {"method": f"{fold_count}-fold grouped CV on development units",
                                    "linear_rmse": linear_cv_rmse, "quadratic_rmse": quadratic_cv_rmse,
                                    "selected_model": selected_model},
              "independent_evaluation": {"status": "COMPLETED_DIAGNOSTIC", "rmse": holdout_rmse,
                                          "mae": mean(abs(value) for value in errors), "bias": mean(errors),
                                          "independent_groups": len(squared_errors)},
              "selected_model": selected_model,
              "qualification": "formula selection uses development groups only; untouched group holdout performance is descriptive and not a future guarantee"}
    return report, development_rows, selected_options, fit, model


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


def _quadratic_design_vector(settings, controls, bounds):
    coded = [2*(settings[name]-bounds[name][0])/(bounds[name][1]-bounds[name][0])-1
             for name in controls]
    return ([1.0] + coded + [value*value for value in coded]
            + [coded[i]*coded[j] for i in range(len(coded)) for j in range(i+1, len(coded))])


def _matrix_rank(matrix, tolerance=1e-10):
    """Small-matrix pivoted elimination for the bounded <=8-factor DOE check."""
    if not matrix:
        return 0
    work = [list(map(float, row)) for row in matrix]
    rank, row_count, column_count = 0, len(work), len(work[0])
    for column in range(column_count):
        pivot = max(range(rank, row_count), key=lambda index: abs(work[index][column]), default=rank)
        if rank >= row_count or abs(work[pivot][column]) <= tolerance:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        scale = work[rank][column]
        work[rank] = [value/scale for value in work[rank]]
        for other in range(rank+1, row_count):
            factor = work[other][column]
            if abs(factor) > tolerance:
                work[other] = [value-factor*pivot_value
                               for value, pivot_value in zip(work[other], work[rank])]
        rank += 1
        if rank == row_count:
            break
    return rank


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


def _confirmation_t_critical(probability, degrees_of_freedom):
    """Three-term Cornish-Fisher approximation, used only for df >= 10."""
    z = NormalDist().inv_cdf(probability)
    nu = float(degrees_of_freedom)
    return (z + (z**3+z)/(4*nu)
            + (5*z**5+16*z**3+3*z)/(96*nu**2)
            + (3*z**7+19*z**5+17*z**3-15*z)/(384*nu**3))


def propose_window_confirmation(process_window, controls, bounds, spec, forbidden_regions,
                                metric_defs, cancel=None):
    """Create a randomized blocked confirmation plan for one D02 candidate.

    The D02 cell is used only to identify the proposed setting and carry its
    uncertainty evidence forward. D04 requires an explicitly named reference,
    paired-difference variability, effect target, and source references before
    proposing a powered, non-executing randomized comparison.
    """
    def refuse(reason, **details):
        return {"status": "REFUSED", "design": "D02 candidate confirmation", "reason": reason,
                "run_count": 0, "runs": [], "factors": controls,
                "executed": False, "actuation": "none", **details}

    if not isinstance(process_window, dict) or process_window.get("status") != "VALID":
        return refuse("a valid D02 supported-region result is required")
    candidate_factors = spec.get("candidate_factors")
    comparison_factors = spec.get("comparison_factors")
    if (not isinstance(candidate_factors, dict) or not isinstance(comparison_factors, dict)
            or set(comparison_factors) != set(controls)):
        return refuse("exact candidate factors from D02 and a complete engineer-supplied reference setting are required")
    d02_candidate = next((cell for cell in process_window.get("candidate_cells", [])
                          if isinstance(cell, dict) and cell.get("factors") == candidate_factors), None)
    if d02_candidate is None:
        return refuse("the requested setting is not a currently supported D02 candidate")
    if d02_candidate.get("supported_candidate") is not True:
        return refuse("the exact setting is no longer retained as a supported D02 advisory candidate")
    if d02_candidate.get("region_class") not in ("observed", "interpolated"):
        return refuse("D02 confirmation is limited to observed or supported interpolated settings")
    candidate_control_factors = {name: candidate_factors.get(name) for name in controls}
    if (any(not isinstance(candidate_control_factors[name], (int, float))
            or isinstance(candidate_control_factors[name], bool)
            or not isfinite(candidate_control_factors[name]) for name in controls)
            or any(not isinstance(comparison_factors[name], (int, float))
                   or isinstance(comparison_factors[name], bool)
                   or not isfinite(comparison_factors[name]) for name in controls)):
        return refuse("candidate and reference controllable settings must be finite numeric values")
    for label, settings in (("candidate", candidate_control_factors), ("reference", comparison_factors)):
        if any(not bounds[name][0] <= settings[name] <= bounds[name][1] for name in controls):
            return refuse(f"{label} settings must remain within the supplied approved factor bounds")
        try:
            if _forbidden(settings, forbidden_regions):
                return refuse(f"{label} setting intersects a supplied forbidden region")
        except (DesignError, TypeError, ValueError) as exc:
            return refuse(f"forbidden-region validation failed: {exc}")
    if all(candidate_control_factors[name] == comparison_factors[name] for name in controls):
        return refuse("candidate and reference settings must differ")

    metric = spec.get("target_metric")
    definition = metric_defs.get(metric) if isinstance(metric_defs, dict) else None
    interval = d02_candidate.get("predictions", {}).get(metric, {}).get("predictive_interval95")
    if (not isinstance(metric, str) or not isinstance(definition, dict)
            or (definition.get("min") is None and definition.get("max") is None)
            or not isinstance(interval, list) or len(interval) != 2
            or any(not isinstance(value, (int, float)) or not isfinite(value) for value in interval)):
        return refuse("a bounded target metric and its D02 empirical interval are required")
    objective = spec.get("objective_statement")
    if not isinstance(objective, str) or not objective.strip():
        return refuse("a prespecified engineering objective statement is required")
    paired_sd = spec.get("paired_difference_sd")
    paired_sd_basis = spec.get("paired_difference_sd_basis")
    paired_sd_confidence = spec.get("paired_difference_sd_confidence_level")
    paired_sd_df = spec.get("paired_difference_sd_degrees_of_freedom")
    detectable = spec.get("minimum_detectable_effect")
    alpha = spec.get("alpha", 0.05)
    target_power = spec.get("target_power", 0.8)
    if (any(not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isfinite(value) or value <= 0 for value in (paired_sd, detectable))
            or not isinstance(alpha, (int, float)) or isinstance(alpha, bool)
            or not isfinite(alpha) or not 0 < alpha < 0.2
            or not isinstance(target_power, (int, float)) or isinstance(target_power, bool)
            or not isfinite(target_power) or not 0.5 < target_power < 0.99):
        return refuse("positive paired-difference SD and MDE plus alpha and target power in valid ranges are required")
    for field in ("paired_difference_sd_source", "minimum_detectable_effect_source"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            return refuse(f"{field} is required so the power inputs have reviewable provenance")
    if paired_sd_basis not in ("ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND", "ENGINEER_APPROVED_HARD_BOUND"):
        return refuse("paired_difference_sd must be a source-backed conservative upper bound; a point estimate is not sufficient")
    if paired_sd_basis == "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND":
        if (not isinstance(paired_sd_confidence, (int, float)) or isinstance(paired_sd_confidence, bool)
                or not isfinite(paired_sd_confidence) or not 0.95 <= paired_sd_confidence < 1.0
                or not isinstance(paired_sd_df, int) or isinstance(paired_sd_df, bool) or paired_sd_df < 2):
            return refuse("a one-sided normal-theory SD upper bound requires confidence level >= 0.95 and at least 2 source degrees of freedom")
    elif any(value is not None for value in (paired_sd_confidence, paired_sd_df)):
        return refuse("confidence level and degrees of freedom must be omitted for an engineer-approved hard SD bound")
    seed = spec.get("seed", 20261122)
    budget = spec.get("run_budget")
    if not isinstance(seed, int) or isinstance(seed, bool):
        return refuse("seed must be an integer")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        return refuse("run_budget must be a positive integer")

    distribution = NormalDist()
    z_alpha = distribution.inv_cdf(1.0-alpha/2.0)
    z_power = distribution.inv_cdf(target_power)
    normal_pairs = max(2, ceil(((z_alpha+z_power)*paired_sd/detectable)**2))
    # The basic z formula underpowers Student-t confirmation tests at the
    # small sample sizes it often proposes. Use a t-critical expansion only
    # on its qualified df>=10 domain, retain normal power tails, and add one
    # complete pair as a finite-grid validated safety margin.
    required_pairs = None
    for pair_count in range(max(11, normal_pairs), 100_001):
        t_critical = _confirmation_t_critical(1.0-alpha/2.0, pair_count-1)
        if (detectable/paired_sd)*sqrt(pair_count) >= t_critical+z_power:
            required_pairs = pair_count+1
            break
    if required_pairs is None:
        return refuse("conservative confirmation sample-size approximation exceeds 100000 complete pairs",
                      maximum_pairs=100000, executed=False)
    required_runs = 2*required_pairs
    if required_runs > budget:
        return refuse("powered blocked confirmation exceeds the supplied run budget",
                      required_pair_count=required_pairs, required_runs=required_runs,
                      run_budget=budget, objective_statement=objective)

    rng = Random(seed)
    runs = []
    for block in range(1, required_pairs+1):
        if cancel and cancel():
            raise InterruptedError("D02 confirmation design cancelled")
        order = ["candidate", "reference"]
        rng.shuffle(order)
        for position, arm in enumerate(order, start=1):
            settings = candidate_control_factors if arm == "candidate" else comparison_factors
            runs.append({**settings, "arm": arm, "block": block, "replicate": block,
                         "order_within_block": position, "run_order": len(runs)+1})

    direction = definition.get("direction", "unspecified")
    candidate_evidence = {
        "factors": candidate_factors,
        "region_class": d02_candidate.get("region_class"),
        "pointwise_supported_candidate": d02_candidate.get("supported_candidate") is True,
        "simultaneous_supported_candidate": d02_candidate.get("simultaneous_supported_candidate") is True,
        "target_metric_interval95": interval,
        "simultaneous_target_metric_interval95": d02_candidate.get("predictions", {}).get(metric, {}).get("simultaneous_group_interval95"),
        "d02_simultaneous_scope": process_window.get("simultaneous_exact_setting_screen", {}).get("status_scope"),
    }
    return {
        "status": "PROPOSED", "design": "randomized blocked D02 candidate confirmation",
        "claim_method": "randomized_blocked_confirmation_proposal",
        "objective_statement": objective,
        "objective": {"metric": metric, "unit": definition.get("unit"), "direction": direction,
                      "minimum_detectable_effect": detectable,
                      "effect_input_source": spec["minimum_detectable_effect_source"]},
        "candidate_evidence": candidate_evidence,
        "reference_factors": comparison_factors,
        "power": {"method": "two-sided paired mean; three-term Cornish-Fisher Student-t critical plus normal power-tail approximation and one-pair margin",
                  "paired_difference_sd": paired_sd,
                  "paired_difference_sd_source": spec["paired_difference_sd_source"],
                  "paired_difference_sd_basis": paired_sd_basis,
                  "paired_difference_sd_confidence_level": paired_sd_confidence,
                  "paired_difference_sd_degrees_of_freedom": paired_sd_df,
                  "paired_sd_scope": "caller-supplied conservative upper bound; P4 does not recompute or authenticate it",
                  "alpha": alpha, "target_power": target_power,
                  "normal_approximation_reference_pairs": normal_pairs,
                  "required_complete_pairs": required_pairs,
                  "approximation_limitations": ["assumes independent randomized blocks and a valid conservative paired-difference SD upper bound",
                                                "Student-t critical is a Cornish-Fisher approximation restricted to at least 11 pairs; power tail remains normal and is not exact noncentral-t power",
                                                "one extra pair was retained after comparison with a fixed SciPy noncentral-t qualification grid; this is not a universal guarantee",
                                                "the SD bound method, population relevance, and source references are caller-supplied and unverified"]},
        "blocking": {"method": "randomized complete pairs; one candidate and one reference run within each block",
                     "block_count": required_pairs,
                     "order_assignment": "seeded random order within each pair",
                     "analysis_requirement": "analyze candidate-minus-reference within each block; report attrition, deviations, population, and measurement uncertainty"},
        "run_count": required_runs, "run_budget": budget, "runs": runs,
        "factors": controls, "randomization_seed": seed,
        "required_engineer_review": ["confirm the exact candidate/reference settings and all approved bounds",
                                     "verify the paired-difference SD conservative upper-bound method, source, population, and MDE evidence",
                                     "approve randomization, blocking, measurement, safety and operational feasibility"],
        "evidence_required_before_next_iteration": ["assigned and executed order with block and arm identity",
                                                     "source paired differences and the upper-bound calculation record, including confidence level and degrees of freedom where applicable",
                                                     "outcomes at the declared observation grain for both arms",
                                                     "product/tool/chamber/lot/time population and measurement method",
                                                     "failed runs, missing outcomes, protocol deviations and exclusions",
                                                     "source hashes and metric/limit version used for analysis"],
        "authorization_fields": ["engineer_approval_id", "process_owner_approval_id", "safety_review_id"],
        "qualification": "non-executing confirmatory experiment proposal; D02 evidence remains advisory",
        "executed": False, "actuation": "none",
    }


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
    if strategy == "central_composite":
        factor_count = len(controls)
        center_replicates = spec.get("center_replicates", 2)
        if not 2 <= factor_count <= 8:
            raise DesignError("face-centered central-composite response-surface design requires 2 to 8 factors")
        if (not isinstance(center_replicates, int) or isinstance(center_replicates, bool)
                or not 2 <= center_replicates <= 100):
            raise DesignError("central-composite center_replicates must be an integer from 2 to 100")
        if any(not isinstance(bounds.get(name), (list, tuple)) or len(bounds[name]) != 2
               or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                      or not isfinite(value) for value in bounds[name])
               or bounds[name][0] >= bounds[name][1] for name in controls):
            raise DesignError("central-composite factors require finite, increasing approved bounds")
        required_runs = 2**factor_count + 2*factor_count + center_replicates
        if required_runs > budget:
            raise DesignError(f"face-centered central-composite design requires {required_runs} runs; budget is {budget}")
        if blocks > required_runs:
            raise DesignError("central-composite block count must not exceed its planned run count")
        coded_rows = []
        for corner in product((-1.0, 1.0), repeat=factor_count):
            coded_rows.append(("factorial", corner, None))
        for factor_index in range(factor_count):
            for level in (-1.0, 1.0):
                axial = [0.0]*factor_count
                axial[factor_index] = level
                coded_rows.append(("axial", tuple(axial), None))
        coded_rows.extend(("center", (0.0,)*factor_count, replicate)
                          for replicate in range(1, center_replicates+1))
        runs = []
        for index, (kind, coordinates, replicate) in enumerate(coded_rows, start=1):
            if cancel and cancel():
                raise InterruptedError("central-composite design cancelled")
            settings = {name: bounds[name][0]+(coordinates[position]+1.0)
                        * (bounds[name][1]-bounds[name][0])/2.0
                        for position, name in enumerate(controls)}
            if _forbidden(settings, forbidden_regions):
                raise DesignError("a forbidden region intersects the central-composite design; removing points would invalidate its quadratic model support")
            runs.append({**settings, "design_point_id": f"CCD-{index:03d}",
                         "design_point_type": kind, "replicate": replicate or 1})
        model_terms = ["intercept", *controls, *[f"{name}^2" for name in controls]]
        model_terms.extend(f"{controls[i]}:{controls[j]}"
                           for i in range(factor_count) for j in range(i+1, factor_count))
        matrix = [_quadratic_design_vector(run, controls, bounds) for run in runs]
        rank = _matrix_rank(matrix)
        if rank != len(model_terms):
            raise DesignError(f"central-composite design is not full rank for its quadratic model ({rank}/{len(model_terms)})")
        return _proposal("randomized face-centered central-composite response-surface design",
                         runs, controls, seed, blocks, "central_composite",
                         {"factorial_runs": 2**factor_count,
                          "axial_runs": 2*factor_count,
                          "center_replicates": center_replicates,
                          "coded_factor_levels": [-1.0, 0.0, 1.0],
                          "model_terms": model_terms,
                          "quadratic_model_matrix_rank": rank,
                          "qualification": "full-rank quadratic response-surface design at face-centered points within the supplied bounds; estimates only the stated second-order terms and cannot validate higher-order behavior"},
                         cancel=cancel)
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
        if len(controls) > 2:
            raise DesignError("next_best requires one or two factors; this release has no qualified joint-support geometry above two dimensions, so screen or block factors before sequential selection")
        if budget != 1:
            raise DesignError("sequential next_best proposes exactly one run per analysis")
        unit_field = spec.get("independent_unit_field") or (model_options or {}).get("cluster_field")
        if not isinstance(unit_field, str) or not unit_field:
            raise DesignError("next_best requires an explicit independent_unit_field or cluster_field")
        minimum_units = spec.get("min_independent_units", 10)
        if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 3:
            raise DesignError("min_independent_units must be at least 3")
        unit_ids = [_independent_unit_key(row, unit_field) for row in rows]
        if len(set(unit_ids)) < len(unit_ids) and (
                (model_options or {}).get("covariance", "HC3") != "cluster"
                or (model_options or {}).get("cluster_field") != unit_field):
            raise DesignError("repeated independent units require cluster-robust uncertainty clustered on the same declared unit")
        levels = spec.get("candidate_levels", 21)
        if not isinstance(levels, int) or isinstance(levels, bool) or not 3 <= levels <= 41 or levels**len(controls) > 4096:
            raise DesignError("candidate_levels must be 3..41 and the finite grid may not exceed 4096 points")
        model_options = model_options or {}
        declared_quadratic = model_options.get("quadratic")
        if declared_quadratic is not True and not (isinstance(declared_quadratic, list) and declared_quadratic):
            raise DesignError("next_best requires a caller-specified quadratic response candidate for model selection")
        model_factors = model_options.get("factor_fields", controls)
        if not isinstance(model_factors, list) or not model_factors:
            raise DesignError("next_best requires explicit model factor fields")
        if any(name not in controls for name in model_factors):
            raise DesignError("next_best model may use only declared controllable factors")
        omitted_varying = [name for name in controls if name not in model_factors
                           and len({row["factors"][name] for row in rows}) > 1]
        if omitted_varying:
            raise DesignError(f"next_best model omits varying controllable factors: {', '.join(omitted_varying)}")
        maximum_validation_rmse = spec.get("maximum_grouped_validation_rmse")
        if not isinstance(maximum_validation_rmse, (int, float)) or isinstance(maximum_validation_rmse, bool) or not isfinite(maximum_validation_rmse) or maximum_validation_rmse <= 0:
            raise DesignError("next_best requires an engineer-specified positive maximum_grouped_validation_rmse")
        constraint_metrics = spec.get("constraint_metrics", [])
        if (not isinstance(constraint_metrics, list)
                or any(not isinstance(name, str) or not name for name in constraint_metrics)
                or len(set(constraint_metrics)) != len(constraint_metrics)
                or metric in constraint_metrics):
            raise DesignError("constraint_metrics must be a unique list of defined metrics separate from target_metric")
        constraint_validation_limits = spec.get("maximum_grouped_validation_rmse_by_metric", {})
        if not isinstance(constraint_validation_limits, dict):
            raise DesignError("maximum_grouped_validation_rmse_by_metric must map constrained metric names to positive RMSE limits")
        for constraint_metric in constraint_metrics:
            definition = metric_defs.get(constraint_metric)
            limit = constraint_validation_limits.get(constraint_metric)
            if (not isinstance(definition, dict) or
                    (definition.get("min") is None and definition.get("max") is None)):
                raise DesignError(f"constrained metric {constraint_metric} needs an explicit engineering min or max bound")
            if (not isinstance(limit, (int, float)) or isinstance(limit, bool)
                    or not isfinite(limit) or limit <= 0):
                raise DesignError(f"constrained metric {constraint_metric} needs its own positive grouped validation RMSE limit")
            if any(not isinstance(row.get("metrics", {}).get(constraint_metric), (int, float))
                   or isinstance(row.get("metrics", {}).get(constraint_metric), bool)
                   or not isfinite(row.get("metrics", {}).get(constraint_metric)) for row in rows):
                raise DesignError(f"constrained metric {constraint_metric} must be finite for every development/evaluation observation")
        grouped_validation, development_rows, selected_options, fit, model = _grouped_surface_validation(
            rows, {name: {"role": "controllable", "unit": "unspecified"} for name in controls},
            metric, spec, model_options, unit_field, cancel=cancel)
        grouped_validation["engineer_specified_maximum_rmse"] = float(maximum_validation_rmse)
        evaluation_rmse = grouped_validation["independent_evaluation"]["rmse"]
        if evaluation_rmse > maximum_validation_rmse:
            raise DesignError("next_best refuses because untouched grouped evaluation error exceeds maximum_grouped_validation_rmse")
        constraint_models, constraint_fits, constraint_validations = {}, {}, {}
        for constraint_metric in constraint_metrics:
            validation, constraint_development_rows, _constraint_options, constraint_fit, constraint_model = _grouped_surface_validation(
                rows, {name: {"role": "controllable", "unit": "unspecified"} for name in controls},
                constraint_metric, spec, model_options, unit_field, cancel=cancel)
            if ({_independent_unit_key(row, unit_field) for row in constraint_development_rows}
                    != {_independent_unit_key(row, unit_field) for row in development_rows}):
                raise DesignError("constrained metric models must use the same development/evaluation independent units")
            limit = float(constraint_validation_limits[constraint_metric])
            validation["engineer_specified_maximum_rmse"] = limit
            if validation["independent_evaluation"]["rmse"] > limit:
                raise DesignError(f"next_best refuses because constrained metric {constraint_metric} exceeds its grouped evaluation RMSE limit")
            constraint_models[constraint_metric] = constraint_model
            constraint_fits[constraint_metric] = constraint_fit
            constraint_validations[constraint_metric] = validation
        observed = {tuple(row["factors"][name] for name in controls) for row in development_rows}
        ranges = {name: [min(row["factors"][name] for row in development_rows),
                         max(row["factors"][name] for row in development_rows)] for name in controls}
        if any(ranges[name][0] >= ranges[name][1] for name in controls):
            raise DesignError("next_best requires observed variation in every development factor")
        axes = [[bounds[name][0]+i*(bounds[name][1]-bounds[name][0])/(levels-1) for i in range(levels)] for name in controls]
        support_points = [tuple((row["factors"][name]-ranges[name][0])/(ranges[name][1]-ranges[name][0]) for name in controls) for row in development_rows]
        fixed_effects = spec.get("fixed_effects", {})
        if not isinstance(fixed_effects, dict):
            raise DesignError("fixed_effects must be an object")
        for field in fit["model_specification"]["fixed_effect_fields"]:
            if field not in fixed_effects:
                raise DesignError(f"next_best requires an explicit fixed effect value for {field}")
        # The incumbent is the best independently aggregated setting mean,
        # never the largest/smallest noisy individual measurement.
        incumbent_units = {}
        for row in development_rows:
            setting = tuple(row["factors"][name] for name in controls)
            unit = _independent_unit_key(row, unit_field)
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
        forbidden_candidate_count = 0
        constraint_candidate_count = 0
        constraint_rejected_candidate_count = 0
        for point in product(*axes):
            if cancel and cancel():
                raise InterruptedError("sequential DOE cancelled")
            settings = dict(zip(controls, point))
            if _forbidden(settings, forbidden_regions):
                forbidden_candidate_count += 1
                continue
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
            nearby = [row for row, distance in zip(development_rows, distances) if distance <= 0.75]
            if len({_independent_unit_key(row, unit_field) for row in nearby}) < minimum_units:
                continue
            prediction = model.predict(settings, fixed_effects)
            if prediction.get("status") != "ESTIMATED" or prediction["mean_standard_error"] <= 0:
                continue
            constraint_predictions = {}
            candidate_constraint_feasible = True
            for constraint_metric, constraint_model in constraint_models.items():
                constraint_prediction = constraint_model.predict(settings, fixed_effects)
                definition = metric_defs[constraint_metric]
                interval = constraint_prediction.get("predictive_interval95")
                interval_supported = (constraint_prediction.get("status") == "ESTIMATED"
                                      and isinstance(interval, (list, tuple)) and len(interval) == 2
                                      and all(isinstance(value, (int, float)) and isfinite(value) for value in interval))
                within_bounds = (interval_supported
                                 and (definition.get("min") is None or interval[0] >= definition["min"])
                                 and (definition.get("max") is None or interval[1] <= definition["max"]))
                constraint_predictions[constraint_metric] = {
                    "unit": definition.get("unit"), "min": definition.get("min"), "max": definition.get("max"),
                    "estimate": constraint_prediction.get("estimate"),
                    "predictive_interval95": interval,
                    "status": "MODEL_INTERVAL_WITHIN_SUPPLIED_BOUNDS" if within_bounds else
                              "UNSUPPORTED_OR_INTERVAL_OUTSIDE_SUPPLIED_BOUNDS"}
                candidate_constraint_feasible &= within_bounds
            if constraint_models:
                constraint_candidate_count += 1
                if not candidate_constraint_feasible:
                    constraint_rejected_candidate_count += 1
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
                       "constraint_predictions": constraint_predictions,
                       "nearest_normalized_distance": min(distances), "nearby_observation_count": sum(d <= 0.75 for d in distances)}
        if top is None:
            if constraint_metrics and constraint_candidate_count:
                raise DesignError("no unobserved locally supported candidate has predictive intervals inside every supplied engineering constraint")
            raise DesignError("no unobserved candidate has both local support and estimable uncertainty")
        return _proposal("sequential expected-improvement next experiment", [top["settings"]], controls, seed, 1,
                         "next_best", {"target_metric": metric, "objective_direction": direction,
                         "acquisition": "Gaussian expected improvement using mean-estimation standard error",
                         "expected_improvement": top["expected_improvement"], "prediction": top["prediction"],
                         "observed_incumbent": {"settings": dict(zip(controls, incumbent_setting)),
                                                "mean": best_y, "independent_units": incumbent_n},
                         "support": {"nearest_normalized_distance": top["nearest_normalized_distance"],
                                     "nearby_observations": top["nearby_observation_count"],
                                     "forbidden_candidates_excluded": forbidden_candidate_count,
                                     "independent_unit_field": unit_field, "minimum_independent_units": minimum_units},
                         "constraint_evaluation": {
                             "status": "MODEL_BASED_INTERVAL_SCREEN_ONLY" if constraint_metrics else "NOT_REQUESTED",
                             "constraint_metrics": constraint_metrics,
                             "candidate_count_with_support_and_estimable_objective": constraint_candidate_count,
                             "rejected_candidate_count": constraint_rejected_candidate_count,
                             "selected_candidate": top["constraint_predictions"],
                             "validation_by_metric": constraint_validations,
                             "model_diagnostics_by_metric": constraint_fits,
                             "qualification": "model-based predictive intervals screened against caller-supplied bounds; this is not a probability or production-feasibility guarantee"},
                         "model_diagnostics": fit,
                         "grouped_surface_validation": grouped_validation,
                         "model_selection": {"selected_formula": grouped_validation["selected_model"],
                                             "data_used_for_candidate_selection": "development independent units only"},
                         "qualification": "one-step advisory proposal inside development support; formula selection used development groups and the untouched group holdout met the engineer-specified error limit; holdout scores are descriptive and do not guarantee future performance or intervention response"}, cancel=cancel)
    raise DesignError("strategy must be full_factorial, fractional_factorial, latin_hypercube, d_optimal, or next_best")
