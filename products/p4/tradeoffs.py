"""Approved, paired cross-step objective comparison for D03."""
from __future__ import annotations

from datetime import datetime
from itertools import combinations
from math import isfinite, log, sqrt
from statistics import NormalDist, mean, variance
import json

from products.p4.regression import critical_t_975


class RelationshipError(ValueError):
    pass


def _identity_key(value):
    """Preserve the scalar type of opaque engineering identifiers."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RelationshipError("independent-unit and join identifiers must be strings or integers")
    if value == "":
        raise RelationshipError("independent-unit and join identifiers must not be empty")
    return json.dumps({"type": type(value).__name__, "value": value},
                      sort_keys=True, separators=(",", ":"))


def _path(row, path):
    value = row
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise RelationshipError(f"relationship field is missing: {path}")
        value = value[part]
    return value


def _datetime(value, field):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RelationshipError(f"{field} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RelationshipError(f"{field} must be timezone-aware ISO-8601")
    return parsed


def _dominates(a, b, objectives):
    better_or_equal = True
    strictly_better = False
    for objective in objectives:
        metric, direction = objective["metric"], objective["direction"]
        av, bv = a["means"][metric], b["means"][metric]
        if direction == "maximize":
            better_or_equal &= av >= bv
            strictly_better |= av > bv
        else:
            better_or_equal &= av <= bv
            strictly_better |= av < bv
    return better_or_equal and strictly_better


def _interval_separated_dominates(a, b, objectives, interval_key="marginal_ci95"):
    """Check rectangular interval separation for every declared objective."""
    strict = False
    for objective in objectives:
        metric, direction = objective["metric"], objective["direction"]
        left = a.get("uncertainty", {}).get(metric, {}).get(interval_key)
        right = b.get("uncertainty", {}).get(metric, {}).get(interval_key)
        if (not isinstance(left, (list, tuple)) or len(left) != 2
                or not isinstance(right, (list, tuple)) or len(right) != 2):
            return False
        if direction == "maximize":
            if left[0] < right[1]:
                return False
            strict = strict or left[0] > right[1]
        else:
            if left[1] > right[0]:
                return False
            strict = strict or left[1] < right[0]
    return strict


def _familywise_t_critical(df, family_size):
    """Conservative Cornish-Fisher Student-t critical value on a bounded domain.

    The formula is independently checked against SciPy's t.ppf in qualification
    tests. Runtime use abstains outside 10<=df<=300 and family size<=40; no SciPy
    runtime dependency is added to the offline analytical engine.
    """
    if (not isinstance(df, int) or not 10 <= df <= 300
            or not isinstance(family_size, int) or not 1 <= family_size <= 40):
        return None
    alpha = 0.05 / family_size
    z = NormalDist().inv_cdf(1.0-alpha/2.0)
    v = float(df)
    z2, z3, z5, z7, z9 = z*z, z**3, z**5, z**7, z**9
    approximation = (z + (z3+z)/(4*v)
                     + (5*z5+16*z3+3*z)/(96*v**2)
                     + (3*z7+19*z5+17*z3-15*z)/(384*v**3)
                     + (79*z9+776*z7+1482*z5-1920*z3-945*z)/(92160*v**4))
    # A small validated additive margin protects against the finite expansion's
    # observed under-shoot in the qualified df/family-size grid.
    return approximation + 0.002


def _familywise_mean_envelope(candidates, objectives, *, allow=True,
                              unavailable_status="NOT_AVAILABLE_AFTER_OUTCOME_BASED_CONSTRAINT_SELECTION",
                              bounded_contract=None, metric_units=None, t_precommit=None):
    family_size = len(candidates) * len(objectives)
    summary = {"status": "NOT_AVAILABLE", "familywise_alpha": 0.05,
               "mean_parameter_count": family_size,
               "method": "Bonferroni simultaneous independent-unit Student-t mean rectangles with conservative Cornish-Fisher critical approximation",
               "assumptions": ["each setting-specific independent-unit mean is estimable from independent units",
                               "setting-specific independent-unit means are approximately normal for Student-t intervals",
                               "candidate settings and objective family are fully represented before inspecting their mean rankings",
                               "outcome-based constraint exclusions disable this family-wise comparison"],
               "limitations": ["critical approximation is independently checked only for 10<=df<=300 and family size<=40",
                               "rectangular means do not estimate a causal setting effect or harmonize incompatible populations"]}
    for candidate in candidates:
        candidate["familywise_dominance_status"] = "NOT_ESTABLISHED"
        candidate["familywise_dominated_by"] = []
        for metric in candidate.get("uncertainty", {}):
            candidate["uncertainty"][metric]["familywise_ci95"] = None
    if not allow:
        summary["status"] = unavailable_status
        return summary, []
    if family_size < 1:
        summary["status"] = "NO_ESTIMABLE_OBJECTIVE_MEANS"
        return summary, []
    if bounded_contract is not None:
        summary["method"] = "distribution-free two-sided Hoeffding mean rectangles with Bonferroni allocation"
        if not isinstance(bounded_contract, dict):
            summary["status"] = "INVALID_BOUNDED_MEAN_CONTRACT"
            summary["reason"] = "familywise_mean_bounds must be an object"
            return summary, []
        plan_reference = bounded_contract.get("precommit_reference")
        bounds_reference = bounded_contract.get("bounds_source_reference")
        precommitted_candidates = bounded_contract.get("candidate_setting_ids")
        bounds = bounded_contract.get("metric_bounds")
        declared_units = bounded_contract.get("metric_units")
        if (not isinstance(plan_reference, str) or not plan_reference.strip()
                or not isinstance(bounds_reference, str) or not bounds_reference.strip()):
            summary["status"] = "INVALID_BOUNDED_MEAN_CONTRACT"
            summary["reason"] = "non-empty precommit and hard-bounds source references are required"
            return summary, []
        metric_names = [objective["metric"] for objective in objectives]
        expected_metrics = set(metric_names)
        if len(expected_metrics) != len(metric_names):
            summary["status"] = "INVALID_BOUNDED_MEAN_METRIC_FAMILY"
            summary["reason"] = "objective metrics must be unique in a bounded family"
            return summary, []
        actual_candidates = [candidate.get("id") for candidate in candidates]
        if (not isinstance(precommitted_candidates, list)
                or any(not isinstance(value, str) or not value.strip() for value in precommitted_candidates)
                or len(precommitted_candidates) != len(set(precommitted_candidates))
                or len(precommitted_candidates) != len(actual_candidates)
                or set(precommitted_candidates) != set(actual_candidates)):
            summary["status"] = "PRECOMMITTED_SETTING_FAMILY_MISMATCH"
            summary["reason"] = "bounded inference requires an exact, unique precommitted candidate setting ID family"
            return summary, []
        if not isinstance(bounds, dict) or set(bounds) != expected_metrics:
            summary["status"] = "INVALID_BOUNDED_MEAN_METRIC_FAMILY"
            summary["reason"] = "hard bounds must be supplied for exactly the declared objective metrics"
            return summary, []
        if (not isinstance(declared_units, dict) or set(declared_units) != expected_metrics
                or any(not isinstance(declared_units.get(metric), str) or not declared_units[metric].strip()
                       or declared_units[metric] != (metric_units or {}).get(metric)
                       for metric in expected_metrics)):
            summary["status"] = "INVALID_BOUNDED_MEAN_METRIC_UNITS"
            summary["reason"] = "hard-bound metric units must exactly match the declared objective metric units"
            return summary, []
        normalized_bounds = {}
        for metric, pair in bounds.items():
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not isfinite(value) for value in pair)
                    or pair[0] >= pair[1] or not isfinite(pair[1]-pair[0])):
                summary["status"] = "INVALID_BOUNDED_MEAN_RANGE"
                summary["reason"] = f"hard support bounds for {metric} must be finite [minimum, maximum] values"
                return summary, []
            normalized_bounds[metric] = [float(pair[0]), float(pair[1])]
        for candidate in candidates:
            n = candidate.get("independent_units", 0)
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                summary["status"] = "INVALID_BOUNDED_MEAN_SAMPLE_SIZE"
                return summary, []
            for metric in metric_names:
                estimate = candidate.get("uncertainty", {}).get(metric, {})
                observed_min = estimate.get("unit_value_min")
                observed_max = estimate.get("unit_value_max")
                lower, upper = normalized_bounds[metric]
                if (not isinstance(observed_min, (int, float)) or isinstance(observed_min, bool)
                        or not isinstance(observed_max, (int, float)) or isinstance(observed_max, bool)
                        or not isfinite(observed_min) or not isfinite(observed_max)
                        or observed_min < lower or observed_max > upper):
                    summary["status"] = "OBSERVED_UNIT_VALUE_OUTSIDE_SUPPLIED_HARD_BOUNDS"
                    summary["reason"] = f"observed independent-unit values for {metric} are not contained in the supplied hard bounds"
                    return summary, []
        alpha = 0.05
        for candidate in candidates:
            n = candidate["independent_units"]
            for metric in metric_names:
                estimate = candidate["uncertainty"][metric]
                lower, upper = normalized_bounds[metric]
                radius = (upper-lower) * sqrt(log(2.0*family_size/alpha)/(2.0*n))
                estimate["familywise_ci95"] = [max(lower, estimate["mean"]-radius),
                                                min(upper, estimate["mean"]+radius)]
                estimate["familywise_ci95_method"] = "two-sided Hoeffding bound with Bonferroni allocation"
                estimate["familywise_half_width"] = radius
        pairs = []
        dominators = {candidate["id"]: [] for candidate in candidates}
        for candidate in candidates:
            for other in candidates:
                if other is candidate:
                    continue
                if _interval_separated_dominates(other, candidate, objectives, "familywise_ci95"):
                    dominators[candidate["id"]].append(other["id"])
                    pairs.append({"dominant_setting_id": other["id"],
                                  "dominated_setting_id": candidate["id"],
                                  "scope": "Bonferroni_Hoeffding_bounded_mean_rectangles"})
        for candidate in candidates:
            candidate["familywise_dominated_by"] = sorted(dominators[candidate["id"]])
            candidate["familywise_dominance_status"] = (
                "FAMILYWISE_INTERVAL_SEPARATED_DOMINATED" if dominators[candidate["id"]]
                else "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR")
        summary.update({"status": "AVAILABLE_BOUNDED_HOEFFDING_ENVELOPE",
                        "familywise_alpha": alpha,
                        "familywise_confidence_target": 1.0-alpha,
                        "method": "distribution-free two-sided Hoeffding mean rectangles with Bonferroni allocation",
                        "mean_parameter_count": family_size,
                        "precommitted_candidate_setting_ids": sorted(precommitted_candidates),
                        "hard_bounds_units": {metric: declared_units[metric] for metric in sorted(expected_metrics)},
                        "hard_bounds": normalized_bounds,
                        "hard_bounds_source_reference": bounds_reference,
                        "precommit_reference": plan_reference,
                        "source_qualification_status": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
                        "assumptions": ["independent sampling units are independent draws from each stated target population",
                                        "each independent-unit aggregated objective value lies within its supplied hard bounds",
                                        "candidate settings and the objective family were fixed before mean outcomes were inspected",
                                        "no outcome-based exclusions were made"],
                        "limitations": ["the bound source and precommit timing are not authenticated by P4",
                                        "distribution-free intervals can be wide, especially for broad engineering bounds",
                                        "bounds apply to the independent-unit aggregated objective, not an individual replicate",
                                        "interval separation is not a causal effect or population-compatibility check"],
                        "interpretation": "finite-sample family-wise mean confidence is conditional on independent units, truthful supplied support bounds, and a fixed setting/objective family; no distribution shape assumption is required"})
        return summary, pairs
    if family_size > 40:
        summary["status"] = "NOT_AVAILABLE_FAMILY_EXCEEDS_40_MEANS"
        return summary, []
    if any(candidate.get("independent_units", 0) < 11 for candidate in candidates):
        summary["status"] = "NOT_AVAILABLE_REQUIRES_11_INDEPENDENT_UNITS_PER_SETTING"
        return summary, []
    if not isinstance(t_precommit, dict):
        summary["status"] = "NOT_AVAILABLE_PRECOMMIT_NOT_DECLARED"
        summary["reason"] = "the complete candidate-setting and objective family must be caller-declared before ranking"
        return summary, []
    reference = t_precommit.get("precommit_reference")
    declared_ids = t_precommit.get("candidate_setting_ids")
    declared_objectives = t_precommit.get("objectives")
    if (not isinstance(reference, str) or not reference.strip()
            or not isinstance(declared_ids, list)
            or any(not isinstance(value, str) or not value.strip() for value in declared_ids)
            or len(declared_ids) != len(set(declared_ids))):
        summary["status"] = "INVALID_T_PRECOMMIT_CONTRACT"
        summary["reason"] = "a nonempty precommit reference and unique candidate setting IDs are required"
        return summary, []
    actual_ids = [candidate.get("id") for candidate in candidates]
    if len(declared_ids) != len(actual_ids) or set(declared_ids) != set(actual_ids):
        summary["status"] = "PRECOMMITTED_SETTING_FAMILY_MISMATCH"
        summary["reason"] = "the declared candidate setting family does not exactly match the assessed settings"
        return summary, []
    actual_objectives = {(item["metric"], item["direction"]) for item in objectives}
    if (not isinstance(declared_objectives, list)
            or any(not isinstance(item, dict) or not isinstance(item.get("metric"), str)
                   or item.get("direction") not in ("maximize", "minimize") for item in declared_objectives)
            or len(declared_objectives) != len(set((item.get("metric"), item.get("direction"))
                                                   for item in declared_objectives))
            or {(item.get("metric"), item.get("direction")) for item in declared_objectives}
            != actual_objectives):
        summary["status"] = "PRECOMMITTED_OBJECTIVE_FAMILY_MISMATCH"
        summary["reason"] = "the declared objective family does not exactly match the assessed metrics and directions"
        return summary, []
    for candidate in candidates:
        df = candidate["independent_units"] - 1
        critical = _familywise_t_critical(df, family_size)
        if critical is None:
            summary["status"] = "NOT_AVAILABLE_OUTSIDE_VALIDATED_CRITICAL_VALUE_RANGE"
            return summary, []
        for objective in objectives:
            metric = objective["metric"]
            estimate = candidate["uncertainty"][metric]
            se = estimate.get("standard_error")
            if not isinstance(se, (int, float)) or not isfinite(se) or se <= 0:
                summary["status"] = "NOT_AVAILABLE_OBJECTIVE_STANDARD_ERROR"
                return summary, []
    for candidate in candidates:
        df = candidate["independent_units"] - 1
        critical = _familywise_t_critical(df, family_size)
        for objective in objectives:
            metric = objective["metric"]
            estimate = candidate["uncertainty"][metric]
            se = estimate["standard_error"]
            estimate["familywise_ci95"] = [estimate["mean"]-critical*se,
                                            estimate["mean"]+critical*se]
            estimate["familywise_critical_value"] = critical
            estimate["familywise_ci95_method"] = "Bonferroni simultaneous independent-unit Student-t mean rectangles with conservative critical approximation"
            estimate["familywise_half_width"] = critical*se
    pairs = []
    dominators = {candidate["id"]: [] for candidate in candidates}
    for candidate in candidates:
        for other in candidates:
            if other is candidate:
                continue
            if _interval_separated_dominates(other, candidate, objectives, "familywise_ci95"):
                dominators[candidate["id"]].append(other["id"])
                pairs.append({"dominant_setting_id": other["id"],
                              "dominated_setting_id": candidate["id"],
                              "scope": "Bonferroni_familywise_simultaneous_mean_rectangles"})
    for candidate in candidates:
        candidate["familywise_dominated_by"] = sorted(dominators[candidate["id"]])
        candidate["familywise_dominance_status"] = (
            "FAMILYWISE_INTERVAL_SEPARATED_DOMINATED" if dominators[candidate["id"]]
            else "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR")
    summary.update({"status": "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE",
                    "familywise_alpha": 0.05, "familywise_confidence_target": 0.95,
                    "precommit_reference": reference,
                    "precommitted_candidate_setting_ids": sorted(declared_ids),
                    "precommitted_objectives": sorted(declared_objectives,
                        key=lambda item: (item["metric"], item["direction"])),
                    "precommit_source_qualification_status": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
                    "critical_value_domain": {"minimum_degrees_of_freedom": 10,
                                              "maximum_degrees_of_freedom": 300,
                                              "maximum_mean_parameter_count": 40},
                    "interpretation": "Every reported mean rectangle uses a Bonferroni allocation across all candidate-setting/objective means; a rectangle-separated pair is a conservative family-wise diagnostic under the listed assumptions. Critical values use the validated approximation, not an exact special-function implementation."})
    return summary, pairs


def _uncertainty_dominance_audit(candidates, objectives, mean_front):
    pairs = []
    for candidate in candidates:
        dominators = []
        for other in candidates:
            if other is candidate:
                continue
            if _interval_separated_dominates(other, candidate, objectives):
                dominators.append(other["id"])
                pairs.append({"dominant_setting_id": other["id"],
                              "dominated_setting_id": candidate["id"],
                              "scope": "marginal_95_interval_separation_only"})
        candidate["mean_pareto_status"] = "NONDOMINATED_BY_MEANS" if candidate["id"] in mean_front else "DOMINATED_BY_MEANS"
        candidate["uncertainty_dominance_status"] = (
            "MARGINAL_INTERVAL_SEPARATED_DOMINATED" if dominators else "NO_INTERVAL_SEPARATED_DOMINATOR")
        candidate["interval_separated_dominated_by"] = sorted(dominators)
    return pairs


def observed_tradeoffs(rows, metric_defs, factor_defs, data, objectives, cancel=None):
    """Aggregate by controllable setting and independent unit before Pareto ranking."""
    def metric_pass(value, definition):
        return ((definition.get("min") is None or value >= definition["min"])
                and (definition.get("max") is None or value <= definition["max"]))
    robustness = data.get("robustness", {})
    unit_field = data.get("tradeoff_unit_field") or (robustness.get("independent_unit_field") if isinstance(robustness, dict) else None)
    if not isinstance(unit_field, str) or not unit_field:
        return {"status": "LIMITED_SCOPE", "reason": "multiobjective comparisons require an explicit independent-unit field",
                "pareto_observation_ids": [], "scope": "no uncertainty-aware setting comparison"}
    minimum_units = data.get("tradeoff_min_independent_units", 3)
    if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 2:
        raise RelationshipError("tradeoff_min_independent_units must be at least 2")
    controls = [name for name, definition in factor_defs.items() if definition.get("role", "controllable") == "controllable"]
    if not controls:
        return {"status": "LIMITED_SCOPE", "reason": "no controllable decision factors are defined", "pareto_observation_ids": []}
    all_groups = {}
    for row in rows:
        if cancel and cancel():
            raise InterruptedError("tradeoff analysis cancelled")
        setting = tuple(row["factors"][name] for name in controls)
        try:
            identity = _identity_key(_path(row, unit_field))
        except RelationshipError as exc:
            return {"status": "LIMITED_SCOPE", "reason": f"independent-unit identity is incomplete or invalid: {exc}",
                    "pareto_observation_ids": [], "scope": "no uncertainty-aware setting comparison"}
        all_groups.setdefault(setting, {}).setdefault(identity, []).append(row)
    groups = {}
    setting_audit = {}
    for setting, unit_rows in all_groups.items():
        eligible_units = {}
        excluded_units = set()
        excluded_observations = 0
        for unit, members in unit_rows.items():
            # Constraint selection happens at the independent-unit grain. A
            # single failing replicate excludes the whole unit rather than
            # leaving only its favorable measurements in the objective mean.
            if all(metric_pass(row["metrics"][name], definition)
                   for row in members for name, definition in metric_defs.items()):
                eligible_units[unit] = members
            else:
                excluded_units.add(unit)
                excluded_observations += len(members)
        setting_audit[setting] = {"all_independent_units": len(unit_rows),
                                  "eligible_independent_units": len(eligible_units),
                                  "excluded_independent_units": len(excluded_units),
                                  "all_observation_count": sum(len(members) for members in unit_rows.values()),
                                  "eligible_observation_count": sum(len(members) for members in eligible_units.values()),
                                  "excluded_observation_count": excluded_observations}
        if eligible_units:
            groups[setting] = eligible_units
    excluded_units_total = sum(item["excluded_independent_units"] for item in setting_audit.values())
    exclusion_audit = {"status": "NO_CONSTRAINT_EXCLUSIONS" if excluded_units_total == 0 else "DESCRIPTIVE_CONSTRAINT_SELECTION",
                       "independent_unit_field": unit_field,
                       "eligible_population": "whole independent units with every observed row inside all supplied metric bounds",
                       "excluded_independent_units": excluded_units_total,
                       "settings": [{"factors": dict(zip(controls, setting)), **audit}
                                    for setting, audit in setting_audit.items()],
                       "interpretation": "constraint-based selection can change compared populations; it is reported by setting and is not adjusted inference"}
    unassessed_settings = [{"id": "SYN-SETTING-"+"-".join(f"{value:g}" for value in setting),
                            "factors": dict(zip(controls, setting)),
                            "eligible_independent_units": audit["eligible_independent_units"],
                            "required_independent_units": minimum_units,
                            "reason": "below independent-unit minimum"}
                           for setting, audit in setting_audit.items()
                           if audit["eligible_independent_units"] < minimum_units]
    candidates = []
    uncertainty_available = True
    for setting, unit_rows in groups.items():
        if len(unit_rows) < minimum_units:
            continue
        unit_metrics = []
        observation_ids = []
        for unit, members in unit_rows.items():
            observation_ids.extend(member["id"] for member in members)
            unit_metrics.append({metric: mean(member["metrics"][metric] for member in members) for metric in metric_defs})
        estimates = {}
        for objective in objectives:
            metric = objective["metric"]
            values = [member[metric] for member in unit_metrics]
            avg = mean(values)
            se = sqrt(variance(values)/len(values)) if len(values) > 1 else None
            if se is None or se == 0:
                uncertainty_available = False
                interval = None
            else:
                critical = critical_t_975(len(values)-1)
                interval = [avg-critical*se, avg+critical*se]
            estimates[metric] = {"mean": avg, "standard_error": se, "marginal_ci95": interval,
                                 "unit_value_min": min(values), "unit_value_max": max(values)}
        candidates.append({"id": "SYN-SETTING-"+"-".join(f"{value:g}" for value in setting),
                           "factors": dict(zip(controls, setting)), "independent_units": len(unit_rows),
                           "constraint_eligibility": setting_audit[setting],
                           "observation_count": sum(len(members) for members in unit_rows.values()),
                           "source_observation_ids": sorted(observation_ids),
                           "means": {metric: value["mean"] for metric, value in estimates.items()}, "uncertainty": estimates})
    if not candidates:
        return {"status": "LIMITED_SCOPE", "reason": "no setting met the independent-unit minimum",
                "minimum_independent_units": minimum_units, "pareto_observation_ids": [],
                "constraint_exclusion_audit": exclusion_audit, "unassessed_settings": unassessed_settings,
                "selection_warning": "No setting met the independent-unit minimum after whole-unit constraint screening; inspect the exclusion audit."}
    front = [candidate for candidate in candidates if not any(other is not candidate and _dominates(other, candidate, objectives)
                                                               for other in candidates)]
    mean_front_ids = [candidate["id"] for candidate in front]
    interval_dominance = _uncertainty_dominance_audit(candidates, objectives, set(mean_front_ids))
    eligible_unit_sets = [set(unit_rows) for unit_rows in groups.values() if len(unit_rows) >= minimum_units]
    identical_unit_cohorts = (not eligible_unit_sets or all(values == eligible_unit_sets[0]
                                                            for values in eligible_unit_sets[1:]))
    familywise_envelope, familywise_dominance = _familywise_mean_envelope(
        candidates, objectives, allow=excluded_units_total == 0 and not unassessed_settings and identical_unit_cohorts,
        unavailable_status=("NOT_AVAILABLE_AFTER_OUTCOME_BASED_CONSTRAINT_SELECTION"
                            if excluded_units_total else
                            "NOT_AVAILABLE_INSUFFICIENT_UNITS_FOR_SOME_SETTINGS" if unassessed_settings else
                            "NOT_AVAILABLE_INCOMPATIBLE_INDEPENDENT_UNIT_COHORTS"),
        bounded_contract=data.get("familywise_mean_bounds"),
        t_precommit=data.get("familywise_t_precommit"),
        metric_units={metric: definition.get("unit") for metric, definition in metric_defs.items()})
    familywise_envelope["population_compatibility"] = (
        "IDENTICAL_INDEPENDENT_UNIT_SET_AT_EVERY_INCLUDED_SETTING" if identical_unit_cohorts
        else "SETTING_SPECIFIC_INDEPENDENT_UNIT_SETS_DIFFER")
    warning_parts = []
    if excluded_units_total:
        warning_parts.append("Constraint-passing outcomes are selected at the whole independent-unit level. Excluded unit counts are shown; candidate means describe only the eligible subset and may not be comparable to the full source population.")
    if unassessed_settings:
        warning_parts.append("Some observed settings were omitted because they did not meet the independent-unit minimum; the Pareto front is incomplete.")
    selection_warning = " ".join(warning_parts) or None
    return {"status": "VALID" if uncertainty_available and excluded_units_total == 0 and not unassessed_settings else "LIMITED_SCOPE",
            "method": "independent-unit-aggregated-Pareto-with-marginal-t-intervals",
            "objective_metrics": [{**objective, "unit": metric_defs[objective["metric"]].get("unit")}
                                  for objective in objectives],
            "decision_factors": controls, "independent_unit_field": unit_field,
            "minimum_independent_units": minimum_units, "candidate_settings": candidates,
            "constraint_exclusion_audit": exclusion_audit, "selection_warning": selection_warning,
            "unassessed_settings": unassessed_settings,
            "pareto_setting_ids": mean_front_ids, "mean_pareto_setting_ids": mean_front_ids,
            "interval_separated_dominance": interval_dominance,
            "familywise_mean_envelope": familywise_envelope,
            "familywise_interval_separated_dominance": familywise_dominance,
            "familywise_nondominated_setting_ids": [candidate["id"] for candidate in candidates
                                                       if candidate["familywise_dominance_status"] == "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR"],
            "pareto_status_scope": "mean-based observed front among whole-unit constraint-eligible observations; marginal interval separation is diagnostic only; the separate Bonferroni envelope is assumption-conditional and unavailable after outcome-based constraint selection",
            "pareto_observation_ids": sorted({row_id for candidate in front for row_id in candidate["source_observation_ids"]}),
            "pareto_values": [{"id": c["id"], "factors": c["factors"], **c["means"]} for c in front],
            "tradeoff_count": len(front), "uncertainty_available": uncertainty_available,
            "multiplicity_adjusted": False, "causal_claim": False,
            "familywise_multiplicity_adjustment": familywise_envelope["status"],
            "qualification": "setting-level descriptive mean-based Pareto set among whole-unit constraint-eligible observations; constraint-based selection may change compared populations; marginal interval separation is not adjusted; the separate Bonferroni mean envelope is assumption-conditional and does not establish causal effects or reconcile incompatible setting populations"}


def cross_step_tradeoffs(rows, metric_defs, data, cancel=None):
    """Validate an explicit relationship contract and compute paired setting means.

    This is synthetic qualification behavior. An approved field map still needs
    real site approval and semantic verification before internal data can flow.
    """
    link = data.get("linkage")
    if not isinstance(link, dict):
        return {"status": "LIMITED_SCOPE", "reason": "versioned approved relationship contract is absent",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    required = ("relationship_id", "contract_version", "approval_reference", "upstream", "downstream",
                "maximum_lag_seconds", "unit_field", "decision_factors")
    if link.get("approved") is not True or any(key not in link for key in required):
        return {"status": "LIMITED_SCOPE", "reason": "relationship contract or approval reference is incomplete",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    if (not str(link["relationship_id"]).startswith("SYN-")
            or not isinstance(link["contract_version"], str)
            or link["contract_version"] not in {"1.0.0", "1.1.0"}
            or not str(link["approval_reference"]).startswith("SYN-")):
        return {"status": "LIMITED_SCOPE", "reason": "only the versioned synthetic relationship contract can be qualified offline",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    if link["contract_version"] == "1.0.0" and "population_composition_fields" in link:
        return {"status": "LIMITED_SCOPE", "reason": "population composition mappings require relationship contract v1.1.0",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    upstream, downstream = link["upstream"], link["downstream"]
    if not isinstance(upstream, dict) or not isinstance(downstream, dict):
        raise RelationshipError("upstream and downstream mappings must be objects")
    field_names = ("source_id", "key_field", "event_time_field", "population_field", "population_id", "metric_field", "metric")
    for name, mapping in (("upstream", upstream), ("downstream", downstream)):
        if any(not isinstance(mapping.get(key), str) or not mapping[key] for key in field_names):
            raise RelationshipError(f"{name} mapping requires explicit source, key, event, population, and metric fields")
        if mapping["metric"] not in metric_defs:
            raise RelationshipError(f"{name} mapping references an undefined metric")
    if upstream["metric"] == downstream["metric"]:
        raise RelationshipError("cross-step objectives must identify distinct approved metrics")
    if upstream["population_id"] != downstream["population_id"]:
        return {"status": "LIMITED_SCOPE", "reason": "upstream and downstream engineering populations are not identical",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    sources = data.get("sources")
    if (not isinstance(sources, list)
            or any(not isinstance(source, dict) or not isinstance(source.get("id"), str)
                   or not source["id"].strip() for source in sources)):
        return {"status": "LIMITED_SCOPE", "reason": "relationship sources are not a validated evidence source list",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    source_ids = {source["id"] for source in sources}
    if upstream["source_id"] not in source_ids or downstream["source_id"] not in source_ids:
        return {"status": "LIMITED_SCOPE", "reason": "relationship sources are not both declared in the evidence source set",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    lag = link["maximum_lag_seconds"]
    if isinstance(lag, bool) or not isinstance(lag, (int, float)) or not isfinite(lag) or lag <= 0:
        raise RelationshipError("maximum_lag_seconds must be positive")
    unit_field = link["unit_field"]
    decision_factors = link["decision_factors"]
    if not isinstance(unit_field, str) or not unit_field or not isinstance(decision_factors, list) or not decision_factors:
        raise RelationshipError("unit_field and at least one decision factor are required")
    if (not isinstance(rows, list) or not rows):
        return {"status": "LIMITED_SCOPE", "reason": "relationship evidence contains no observations",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    if (any(not isinstance(name, str) or not name for name in decision_factors)
            or len(set(decision_factors)) != len(decision_factors)
            or any(not isinstance(row, dict) or not isinstance(row.get("factors"), dict)
                   or any(name not in row["factors"] for name in decision_factors) for row in rows)):
        raise RelationshipError("decision_factors must refer to normalized factors")
    objectives = data.get("objectives", [])
    if (not isinstance(objectives, list)
            or any(not isinstance(item, dict)
                   or not isinstance(item.get("metric"), str)
                   or item.get("direction") not in ("maximize", "minimize")
                   for item in objectives)):
        return {"status": "LIMITED_SCOPE", "reason": "approved relationship objectives are malformed",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    objective_map = {item.get("metric"): item.get("direction") for item in objectives}
    expected_metrics = {upstream["metric"], downstream["metric"]}
    if len(objective_map) != len(objectives) or set(objective_map) != expected_metrics:
        return {"status": "LIMITED_SCOPE", "reason": "objectives must match the approved upstream/downstream metric pair",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    for metric, direction in objective_map.items():
        if direction != metric_defs[metric].get("direction", "maximize"):
            return {"status": "LIMITED_SCOPE", "reason": "objective direction conflicts with the approved metric definition",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
    minimum_units = link.get("minimum_independent_units", 30)
    if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 3:
        raise RelationshipError("minimum_independent_units must be at least 3")

    raw_composition_fields = link.get("population_composition_fields")
    composition_fields = []
    composition_field_status = "DECLARED"
    if raw_composition_fields is None:
        composition_field_status = "NOT_ASSESSED_NO_DECLARED_COMPOSITION_FIELDS"
    elif (not isinstance(raw_composition_fields, list) or not raw_composition_fields
          or any(not isinstance(item, dict)
                 or any(not isinstance(item.get(key), str) or not item[key].strip()
                        for key in ("name", "upstream_field", "downstream_field"))
                 for item in raw_composition_fields)
          or len({item.get("name") for item in raw_composition_fields
                  if isinstance(item, dict)}) != len(raw_composition_fields)):
        composition_field_status = "INVALID_DECLARED_COMPOSITION_FIELDS"
    else:
        composition_fields = raw_composition_fields

    seen_pairs, seen_units = set(), set()
    groups = {}
    setting_audit = {}
    composition_counts = {}
    composition_labels = {}
    def metric_pass(value, definition):
        return ((definition.get("min") is None or value >= definition["min"])
                and (definition.get("max") is None or value <= definition["max"]))
    for index, row in enumerate(rows):
        if cancel and cancel():
            raise InterruptedError("cross-step analysis cancelled")
        up_key = _path(row, upstream["key_field"])
        down_key = _path(row, downstream["key_field"])
        try:
            up_identity = _identity_key(up_key)
            down_identity = _identity_key(down_key)
        except RelationshipError:
            up_identity = down_identity = None
        if up_identity is None or down_identity is None or up_identity != down_identity:
            return {"status": "LIMITED_SCOPE", "reason": "upstream/downstream keys do not map one-to-one for every paired observation",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        population_up = _path(row, upstream["population_field"])
        population_down = _path(row, downstream["population_field"])
        if population_up != upstream["population_id"] or population_down != downstream["population_id"]:
            return {"status": "LIMITED_SCOPE", "reason": "an observation is outside the approved compatible population",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        t_up = _datetime(_path(row, upstream["event_time_field"]), "upstream event time")
        t_down = _datetime(_path(row, downstream["event_time_field"]), "downstream event time")
        lag_seconds = (t_down-t_up).total_seconds()
        if lag_seconds < 0 or lag_seconds > lag:
            return {"status": "LIMITED_SCOPE", "reason": "downstream event is outside the approved temporal relationship window",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        pair = (up_identity, down_identity)
        unit = _path(row, unit_field)
        try:
            unit_identity = _identity_key(unit)
        except RelationshipError:
            return {"status": "LIMITED_SCOPE", "reason": "relationship unit identity is missing",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        if pair in seen_pairs or unit_identity in seen_units:
            return {"status": "LIMITED_SCOPE", "reason": "duplicate paired key or non-independent repeated unit detected",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        seen_pairs.add(pair); seen_units.add(unit_identity)
        refs = row.get("source_ids")
        if refs is None:
            refs = [row.get("source_id")] if row.get("source_id") is not None else []
        if (not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs)
                or upstream["source_id"] not in refs or downstream["source_id"] not in refs):
            return {"status": "LIMITED_SCOPE", "reason": "paired evidence does not carry row-level lineage to both approved sources",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        up_value = _path(row, upstream["metric_field"])
        down_value = _path(row, downstream["metric_field"])
        if (isinstance(up_value, bool) or not isinstance(up_value, (int, float)) or not isfinite(up_value)
                or isinstance(down_value, bool) or not isinstance(down_value, (int, float)) or not isfinite(down_value)):
            raise RelationshipError("mapped objective values must be finite numeric measurements")
        mapped_row = {**row, "metrics": {**row["metrics"], upstream["metric"]: float(up_value),
                                           downstream["metric"]: float(down_value)}}
        setting = tuple(row["factors"][name] for name in decision_factors)
        if composition_fields:
            stratum = {}
            for field in composition_fields:
                try:
                    upstream_value = _path(row, field["upstream_field"])
                    downstream_value = _path(row, field["downstream_field"])
                    upstream_identity = _identity_key(upstream_value)
                    downstream_identity = _identity_key(downstream_value)
                except RelationshipError as exc:
                    return {"status": "LIMITED_SCOPE",
                            "reason": f"declared population composition field is missing or invalid: {exc}",
                            "pareto_observation_ids": [], "downstream_claim": "withheld",
                            "population_composition_audit": {"status": "INVALID_OBSERVED_COMPOSITION_VALUE",
                                "field": field["name"]}}
                if upstream_identity != downstream_identity:
                    return {"status": "LIMITED_SCOPE",
                            "reason": "upstream and downstream population composition values disagree",
                            "pareto_observation_ids": [], "downstream_claim": "withheld",
                            "population_composition_audit": {"status": "UPSTREAM_DOWNSTREAM_COMPOSITION_MISMATCH",
                                "field": field["name"]}}
                stratum[field["name"]] = upstream_value
            stratum_key = json.dumps(stratum, sort_keys=True, separators=(",", ":"))
            setting_composition = composition_counts.setdefault(setting, {})
            setting_composition[stratum_key] = setting_composition.get(stratum_key, 0) + 1
            composition_labels[stratum_key] = stratum
        audit = setting_audit.setdefault(setting, {"all_independent_units": 0, "eligible_independent_units": 0,
                                                   "excluded_independent_units": 0})
        audit["all_independent_units"] += 1
        if not all(metric_pass(mapped_row["metrics"][metric], metric_defs[metric])
                   for metric in expected_metrics):
            audit["excluded_independent_units"] += 1
            continue
        audit["eligible_independent_units"] += 1
        groups.setdefault(setting, []).append(mapped_row)

    excluded_units_total = sum(item["excluded_independent_units"] for item in setting_audit.values())
    constraint_audit = {"status": "NO_CONSTRAINT_EXCLUSIONS" if excluded_units_total == 0 else "DESCRIPTIVE_CONSTRAINT_SELECTION",
                        "eligible_population": "whole independent units inside every declared upstream/downstream metric bound",
                        "excluded_independent_units": excluded_units_total,
                        "settings": [{"factors": dict(zip(decision_factors, setting)), **audit}
                                     for setting, audit in setting_audit.items()],
                        "interpretation": "constraint selection can change the compared population; means are limited to eligible independent units"}
    unassessed_settings = [{"id": "SYN-SETTING-" + "-".join(f"{value:g}" for value in setting),
                            "factors": dict(zip(decision_factors, setting)),
                            "eligible_independent_units": audit["eligible_independent_units"],
                            "required_independent_units": minimum_units,
                            "reason": "below independent-unit minimum"}
                           for setting, audit in setting_audit.items()
                           if audit["eligible_independent_units"] < minimum_units]

    composition_profiles = []
    for setting, counts in composition_counts.items():
        total = sum(counts.values())
        composition_profiles.append({
            "id": "SYN-SETTING-" + "-".join(f"{value:g}" for value in setting),
            "factors": dict(zip(decision_factors, setting)),
            "independent_units": total,
            "strata": [{"values": composition_labels[key], "count": count,
                        "proportion": count/total}
                       for key, count in sorted(counts.items())],
        })
    if composition_field_status != "DECLARED":
        composition_status = composition_field_status
    elif len(composition_counts) < 2:
        composition_status = "NOT_ASSESSED_FEWER_THAN_TWO_SETTINGS"
    else:
        setting_items = list(composition_counts.items())
        reference_total = sum(setting_items[0][1].values())
        reference_counts = setting_items[0][1]
        same_proportions = True
        for _, counts in setting_items[1:]:
            total = sum(counts.values())
            for key in set(reference_counts) | set(counts):
                if counts.get(key, 0)*reference_total != reference_counts.get(key, 0)*total:
                    same_proportions = False
                    break
            if not same_proportions:
                break
        composition_status = ("MATCHED_DECLARED_STRATUM_DISTRIBUTIONS" if same_proportions
                              else "MISMATCHED_DECLARED_STRATUM_DISTRIBUTIONS")
    population_composition_audit = {
        "status": composition_status,
        "fields": [{"name": item["name"], "upstream_field": item["upstream_field"],
                    "downstream_field": item["downstream_field"]}
                   for item in composition_fields],
        "settings": composition_profiles,
        "method": "exact comparison of observed categorical stratum proportions before metric-constraint screening",
        "interpretation": "matching declared proportions are descriptive compatibility evidence only; they do not establish exchangeability, random assignment, or a causal effect",
    }

    candidates = []
    uncertainty_limitations = []
    for setting, members in groups.items():
        n = len(members)
        if n < minimum_units:
            continue
        estimates = {}
        for objective in objectives:
            metric = objective["metric"]
            values = [member["metrics"][metric] for member in members]
            avg = mean(values)
            se = sqrt(variance(values)/n) if n > 1 else None
            if se is None or se == 0:
                interval = None
                interval_status = "NOT_ESTIMABLE_ZERO_OBSERVED_VARIANCE"
                limitation = "zero observed variance leaves the marginal Student-t interval unestimable; it does not establish zero population uncertainty"
                if limitation not in uncertainty_limitations:
                    uncertainty_limitations.append(limitation)
            else:
                critical = critical_t_975(n-1)
                interval = [avg-critical*se, avg+critical*se]
                interval_status = "AVAILABLE"
            estimates[metric] = {"mean": avg, "standard_error": se,
                                 "marginal_ci95": interval,
                                 "marginal_ci95_status": interval_status,
                                 "unit_value_min": min(values), "unit_value_max": max(values)}
        up_values = [member["metrics"][upstream["metric"]] for member in members]
        down_values = [member["metrics"][downstream["metric"]] for member in members]
        paired_covariance = sum((a-mean(up_values))*(b-mean(down_values)) for a, b in zip(up_values, down_values))/(n-1) if n > 1 else None
        candidates.append({"id": "SYN-SETTING-" + "-".join(f"{value:g}" for value in setting),
                           "factors": dict(zip(decision_factors, setting)), "independent_units": n,
                           "constraint_eligibility": setting_audit[setting],
                           "means": {metric: value["mean"] for metric, value in estimates.items()},
                           "uncertainty": estimates, "paired_covariance": paired_covariance})
    if not candidates:
        return {"status": "LIMITED_SCOPE", "reason": "no constraint-eligible decision setting met the independent-unit minimum",
                "minimum_independent_units": minimum_units, "pareto_observation_ids": [], "downstream_claim": "withheld",
                "constraint_exclusion_audit": constraint_audit, "unassessed_settings": unassessed_settings,
                "population_composition_audit": population_composition_audit}
    population_composition_compatible = (
        composition_status == "MATCHED_DECLARED_STRATUM_DISTRIBUTIONS")
    if population_composition_compatible:
        front = [candidate for candidate in candidates if not any(
            other is not candidate and _dominates(other, candidate, objectives) for other in candidates)]
        mean_front_ids = [candidate["id"] for candidate in front]
        interval_dominance = _uncertainty_dominance_audit(candidates, objectives, set(mean_front_ids))
    else:
        front, mean_front_ids, interval_dominance = [], [], []
        for candidate in candidates:
            candidate["mean_pareto_status"] = "NOT_COMPARED_POPULATION_COMPOSITION_UNVERIFIED_OR_MISMATCHED"
            candidate["uncertainty_dominance_status"] = "NOT_COMPARED_POPULATION_COMPOSITION_UNVERIFIED_OR_MISMATCHED"
            candidate["interval_separated_dominated_by"] = []
    familywise_envelope, familywise_dominance = _familywise_mean_envelope(
        candidates, objectives, allow=(excluded_units_total == 0 and not unassessed_settings
                                       and population_composition_compatible),
        unavailable_status=("NOT_AVAILABLE_AFTER_OUTCOME_BASED_CONSTRAINT_SELECTION" if excluded_units_total
                            else "NOT_AVAILABLE_POPULATION_COMPOSITION_UNVERIFIED"
                            if composition_status == "NOT_ASSESSED_NO_DECLARED_COMPOSITION_FIELDS"
                            else "NOT_AVAILABLE_INVALID_COMPOSITION_FIELDS"
                            if composition_status == "INVALID_DECLARED_COMPOSITION_FIELDS"
                            else "NOT_AVAILABLE_POPULATION_COMPOSITION_MISMATCH"
                            if composition_status == "MISMATCHED_DECLARED_STRATUM_DISTRIBUTIONS"
                            else "NOT_AVAILABLE_POPULATION_COMPOSITION_UNVERIFIED"
                            if composition_status != "MATCHED_DECLARED_STRATUM_DISTRIBUTIONS"
                            else "NOT_AVAILABLE_INSUFFICIENT_UNITS_FOR_SOME_SETTINGS"),
        bounded_contract=data.get("familywise_mean_bounds"),
        t_precommit=data.get("familywise_t_precommit"),
        metric_units={metric: definition.get("unit") for metric, definition in metric_defs.items()})
    familywise_envelope["population_compatibility"] = composition_status
    comparisons = []
    for left, right in combinations(candidates, 2):
        overlaps, comparison_status = {}, {}
        for metric in expected_metrics:
            left_interval = left["uncertainty"][metric]["marginal_ci95"]
            right_interval = right["uncertainty"][metric]["marginal_ci95"]
            if left_interval is None or right_interval is None:
                overlaps[metric] = None
                comparison_status[metric] = "NOT_ASSESSED_ZERO_OBSERVED_VARIANCE"
            else:
                overlaps[metric] = not (left_interval[0] > right_interval[1]
                                        or right_interval[0] > left_interval[1])
                comparison_status[metric] = "ASSESSED_MARGINAL_95_INTERVAL_OVERLAP_ONLY"
        comparisons.append({"settings": [left["id"], right["id"]],
                            "marginal_intervals_overlap": overlaps,
                            "marginal_interval_status": comparison_status})
    uncertainty_available = not uncertainty_limitations
    warning_parts = []
    if excluded_units_total:
        warning_parts.append("Constraint-eligible paired units only are summarized; compare the per-setting exclusion audit before interpreting population tradeoffs.")
    if unassessed_settings:
        warning_parts.append("Some observed settings were omitted because they did not meet the independent-unit minimum; the Pareto front is incomplete.")
    if not population_composition_compatible:
        warning_parts.append("The cross-setting Pareto front and family-wise comparison are withheld because the declared population-stratum proportions are missing or differ; the shared population ID alone does not establish comparable product/tool/chamber mix.")
    return {"status": "VALID" if excluded_units_total == 0 and uncertainty_available and not unassessed_settings
            and population_composition_compatible else "LIMITED_SCOPE",
            "method": "paired_population_marginal_pareto_with_t_intervals",
            "relationship_id": link["relationship_id"], "relationship_contract_version": link["contract_version"],
            "approval_reference": link["approval_reference"], "population_id": upstream["population_id"],
            "upstream_source_id": upstream["source_id"], "downstream_source_id": downstream["source_id"],
            "objective_metrics": [{**objective, "unit": metric_defs[objective["metric"]].get("unit")}
                                  for objective in objectives],
            "minimum_independent_units": minimum_units,
            "compatible_paired_units": len(seen_units),
            "eligible_paired_units": sum(item["eligible_independent_units"] for item in setting_audit.values()),
            "candidate_settings": candidates,
            "population_composition_audit": population_composition_audit,
            "constraint_exclusion_audit": constraint_audit,
            "selection_warning": " ".join(warning_parts) or None,
            "unassessed_settings": unassessed_settings,
            "pareto_observation_ids": mean_front_ids, "mean_pareto_setting_ids": mean_front_ids,
            "interval_separated_dominance": interval_dominance,
            "familywise_mean_envelope": familywise_envelope,
            "familywise_interval_separated_dominance": familywise_dominance,
            "familywise_nondominated_setting_ids": [candidate["id"] for candidate in candidates
                                                       if candidate["familywise_dominance_status"] == "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR"],
            "pareto_status_scope": ("mean-based observed front; exact declared-stratum proportion matching is required; marginal interval separation is diagnostic only; the separate Bonferroni envelope is assumption-conditional"
                                    if population_composition_compatible else
                                    "cross-setting Pareto comparison withheld; candidate means are descriptive per setting because declared population-stratum proportions are unverified or mismatched"),
            "pareto_values": [{"id": c["id"], "factors": c["factors"], **c["means"]} for c in front],
            "tradeoff_count": len(front), "uncertainty_comparisons": comparisons,
            "uncertainty_available": uncertainty_available,
            "uncertainty_limitations": uncertainty_limitations,
            "multiplicity_adjusted": False, "familywise_multiplicity_adjustment": familywise_envelope["status"],
            "causal_claim": False,
            "scope": "paired approved relationship contract; synthetic observations only",
            "qualification": "mean-based observed Pareto set; constraint screening can change compared populations; marginal intervals are not adjusted; a separate Bonferroni mean envelope is assumption-conditional and does not establish causal effects or engineering approval"}
