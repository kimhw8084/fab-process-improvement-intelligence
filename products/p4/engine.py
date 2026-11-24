"""Deterministic, synthetic-only P4 analysis. No network or actuation path exists."""
from __future__ import annotations

from itertools import combinations, product
from datetime import datetime
from math import isfinite, sqrt
from random import Random
from statistics import mean, variance
from typing import Any

from fabintel.contracts import claim, envelope, validate_envelope
from products.p4.regression import fit_linear_model, critical_t_975, ModelError, RegressionCancelled
from products.p4.window import explore_window, WindowError
from products.p4.tradeoffs import cross_step_tradeoffs, observed_tradeoffs
from products.p4.design import (assign_blocks, propose_design, propose_multiobjective_next_best,
                                propose_window_confirmation, DesignError)

ENGINE_VERSION = "1.2.4"
MAX_ROWS = 5_000
MAX_PARETO_ROWS = 2_000
MAX_FACTORS = 10


class AnalysisCancelled(Exception):
    pass


def _check_cancel(cancel):
    if cancel and cancel():
        raise AnalysisCancelled("analysis cancelled")


def slope(x, y):
    """Ordinary least-squares slope for paired observations."""
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("at least three paired observations required")
    mx, my = mean(x), mean(y)
    ss = sum((v - mx) ** 2 for v in x)
    if ss == 0:
        raise ValueError("factor has no variation")
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / ss


def feasible_observed(rows, lo, hi, minimum):
    """Return only measured settings inside an approved interval."""
    if lo >= hi:
        raise ValueError("invalid domain")
    return sorted({r["factor"] for r in rows if lo <= r["factor"] <= hi and r["response"] >= minimum})


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _declared_dependence_diagnostic(study, records):
    """Detect caller-declared shared groups that invalidate unit-independent t intervals."""
    fields = study.get("shared_dependence_fields", [])
    if not isinstance(fields, list) or any(not isinstance(field, str) or not field.strip() for field in fields):
        return {"status": "INVALID_DECLARATION", "fields": [],
                "reason": "shared_dependence_fields must be a list of nonempty row-field names"}
    if len(set(fields)) != len(fields):
        return {"status": "INVALID_DECLARATION", "fields": fields,
                "reason": "shared_dependence_fields must be unique"}
    if not fields:
        return {"status": "NOT_DECLARED", "fields": [],
                "interpretation": "P4 assumes independent unit_id values; unlisted shared shocks are not detected"}
    values_by_unit = {}
    units_by_field_value = {field: {} for field in fields}
    for row in records:
        unit = row.get("unit_id")
        if not isinstance(unit, str) or not unit.strip():
            return {"status": "INVALID_DECLARATION", "fields": fields,
                    "reason": "dependence fields require nonempty string unit_id values"}
        values_by_unit.setdefault(unit, {})
        for field in fields:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                return {"status": "INCOMPLETE_DECLARATION", "fields": fields,
                        "reason": f"declared dependence field {field} must be present as a nonempty string on every study row"}
            previous = values_by_unit[unit].get(field)
            if previous is not None and previous != value:
                return {"status": "TIME_VARYING_UNIT_GROUP", "fields": fields,
                        "reason": f"declared dependence field {field} changes within independent unit {unit}"}
            values_by_unit[unit][field] = value
            units_by_field_value[field].setdefault(value, set()).add(unit)
    shared = {field: {"shared_group_count": sum(len(units) > 1 for units in groups.values()),
                      "max_independent_units_per_group": max((len(units) for units in groups.values()), default=0)}
              for field, groups in units_by_field_value.items()
              if any(len(units) > 1 for units in groups.values())}
    if shared:
        return {"status": "SHARED_GROUPS_DETECTED", "fields": fields,
                "shared_groups_by_field": shared,
                "interpretation": "declared groups repeat across independent units; unit-level Welch uncertainty is withheld"}
    return {"status": "NO_SHARED_GROUPS_OBSERVED", "fields": fields,
            "interpretation": "no repeats were found in declared fields; this does not establish independence"}


def _validate_declared_independent_unit(rows, data):
    robustness = data.get("robustness", {})
    model = data.get("model", {})
    field = (robustness.get("independent_unit_field") if isinstance(robustness, dict) else None)
    if field is None and isinstance(model, dict):
        field = model.get("independent_unit_field")
    if field is None:
        return
    if not isinstance(field, str) or not field:
        raise ValueError("declared independent-unit field must be a nonempty row field path")
    parts = field.split(".")
    for index, row in enumerate(rows):
        value = row
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise ValueError(f"declared independent-unit field is missing at observation index {index}: {field}")
            value = value[part]
        if value is None or value == "":
            raise ValueError(f"declared independent-unit field is empty at observation index {index}: {field}")


def _normalise(data, cancel=None):
    rows = data.get("observations")
    if not isinstance(rows, list) or not rows:
        raise ValueError("at least one observation is required")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"observation limit is {MAX_ROWS}")
    factors = data.get("factors")
    if not isinstance(factors, list) or not factors:
        # Frozen bootstrap input compatibility: one explicitly named factor.
        if not all("factor" in row for row in rows):
            raise ValueError("factor definitions are required")
        bounds = data.get("bounds")
        factors = [{"name": "factor", "role": "controllable", "unit": "factor unit",
                    "bounds": bounds, "approved": data.get("constraints_approved") is True}]
    if len(factors) > MAX_FACTORS:
        raise ValueError(f"factor limit is {MAX_FACTORS}")
    names = []
    fdefs = {}
    for factor in factors:
        if not isinstance(factor, dict) or not isinstance(factor.get("name"), str) or not factor["name"].strip():
            raise ValueError("each factor needs a name")
        name = factor["name"]
        if factor.get("role", "controllable") not in ("controllable", "measured", "latent_unknown"):
            raise ValueError(f"invalid factor role for {name}")
        if not isinstance(factor.get("unit"), str) or not factor["unit"].strip():
            raise ValueError(f"factor unit is required for {name}")
        if name in fdefs:
            raise ValueError("factor names must be unique")
        names.append(name)
        fdefs[name] = dict(factor)

    metrics = data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        if not all("response" in row for row in rows):
            raise ValueError("metric definitions are required")
        metrics = [{"name": "response", "unit": "response unit", "direction": "maximize",
                    "min": data.get("minimum_response")}]
    mdefs = {}
    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get("name"), str) or not metric["name"].strip():
            raise ValueError("each metric needs a name")
        name = metric["name"]
        if name in mdefs:
            raise ValueError("metric names must be unique")
        if metric.get("direction", "maximize") not in ("maximize", "minimize"):
            raise ValueError(f"invalid objective direction for {name}")
        if not isinstance(metric.get("unit"), str) or not metric["unit"].strip():
            raise ValueError(f"metric unit is required for {name}")
        for key in ("min", "max"):
            if metric.get(key) is not None and not _finite_number(metric[key]):
                raise ValueError(f"metric {key} must be finite")
        if metric.get("min") is not None and metric.get("max") is not None and metric["min"] > metric["max"]:
            raise ValueError(f"metric minimum exceeds maximum for {name}")
        mdefs[name] = dict(metric)

    clean_rows = []
    seen_ids = set()
    for i, row in enumerate(rows):
        _check_cancel(cancel)
        if not isinstance(row, dict):
            raise ValueError(f"observation {i} must be an object")
        fx = row.get("factors")
        if fx is None and len(names) == 1 and "factor" in row:
            fx = {names[0]: row["factor"]}
        if not isinstance(fx, dict) or any(n not in fx or not _finite_number(fx[n]) for n in names):
            raise ValueError(f"observation {i} has missing or non-finite factor values; no imputation or missingness assumption is applied")
        my = row.get("metrics")
        if my is None and len(mdefs) == 1 and "response" in row:
            my = {next(iter(mdefs)): row["response"]}
        if not isinstance(my, dict) or any(n not in my or not _finite_number(my[n]) for n in mdefs):
            missing = [name for name in mdefs if not isinstance(my, dict) or name not in my or not _finite_number(my[name])]
            raise ValueError(f"observation {i} has missing or non-finite metric values for {missing}; no imputation or complete-case missingness assumption is applied")
        row_id = str(row.get("id", f"SYN-ROW-{i + 1:05d}"))
        if not row_id or row_id in seen_ids:
            raise ValueError("observation IDs must be unique nonempty strings")
        seen_ids.add(row_id)
        clean_rows.append({**row, "factors": {n: float(fx[n]) for n in names},
                           "metrics": {n: float(my[n]) for n in mdefs}, "id": row_id})
    return fdefs, mdefs, clean_rows


def _approved_bounds(fdef):
    bounds = fdef.get("bounds")
    if (fdef.get("approved") is not True or not isinstance(bounds, (tuple, list)) or len(bounds) != 2
            or not all(_finite_number(v) for v in bounds) or bounds[0] >= bounds[1]):
        return None
    return [float(bounds[0]), float(bounds[1])]


def _solve(matrix, rhs, tol=1e-11):
    """Pivoted Gauss-Jordan solve. Returns None for rank-deficient systems."""
    n = len(rhs)
    a = [list(map(float, matrix[i])) + [float(rhs[i])] for i in range(n)]
    column_scales = [max((abs(a[r][c]) for r in range(n)), default=0.0) for c in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) <= tol * max(1.0, column_scales[col]):
            return None
        a[col], a[pivot] = a[pivot], a[col]
        div = a[col][col]
        a[col] = [v / div for v in a[col]]
        for r in range(n):
            if r == col:
                continue
            mult = a[r][col]
            if mult:
                a[r] = [x - mult * y for x, y in zip(a[r], a[col])]
    return [a[i][-1] for i in range(n)]


def _inverse(matrix):
    n = len(matrix)
    cols = []
    for j in range(n):
        rhs = [1.0 if i == j else 0.0 for i in range(n)]
        col = _solve(matrix, rhs)
        if col is None:
            return None
        cols.append(col)
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def _critical95(df):
    # Two-sided Student t quantiles (95%), with a normal limit for large df.
    table = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
             2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
             2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052,
             2.048, 2.045, 2.042]
    return table[df - 1] if 1 <= df <= len(table) else 1.96


def _design(rows, factor_names, include_interactions=False, include_quadratic=False):
    labels = ["intercept"] + factor_names
    columns = [[1.0 for _ in rows]]
    for name in factor_names:
        vals = [r["factors"][name] for r in rows]
        center = mean(vals)
        columns.append([v - center for v in vals])
    if include_interactions:
        for a, b in combinations(factor_names, 2):
            av, bv = mean(r["factors"][a] for r in rows), mean(r["factors"][b] for r in rows)
            columns.append([(r["factors"][a] - av) * (r["factors"][b] - bv) for r in rows])
            labels.append(f"{a}:{b}")
    if include_quadratic:
        for name in factor_names:
            vals = [r["factors"][name] for r in rows]
            center = mean(vals)
            columns.append([(v - center) ** 2 for v in vals])
            labels.append(f"{name}^2")
    return labels, [[col[i] for col in columns] for i in range(len(rows))]


def _fit_ols(rows, factor_names, metric, options, factor_defs, cancel=None):
    report, _model = fit_linear_model(rows, factor_defs, metric, options, cancel=cancel)
    return report


def _metric_pass(value, definition):
    if definition.get("min") is not None and value < definition["min"]:
        return False
    if definition.get("max") is not None and value > definition["max"]:
        return False
    return True


def _inside_forbidden(row, forbidden):
    for region in forbidden:
        if not isinstance(region, dict):
            raise ValueError("forbidden regions must be factor-to-range maps")
        if not region:
            raise ValueError("forbidden regions cannot be empty")
        matches = True
        for name, val in region.items():
            if name not in row["factors"]:
                raise ValueError(f"unknown factor in forbidden region: {name}")
            bound = val if isinstance(val, (list, tuple)) and len(val) == 2 else [val, val]
            if not all(_finite_number(v) for v in bound) or bound[0] > bound[1]:
                raise ValueError("forbidden-region bounds must be finite and ordered")
            matches = matches and bound[0] <= row["factors"][name] <= bound[1]
        if matches:
            return True
    return False


def _process_window(rows, fdefs, mdefs, data, cancel=None):
    constrained_metrics = {name: definition for name, definition in mdefs.items()
                           if definition.get("min") is not None or definition.get("max") is not None}
    if not constrained_metrics:
        return {"status": "REFUSED", "reason": "at least one explicit metric specification bound is required",
                "candidate_observation_ids": [], "candidate_count": 0}
    approved = {}
    observed_covariate_ranges = {}
    for name, definition in fdefs.items():
        if definition.get("role", "controllable") == "controllable":
            approved[name] = _approved_bounds(definition)
        else:
            values = [row["factors"][name] for row in rows]
            observed_covariate_ranges[name] = [min(values), max(values)]
    missing = [name for name, bounds in approved.items() if bounds is None]
    if not approved or missing or data.get("constraints_approved") is not True:
        return {"status": "REFUSED", "reason": "approved factor ranges and constraints are required",
                "missing_factor_approvals": missing, "candidate_rows": []}
    forbidden = data.get("forbidden_regions", [])
    if not isinstance(forbidden, list):
        raise ValueError("forbidden_regions must be a list")
    candidates = []
    for row in rows:
        _check_cancel(cancel)
        in_domain = all(approved[n][0] <= row["factors"][n] <= approved[n][1] for n in approved)
        passes = all(_metric_pass(row["metrics"][n], definition) for n, definition in constrained_metrics.items())
        if in_domain and passes and not _inside_forbidden(row, forbidden):
            candidates.append(row)
    boundaries = {name: [min(r["factors"][name] for r in candidates), max(r["factors"][name] for r in candidates)]
                  for name in fdefs} if candidates else {}
    return {"status": "VALID" if candidates else "INCONCLUSIVE", "method": "observed_feasible_filter",
            "candidate_observation_ids": [r["id"] for r in candidates], "candidate_count": len(candidates),
            "candidate_factor_values": {name: sorted({r["factors"][name] for r in candidates}) for name in fdefs},
            "observed_factor_boundaries": boundaries, "approved_factor_bounds": approved,
            "observed_covariate_ranges": observed_covariate_ranges,
            "excluded_forbidden_or_out_of_domain": len(rows) - len(candidates),
            "extrapolation": "none; unobserved settings are not candidates",
            "qualification": "observed candidates only; not a validated production window"}


def _robust_window(rows, fdefs, mdefs, data, feasible):
    spec = data.get("robustness", {})
    if not isinstance(spec, dict):
        raise ValueError("robustness must be an object")
    minimum = spec.get("min_independent_units")
    unit_field = spec.get("independent_unit_field")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2 or not isinstance(unit_field, str) or not unit_field:
        return {"status": "NOT_ESTIMATED", "reason": "explicit minimum independent units and unit ID field are required",
                "robust_observed_settings": [], "qualification": "no robustness claim"}
    constrained_metrics = {name: definition for name, definition in mdefs.items()
                           if definition.get("min") is not None or definition.get("max") is not None}
    if not constrained_metrics:
        return {"status": "NOT_ESTIMATED", "reason": "at least one metric needs an explicit specification bound",
                "robust_observed_settings": [], "qualification": "no robustness claim"}
    if feasible.get("status") != "VALID":
        return {"status": "INCONCLUSIVE", "reason": "no observed feasible rows", "robust_observed_settings": []}
    candidate_ids = set(feasible["candidate_observation_ids"])
    candidates = [row for row in rows if row["id"] in candidate_ids]
    groups = {}
    factor_names = list(fdefs)
    for row in candidates:
        unit = row.get(unit_field)
        if unit is None or str(unit) == "":
            continue
        key = tuple(row["factors"][name] for name in factor_names)
        groups.setdefault(key, []).append(row)
    robust = []
    for key, members in groups.items():
        units = {str(row[unit_field]) for row in members}
        worst_case_pass = all(_metric_pass(row["metrics"][metric], definition)
                              for row in members for metric, definition in constrained_metrics.items())
        if len(units) >= minimum and worst_case_pass:
            robust.append({"factors": dict(zip(factor_names, key)), "independent_units": len(units),
                           "observation_count": len(members), "observed_worst_case": {
                               metric: (min(r["metrics"][metric] for r in members) if definition.get("direction", "maximize") == "maximize"
                                        else max(r["metrics"][metric] for r in members))
                               for metric, definition in constrained_metrics.items()}})
    return {"status": "VALID" if robust else "INCONCLUSIVE", "method": "worst_observed_replicate_filter",
            "minimum_independent_units": minimum, "independent_unit_field": unit_field,
            "robust_observed_settings": robust, "count": len(robust),
            "qualification": "only replicated observed settings passing every stated limit; not production-qualified"}


def _pareto(rows, mdefs, fdefs, data, cancel=None):
    objectives = data.get("objectives")
    if objectives is None:
        objectives = [{"metric": n, "direction": d.get("direction", "maximize")} for n, d in mdefs.items()]
    if not isinstance(objectives, list) or not objectives:
        return {"status": "LIMITED_SCOPE", "reason": "no objective metrics supplied", "pareto_observation_ids": []}
    if any(not isinstance(obj, dict) for obj in objectives):
        raise ValueError("each objective must be an object")
    for obj in objectives:
        if obj.get("metric") not in mdefs or obj.get("direction", "maximize") not in ("maximize", "minimize"):
            raise ValueError("objectives must reference defined metrics and valid directions")
    if len({obj["metric"] for obj in objectives}) != len(objectives):
        raise ValueError("objective metrics must be unique")
    multi = data.get("multi_step") is True
    if len(rows) > MAX_PARETO_ROWS:
        return {"status": "REFUSED", "reason": f"multiobjective comparison is bounded to {MAX_PARETO_ROWS} eligible observations",
                "pareto_observation_ids": []}
    if multi:
        return cross_step_tradeoffs(rows, mdefs, data, cancel)
    if len(objectives) < 2 and not multi:
        return {"status": "NOT_REQUESTED", "reason": "multiple objectives were not supplied", "pareto_observation_ids": []}
    return observed_tradeoffs(rows, mdefs, fdefs, data, objectives, cancel)


def _power_assumption(design, runs, controls):
    sd, delta = design.get("noise_sd"), design.get("minimum_detectable_effect")
    if not (_finite_number(sd) and sd > 0 and _finite_number(delta) and delta > 0):
        return {"status": "NOT_SPECIFIED", "required_inputs": ["noise_sd", "minimum_detectable_effect"],
                "claim": "no power guarantee"}
    # Normal-approximation, two-sided 5% alpha, 80% power, two balanced arms.
    per_arm = int((2 * ((1.96 + 0.84) * sd / delta) ** 2) + 0.999999)
    level_counts = {}
    for name in controls:
        counts = {}
        for run in runs:
            key = run[name]
            counts[key] = counts.get(key, 0) + 1
        level_counts[name] = counts
    balanced = all(len(counts) == 2 and len(set(counts.values())) == 1 for counts in level_counts.values())
    available = min(next(iter(level_counts.values())).values()) if balanced and level_counts else None
    return {"status": "APPROXIMATE", "method": "balanced two-level main-effect normal approximation",
            "alpha": 0.05, "power": 0.80, "minimum_detectable_effect": delta,
            "noise_sd_assumption": sd, "required_independent_units_per_arm": per_arm,
            "balanced_level_counts": level_counts,
            "available_independent_units_per_level": available,
            "run_budget_adequate_for_reference_contrast": bool(balanced and available >= per_arm),
            "qualification": "planning approximation for a balanced two-level contrast; not a power guarantee for the full factorial; engineer/statistician review required"}


def _mean_difference_interval(treated, control):
    estimate = mean(treated) - mean(control)
    a = variance(treated) / len(treated)
    b = variance(control) / len(control)
    se = sqrt(a + b)
    denominator = (a * a / (len(treated) - 1)) + (b * b / (len(control) - 1))
    df = (a + b) ** 2 / denominator if denominator else 1000
    tcrit = critical_t_975(max(1.0, df))
    return estimate, se, df, [estimate - tcrit * se, estimate + tcrit * se]


def _randomization_cluster_means(study, records, ledger, metric, fields, attrition):
    """Build equal-cluster outcome means only for a fully declared cluster-randomized design."""
    field = study.get("randomization_cluster_field")
    if not isinstance(field, str) or not field.strip() or field not in fields:
        return None, "randomization_cluster_field must name one of shared_dependence_fields"
    if any(attrition[group]["missing_outcome"] for group in attrition):
        return None, "cluster-randomized inference requires a complete outcome for every assigned unit"
    units = {}
    for item in ledger:
        groups = item.get("shared_groups")
        cluster = groups.get(field) if isinstance(groups, dict) else None
        if not isinstance(cluster, str) or not cluster.strip():
            return None, "every assignment-ledger unit must declare its randomization cluster in shared_groups"
        units[item["unit_id"]] = {"group": item["group"], "cluster": cluster}
    observed_ids = {row.get("unit_id") for row in records}
    if observed_ids != set(units):
        return None, "cluster-randomized analysis requires complete assignment and outcome records"
    clusters = {}
    for item in units.values():
        cluster = item["cluster"]
        existing = clusters.setdefault(cluster, {"group": item["group"], "members": []})
        if existing["group"] != item["group"]:
            return None, "a declared randomization cluster contains both treatment and control assignments"
    for row in records:
        unit = units[row["unit_id"]]
        if row.get(field) != unit["cluster"]:
            return None, "observation cluster values do not match the assignment ledger"
        clusters[unit["cluster"]]["members"].append(row)
    for dependence_field in fields:
        value_clusters = {}
        for row in records:
            value_clusters.setdefault(row[dependence_field], set()).add(units[row["unit_id"]]["cluster"])
        if any(len(cluster_ids) > 1 for cluster_ids in value_clusters.values()):
            return None, f"declared dependence field {dependence_field} spans multiple randomization clusters; cluster-level independence is unsupported"
    grouped = {"treatment": [], "control": []}
    for cluster in clusters.values():
        members = cluster["members"]
        outcomes = [float(row[metric]) for row in members if _finite_number(row.get(metric))]
        if len(outcomes) != len(members) or not members:
            return None, "every randomization cluster must have complete, finite outcomes"
        grouped[cluster["group"]].append({"outcome_mean": mean(outcomes), "members": members})
    if min(len(grouped["treatment"]), len(grouped["control"])) < 5:
        return None, "at least five independent randomization clusters per arm are required for this qualified Welch approximation"
    return grouped, None


def _qualify_experiment_proposal(plan, strategy, spec, data, fdefs, bounds, metric_defs):
    """Attach the engineering objective and decision context to every DOE plan."""
    if not isinstance(plan, dict) or plan.get("status") != "PROPOSED":
        return plan

    statement = spec.get("objective_statement") or data.get("objective")
    if not isinstance(statement, str) or not statement.strip():
        return {**plan, "status": "REFUSED", "reason": "an engineering objective statement is required",
                "run_count": 0, "runs": [], "executed": False, "actuation": "none"}

    metric_names = []
    if strategy == "next_best_multiobjective":
        for item in data.get("objectives", []):
            if isinstance(item, dict) and item.get("metric") in metric_defs:
                metric_names.append(item["metric"])
    elif strategy in ("next_best", "confirm_window_candidate"):
        target = spec.get("target_metric")
        if isinstance(target, str) and target in metric_defs:
            metric_names.append(target)
        for name in spec.get("constraint_metrics", []):
            if isinstance(name, str) and name in metric_defs and name not in metric_names:
                metric_names.append(name)
    else:
        for objective in data.get("objectives", []):
            if isinstance(objective, dict) and objective.get("metric") in metric_defs:
                if objective["metric"] not in metric_names:
                    metric_names.append(objective["metric"])
        if not metric_names:
            primary = data.get("primary_metric")
            if isinstance(primary, str) and primary in metric_defs:
                metric_names.append(primary)
            else:
                metric_names.extend(name for name in metric_defs if name not in metric_names)

    supplied_objectives = {item.get("metric"): item for item in data.get("objectives", [])
                           if isinstance(item, dict) and isinstance(item.get("metric"), str)}
    metrics = []
    for name in metric_names:
        definition = metric_defs[name]
        objective = supplied_objectives.get(name, {})
        metrics.append({"metric": name, "unit": definition.get("unit"),
                        "direction": objective.get("direction", definition.get("direction", "characterize")),
                        "min": definition.get("min"), "max": definition.get("max")})
    source = "experiment_design.objective_statement" if spec.get("objective_statement") else "investigation.objective"
    existing_objective = plan.get("objective")
    objective = dict(existing_objective) if isinstance(existing_objective, dict) else {}
    objective.update({"source": source, "metrics": metrics,
                      "selection_policy": ("separate objectives; no scalar weighting or tradeoff preference is inferred"
                                           if len(metrics) > 1 else "no process setting is automatically selected")})

    factor_definitions = [{"name": name, "unit": fdefs[name].get("unit", "unspecified"),
                           "approved_bounds": list(bounds[name]), "role": fdefs[name].get("role", "controllable")}
                          for name in plan.get("factors", []) if name in fdefs and name in bounds]
    if isinstance(plan.get("run_options"), list):
        information = {"status": "OBJECTIVE_SPECIFIC_MODEL_ADVISORY",
                       "alternatives": [{"metric": item["objective_metric"],
                                         "unit": item["objective_unit"],
                                         "expected_improvement": item["expected_improvement"]}
                                        for item in plan["run_options"]],
                       "qualification": "objective-specific expected improvements have different units; no joint probability or combined value is estimated"}
    elif "expected_improvement" in plan:
        information = {"status": "MODEL_BASED_ADVISORY", "method": plan.get("acquisition"),
                       "value": plan.get("expected_improvement"),
                       "qualification": "depends on the supplied response model, grouped validation, support screen, and stated assumptions; not a guarantee"}
    elif isinstance(plan.get("power"), dict):
        information = {"status": plan["power"].get("status", "APPROXIMATE"),
                       "method": plan["power"].get("method"), "diagnostic": plan["power"],
                       "qualification": plan["power"].get("qualification", "assumption-conditional planning diagnostic; not a power guarantee for the complete design")}
    else:
        information = {"status": "NOT_ESTIMATED", "value": None,
                       "reason": "the supplied design specification does not support a power or response-information estimate"}

    if isinstance(plan.get("run_options"), list):
        uncertainty = {"status": "SEPARATE_OBJECTIVE_MODELS",
                       "alternatives": [{"metric": item["objective_metric"],
                                         "prediction": item["prediction"],
                                         "constraint_evaluation": item.get("constraint_evaluation", {}),
                                         "constraint_predictions": item.get("constraint_predictions", {}),
                                         "grouped_validation": item["grouped_surface_validation"],
                                         "support": item["support"]}
                                        for item in plan["run_options"]],
                       "qualification": "each alternative has its own grouped holdout and support screen; competing metric responses at each setting are not predicted here"}
    elif isinstance(plan.get("prediction"), dict):
        uncertainty = {"status": plan["prediction"].get("status", "MODEL_ESTIMATE"),
                      "prediction": plan["prediction"],
                      "grouped_validation": plan.get("grouped_surface_validation"),
                      "qualification": "model-based uncertainty is conditional on development/evaluation populations and supplied model assumptions"}
    else:
        uncertainty = {"status": "NOT_ESTIMATED_FOR_NEW_RUNS",
                       "reason": "design geometry alone cannot establish outcome uncertainty before runs are executed"}

    review = list(plan.get("required_engineer_review", []))
    review.extend(["confirm the engineering objective, metric direction and constraints",
                   "verify each factor unit and approved bound against the authorized process window",
                   "review design assumptions, randomization, blocking, run budget and operational feasibility"])
    if isinstance(plan.get("run_options"), list):
        review.append("review competing objective outcomes at each proposed setting and select at most one alternative; this slate does not predict those competing outcomes")
    evidence = list(plan.get("evidence_required_before_next_iteration", []))
    evidence.extend(["record assigned and executed run order, block, replicate, deviations and failed runs",
                     "retain measurements at the declared observation grain with metric units and measurement method",
                     "record the population (product, tool, chamber, lot and time), exclusions, missing outcomes and source/version hashes"])
    plan.update({"objective": objective, "objective_statement": statement.strip(), "objective_source": source,
                 "factor_definitions": factor_definitions, "information_value": information,
                 "pre_execution_uncertainty": uncertainty,
                 "required_engineer_review": list(dict.fromkeys(review)),
                 "evidence_required_before_next_iteration": list(dict.fromkeys(evidence)),
                 "qualification": plan.get("qualification", "non-executing advisory design; engineer review required")})
    return plan


def _experiment_design(fdefs, data, rows=None, mdefs=None, process_window=None, cancel=None):
    spec = data.get("experiment_design")
    if not spec:
        return {"status": "NOT_REQUESTED", "executed": False}
    if not isinstance(spec, dict):
        raise ValueError("experiment_design must be an object")
    if data.get("constraints_approved") is not True:
        return {"status": "REFUSED", "reason": "approved constraints are required", "executed": False}
    controls = [n for n, f in fdefs.items() if f.get("role", "controllable") == "controllable"]
    bounds = {n: _approved_bounds(fdefs[n]) for n in controls}
    if not controls or any(v is None for v in bounds.values()):
        return {"status": "REFUSED", "reason": "approved DOE bounds for controllable factors are required", "executed": False}
    budget = spec.get("run_budget")
    replicates = spec.get("replicates", 1)
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1 or not isinstance(replicates, int) or replicates < 1:
        return {"status": "REFUSED", "reason": "positive integer run_budget and replicates are required", "executed": False}
    strategy = spec.get("strategy", "full_factorial")
    if strategy == "confirm_window_candidate":
        plan = propose_window_confirmation(process_window, controls, bounds, spec,
                                           data.get("forbidden_regions", []), mdefs or {}, cancel)
        return _qualify_experiment_proposal(plan, strategy, spec, data, fdefs, bounds, mdefs or {})
    if strategy == "next_best_multiobjective":
        try:
            plan = propose_multiobjective_next_best(
                controls, bounds, spec, data.get("forbidden_regions", []), rows or [],
                data.get("objectives"), mdefs or {}, data.get("model", {}), cancel)
        except DesignError as exc:
            plan = {"status": "REFUSED", "design": "objective-specific sequential experiment alternatives",
                    "strategy": strategy, "reason": str(exc), "run_count": 0, "runs": [],
                    "run_options": [], "alternative_count": 0, "executed": False, "actuation": "none"}
        return _qualify_experiment_proposal(plan, strategy, spec, data, fdefs, bounds, mdefs or {})
    if strategy != "full_factorial":
        plan = propose_design(strategy, controls, bounds, spec, data.get("forbidden_regions", []),
                              rows=rows, metric_defs=mdefs, model_options=data.get("model", {}), cancel=cancel)
        return _qualify_experiment_proposal(plan, strategy, spec, data, fdefs, bounds, mdefs or {})
    forbidden = data.get("forbidden_regions", [])
    corners = list(product(*[(bounds[n][0], bounds[n][1]) for n in controls]))
    if len(corners) > 1024:
        return {"status": "REFUSED", "reason": "factorial design exceeds 1024 candidate combinations", "executed": False}
    candidates = []
    for corner in corners:
        _check_cancel(cancel)
        factors = dict(zip(controls, corner))
        pseudo = {"factors": factors}
        if not _inside_forbidden(pseudo, forbidden):
            candidates.append(factors)
    planned = len(candidates) * replicates
    if planned > 10_000:
        return {"status": "REFUSED", "reason": "design output is bounded to 10000 runs", "executed": False}
    if not candidates:
        return {"status": "REFUSED", "reason": "constraints exclude every factorial candidate", "executed": False}
    if planned > budget:
        return {"status": "REFUSED", "reason": f"full factorial requires {planned} runs, exceeding budget {budget}",
                "required_runs": planned, "executed": False}
    runs = [dict(factors, replicate=r + 1) for r in range(replicates) for factors in candidates]
    seed = spec.get("seed", 20261122)
    if not isinstance(seed, int) or isinstance(seed, bool):
        return {"status": "REFUSED", "reason": "seed must be an integer", "executed": False}
    Random(seed).shuffle(runs)
    block_count = spec.get("blocks", 1)
    if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 1 or block_count > len(runs):
        return {"status": "REFUSED", "reason": "blocks must be a positive integer", "executed": False}
    blocking = assign_blocks(runs, controls, block_count, seed, cancel=cancel)
    power = _power_assumption(spec, runs, controls)
    plan = {"status": "PROPOSED", "design": "randomized full factorial at approved bounds",
            "factors": controls, "run_count": len(runs), "runs": runs,
            "randomization_seed": seed, "blocking": blocking,
            "power": power, "authorization_fields": ["engineer_approval_id", "process_owner_approval_id", "safety_review_id"],
            "executed": False, "actuation": "none"}
    return _qualify_experiment_proposal(plan, strategy, spec, data, fdefs, bounds, mdefs or {})


def _effectiveness(data, metric_defs=None):
    study = data.get("effectiveness")
    if not study:
        return {"status": "NOT_REQUESTED", "causal_claim": False}
    if not isinstance(study, dict) or study.get("authorized") is not True:
        return {"status": "INCONCLUSIVE", "reason": "documented authorized intervention is required", "causal_claim": False}
    records = study.get("observations", [])
    metric = study.get("metric")
    if not isinstance(records, list) or len(records) > MAX_ROWS or not records or not isinstance(metric, str) or not metric:
        return {"status": "INCONCLUSIVE", "reason": "effect metric and study observations are required", "causal_claim": False}
    if any(not isinstance(row, dict) for row in records):
        return {"status": "INCONCLUSIVE", "reason": "study observations must be objects", "causal_claim": False}
    design = study.get("design")
    dependence_diagnostic = (_declared_dependence_diagnostic(study, records)
                             if design in ("randomized", "difference_in_differences") else None)
    if dependence_diagnostic and dependence_diagnostic.get("status") in (
            "INVALID_DECLARATION", "INCOMPLETE_DECLARATION", "TIME_VARYING_UNIT_GROUP"):
        return {"status": "INCONCLUSIVE", "reason": dependence_diagnostic["reason"],
                "dependence_diagnostic": dependence_diagnostic, "causal_claim": False}
    metric_definition = metric_defs.get(metric, {}) if isinstance(metric_defs, dict) else {}
    contract_unit = (metric_definition.get("unit") if isinstance(metric_definition, dict)
                     else None)
    study_unit = study.get("metric_unit")
    if (contract_unit and study_unit and contract_unit != study_unit
            and design == "difference_in_differences"):
        return {"status": "INCONCLUSIVE", "reason": "effect metric unit conflicts with the investigation metric contract", "causal_claim": False}
    metric_unit = contract_unit or study_unit
    if design == "randomized":
        if (study.get("randomized") is not True or not str(study.get("intervention_id", "")).startswith("SYN-") or
                not str(study.get("authorization_id", "")).startswith("SYN-") or
                not str(study.get("randomization_evidence", "")).startswith("SYN-")):
            return {"status": "INCONCLUSIVE", "reason": "random allocation evidence, authorization ID, and documented intervention ID are required", "causal_claim": False}
        if any(r.get("group") not in ("treatment", "control") for r in records):
            return {"status": "INCONCLUSIVE", "reason": "every randomized unit needs a valid assigned group", "causal_claim": False}
        ledger = study.get("assignment_ledger")
        if not isinstance(ledger, list) or not ledger or any(not isinstance(item, dict) for item in ledger):
            return {"status": "INCONCLUSIVE", "reason": "randomized study requires an assignment_ledger to establish denominators and detect missing units", "causal_claim": False}
        ledger_ids = [item.get("unit_id") for item in ledger]
        if (any(not isinstance(unit, str) or not unit.strip() for unit in ledger_ids) or len(set(ledger_ids)) != len(ledger_ids)
                or any(item.get("group") not in ("treatment", "control") for item in ledger)):
            return {"status": "INCONCLUSIVE", "reason": "assignment_ledger requires unique nonempty string unit IDs and valid randomized groups", "causal_claim": False}
        observed_ids = [r.get("unit_id") for r in records]
        if any(not isinstance(unit, str) or not unit.strip() for unit in observed_ids) or len(set(observed_ids)) != len(observed_ids):
            return {"status": "INCONCLUSIVE", "reason": "randomized analysis requires one record per unique assigned independent unit", "causal_claim": False}
        ledger_groups = {item["unit_id"]: item["group"] for item in ledger}
        if any(row["unit_id"] not in ledger_groups or ledger_groups[row["unit_id"]] != row["group"] for row in records):
            return {"status": "INCONCLUSIVE", "reason": "study observations do not match the randomized assignment ledger", "causal_claim": False}
        declared_fields = study.get("shared_dependence_fields", [])
        if declared_fields and set(observed_ids) != set(ledger_ids):
            ledger_dependence_rows = []
            for item in ledger:
                groups = item.get("shared_groups")
                if (not isinstance(groups, dict)
                        or any(not isinstance(groups.get(field), str) or not groups[field].strip()
                               for field in declared_fields)):
                    return {"status": "INCONCLUSIVE",
                            "reason": "randomized assignment_ledger must provide shared_groups for every declared dependence field when outcome attrition is present",
                            "dependence_diagnostic": {"status": "INCOMPLETE_ASSIGNMENT_DEPENDENCE_LEDGER",
                                                      "fields": declared_fields},
                            "causal_claim": False}
                ledger_dependence_rows.append({"unit_id": item["unit_id"],
                                               **{field: groups[field] for field in declared_fields}})
            dependence_diagnostic = _declared_dependence_diagnostic(
                study, records + ledger_dependence_rows)
            if dependence_diagnostic.get("status") in (
                    "INVALID_DECLARATION", "INCOMPLETE_DECLARATION", "TIME_VARYING_UNIT_GROUP"):
                return {"status": "INCONCLUSIVE", "reason": dependence_diagnostic["reason"],
                        "dependence_diagnostic": dependence_diagnostic, "causal_claim": False}
        observed_by_id = {row["unit_id"]: row for row in records}
        complete_records = [observed_by_id.get(item["unit_id"], {"unit_id": item["unit_id"], "group": item["group"]})
                           for item in ledger]
        assigned = {group: [r for r in complete_records if r["group"] == group] for group in ("treatment", "control")}
        observed = {group: [float(r[metric]) for r in units_for_group if _finite_number(r.get(metric))]
                    for group, units_for_group in assigned.items()}
        attrition = {group: {"assigned": len(assigned[group]), "observed": len(observed[group]),
                             "missing_outcome": len(assigned[group])-len(observed[group]),
                             "rate": (len(assigned[group])-len(observed[group]))/len(assigned[group]) if assigned[group] else None}
                    for group in assigned}
        cluster_randomization = None
        if (dependence_diagnostic.get("status") == "SHARED_GROUPS_DETECTED"
                or study.get("randomization_cluster_field") is not None):
            cluster_randomization, cluster_error = _randomization_cluster_means(
                study, records, ledger, metric, declared_fields, attrition)
            if cluster_error:
                complete_outcomes = not any(attrition[group]["missing_outcome"] for group in attrition)
                descriptive_difference = (mean(observed["treatment"]) - mean(observed["control"])
                                          if complete_outcomes and observed["treatment"] and observed["control"] else None)
                return {"status": "INCONCLUSIVE", "design": design, "metric": metric,
                        "descriptive_observed_difference": descriptive_difference,
                        "estimate_scope": "unadjusted observed-arm contrast only; no inferential interval or causal effect is reported",
                        "uncertainty_status": "WITHHELD_SHARED_GROUP_DEPENDENCE",
                        "dependence_diagnostic": dependence_diagnostic, "attrition": attrition,
                        "reason": cluster_error if study.get("randomization_cluster_field") else
                                  "declared dependence groups span assigned units; identify the randomization unit and provide a qualified cluster-aware analysis with adequate independent groups",
                        "causal_claim": False}
        cointerventions = {group: {str(row.get("concurrent_intervention_id", "none")) for row in members}
                           for group, members in assigned.items()}
        if study.get("differential_concurrent_intervention") is True or cointerventions["treatment"] != cointerventions["control"]:
            return {"status": "INCONCLUSIVE", "reason": "concurrent intervention differs by randomized arm",
                    "attrition": attrition, "causal_claim": False}
        if any(attrition[group]["missing_outcome"] for group in attrition):
            bounds = study.get("outcome_bounds")
            if (not isinstance(bounds, list) or len(bounds) != 2 or any(not _finite_number(v) for v in bounds)
                    or bounds[0] > bounds[1]):
                return {"status": "INCONCLUSIVE", "reason": "outcome attrition requires engineer-supplied finite outcome_bounds; point estimate withheld",
                        "attrition": attrition, "causal_claim": False}
            if any(value < bounds[0] or value > bounds[1]
                   for values in observed.values() for value in values):
                return {"status": "INCONCLUSIVE", "reason": "an observed outcome falls outside supplied outcome_bounds; worst-case attrition bounds are invalid",
                        "attrition": attrition, "outcome_bounds": bounds, "causal_claim": False}
            arm_bounds = {}
            for group in assigned:
                if not assigned[group]:
                    return {"status": "INCONCLUSIVE", "reason": "both randomized arms need assigned units", "attrition": attrition, "causal_claim": False}
                missing = attrition[group]["missing_outcome"]
                observed_sum = sum(observed[group])
                arm_bounds[group] = [(observed_sum+missing*bounds[0])/len(assigned[group]),
                                     (observed_sum+missing*bounds[1])/len(assigned[group])]
            return {"status": "BOUNDED", "design": "randomized intention-to-treat worst-case attrition bounds",
                    "metric": metric, "attrition": attrition, "outcome_bounds": bounds,
                    "treatment_mean_bounds": arm_bounds["treatment"], "control_mean_bounds": arm_bounds["control"],
                    "effect_identification_bounds": [arm_bounds["treatment"][0]-arm_bounds["control"][1],
                                                      arm_bounds["treatment"][1]-arm_bounds["control"][0]],
                    "causal_claim": False,
                    "qualification": "worst-case bounds only; no point effect or causal certainty is claimed"}
        treated, control = observed["treatment"], observed["control"]
        if cluster_randomization is not None:
            treated = [item["outcome_mean"] for item in cluster_randomization["treatment"]]
            control = [item["outcome_mean"] for item in cluster_randomization["control"]]
        minimum_clusters = min(len(treated), len(control))
        if minimum_clusters < 2:
            return {"status": "INCONCLUSIVE", "reason": "at least two independent analysis units per randomized arm are required", "attrition": attrition, "causal_claim": False}
        estimate, se, df, interval = _mean_difference_interval(treated, control)
        baseline = {}
        baseline_fields = study.get("baseline_covariates", [])
        if baseline_fields and (not isinstance(baseline_fields, list) or any(not isinstance(field, str) for field in baseline_fields)):
            return {"status": "INCONCLUSIVE", "reason": "baseline_covariates must be a list of field names", "causal_claim": False}
        for field in baseline_fields:
            if any(not _finite_number(row.get(field)) for row in records):
                baseline[field] = {"status": "NOT_AVAILABLE"}
                continue
            if cluster_randomization is None:
                values = {group: [float(row[field]) for row in assigned[group]] for group in assigned}
            else:
                values = {group: [mean([float(row[field]) for row in item["members"]])
                                  for item in cluster_randomization[group]] for group in assigned}
            pool_var = ((len(values["treatment"])-1)*variance(values["treatment"])
                        +(len(values["control"])-1)*variance(values["control"]))/(len(values["treatment"])+len(values["control"])-2)
            smd = (mean(values["treatment"])-mean(values["control"]))/sqrt(pool_var) if pool_var > 0 else None
            baseline[field] = {"standardized_mean_difference": smd,
                               "imbalance_flag_abs_smd_over_0_1": abs(smd) > 0.1 if smd is not None else None}
        return {"status": "ESTIMATED", "design": "randomized two-arm difference in means", "metric": metric,
                "intervention_id": study["intervention_id"], "treatment_n": len(assigned["treatment"]), "control_n": len(assigned["control"]),
                "estimate": estimate, "se": se, "welch_df": df, "ci95_welch_t_approximation": interval,
                "inference_unit": "declared_randomization_cluster" if cluster_randomization is not None else "assigned_independent_unit",
                "inference_method": ("Welch t interval over equally weighted declared randomization-cluster means"
                                     if cluster_randomization is not None else
                                     "Welch t interval over assigned independent-unit outcomes"),
                "inference_unit_counts": {group: len(cluster_randomization[group]) for group in cluster_randomization}
                    if cluster_randomization is not None else {"treatment": len(treated), "control": len(control)},
                "attrition": attrition, "baseline_balance": baseline,
                "dependence_diagnostic": dependence_diagnostic,
                "causal_claim": True, "assumptions": (["valid documented random allocation to the declared clusters",
                                                        "independent clusters; undeclared shared shocks are not detected",
                                                        "equal weight per randomization cluster defines the estimand",
                                                        "cluster-mean Welch approximation requires approximately normal independent clusters; five clusters per arm is not a universal guarantee",
                                                        "no interference across clusters", "complete, consistently measured outcomes"]
                                                       if cluster_randomization is not None else
                                                       ["valid documented random allocation", "independent units; P4 does not detect undeclared shared shocks", "no interference", "consistent outcome measurement"]),
                "diagnostics": {"small_sample_warning": minimum_clusters < 10,
                                "assignment_unit_count": len(ledger_ids),
                                "randomization_cluster_field": study.get("randomization_cluster_field") if cluster_randomization is not None else None,
                                "dependence_status": dependence_diagnostic.get("status"),
                                "concurrent_intervention_ids": {group: sorted(values) for group, values in cointerventions.items()}},
                "sensitivity": {"type": "outcome_attrition", "missing_outcomes": 0,
                                "qualification": "report outcome_bounds to compute worst-case attrition bounds if missingness is present"},
                "qualification": "conditional randomized study estimate; small samples and baseline imbalance require review; not production qualification"}
    if design == "difference_in_differences":
        if (not str(study.get("authorization_id", "")).startswith("SYN-") or
                not str(study.get("intervention_id", "")).startswith("SYN-")):
            return {"status": "INCONCLUSIVE", "reason": "documented authorized intervention is required", "causal_claim": False}
        negative_control = study.get("negative_control_outcome")
        negative_control_metric = None
        if negative_control is not None:
            if (not isinstance(negative_control, dict)
                    or not isinstance(negative_control.get("metric"), str)
                    or not negative_control["metric"].strip()
                    or negative_control["metric"] == metric
                    or not _finite_number(negative_control.get("equivalence_bound"))
                    or negative_control["equivalence_bound"] < 0
                    or not isinstance(negative_control.get("bound_unit"), str)
                    or not negative_control["bound_unit"].strip()
                    or not isinstance(negative_control.get("bound_source"), str)
                    or not negative_control["bound_source"].strip()
                    or not isinstance(negative_control.get("bound_method"), str)
                    or not negative_control["bound_method"].strip()):
                return {"status": "INCONCLUSIVE", "reason": "negative_control_outcome requires a distinct metric and documented nonnegative equivalence bound, source, and method", "causal_claim": False}
            negative_control_metric = negative_control["metric"]
            negative_control_definition = (metric_defs.get(negative_control_metric, {})
                                           if isinstance(metric_defs, dict) else {})
            negative_control_unit = ((negative_control_definition.get("unit")
                                      if isinstance(negative_control_definition, dict) else None)
                                     or negative_control.get("metric_unit"))
            if (not isinstance(negative_control_unit, str) or not negative_control_unit.strip()
                    or negative_control["bound_unit"] != negative_control_unit):
                return {"status": "INCONCLUSIVE", "reason": "negative-control equivalence bound unit must exactly match its declared metric unit", "causal_claim": False}
        population_fields = study.get("population_fields", [])
        if (not isinstance(population_fields, list)
                or any(not isinstance(field, str) or not field.strip() for field in population_fields)):
            return {"status": "INCONCLUSIVE", "reason": "population_fields must be a unique list of nonempty categorical source fields", "causal_claim": False}
        if len(set(population_fields)) != len(population_fields):
            return {"status": "INCONCLUSIVE", "reason": "population_fields must be a unique list of nonempty categorical source fields", "causal_claim": False}
        if any(row.get("group") not in ("treatment", "control") or row.get("period") not in ("pre3", "pre2", "pre", "post") for row in records):
            return {"status": "INCONCLUSIVE", "reason": "DiD requires group and ordered periods pre3, pre2, pre, and/or post", "causal_claim": False}
        raw_intervention_time = study.get("intervention_time")
        try:
            intervention_time = datetime.fromisoformat(str(raw_intervention_time).replace("Z", "+00:00"))
            if intervention_time.tzinfo is None or intervention_time.utcoffset() is None:
                raise ValueError("timezone missing")
        except (TypeError, ValueError):
            return {"status": "INCONCLUSIVE",
                    "reason": "DiD requires a timezone-aware intervention_time and source timestamps for every period",
                    "timing_diagnostic": {"status": "MISSING_OR_INVALID_INTERVENTION_TIME"}, "causal_claim": False}
        period_order = {"pre3": 0, "pre2": 1, "pre": 2, "post": 3}
        timestamps_by_unit = {}
        timing_counts = {"pre_intervention": 0, "post_intervention": 0}
        for row in records:
            try:
                timestamp = datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError("timezone missing")
            except (TypeError, ValueError):
                return {"status": "INCONCLUSIVE", "reason": "DiD requires timezone-aware source timestamps for every period",
                        "timing_diagnostic": {"status": "INCOMPLETE_OR_INVALID_SOURCE_TIMESTAMPS",
                                              "unit_id": row.get("unit_id"), "period": row.get("period")},
                        "causal_claim": False}
            is_post = row["period"] == "post"
            if (is_post and timestamp < intervention_time) or (not is_post and timestamp >= intervention_time):
                return {"status": "INCONCLUSIVE", "reason": "DiD period labels conflict with the documented intervention cutoff",
                        "timing_diagnostic": {"status": "PERIOD_CUTOFF_CONFLICT", "unit_id": row.get("unit_id"),
                                              "period": row["period"], "timestamp": timestamp.isoformat(),
                                              "intervention_time": intervention_time.isoformat()},
                        "causal_claim": False}
            timing_counts["post_intervention" if is_post else "pre_intervention"] += 1
            timestamps_by_unit.setdefault(row.get("unit_id"), []).append((period_order[row["period"]], timestamp, row["period"]))
        for unit_id, period_timestamps in timestamps_by_unit.items():
            ordered = sorted(period_timestamps)
            if any(left[1] >= right[1] for left, right in zip(ordered, ordered[1:])):
                return {"status": "INCONCLUSIVE", "reason": "DiD measurements must follow the declared period order within each unit",
                        "timing_diagnostic": {"status": "PERIOD_ORDER_CONFLICT", "unit_id": unit_id,
                                              "periods": [item[2] for item in ordered],
                                              "timestamps": [item[1].isoformat() for item in ordered]},
                        "causal_claim": False}
        timing_diagnostic = {"status": "ALIGNED_TO_DECLARED_CUTOFF", "intervention_time": intervention_time.isoformat(),
                             "timestamped_observations": len(records), **timing_counts,
                             "within_unit_period_order": "STRICTLY_INCREASING",
                             "qualification": "Source labels and timestamps were compared; P4 cannot authenticate intervention occurrence, clock provenance, or timestamp semantics."}
        ledger = study.get("assignment_ledger")
        if not isinstance(ledger, list) or not ledger or any(not isinstance(item, dict) for item in ledger):
            return {"status": "INCONCLUSIVE", "reason": "DiD requires an assignment ledger to establish the independent-unit denominator", "causal_claim": False}
        ledger_ids = [item.get("unit_id") for item in ledger]
        if (any(not isinstance(unit, str) or not unit.strip() for unit in ledger_ids) or len(set(ledger_ids)) != len(ledger_ids)
                or any(item.get("group") not in ("treatment", "control") for item in ledger)):
            return {"status": "INCONCLUSIVE", "reason": "DiD assignment ledger requires unique nonempty string unit IDs and valid groups", "causal_claim": False}
        ledger_groups = {item["unit_id"]: item["group"] for item in ledger}
        if set(ledger_groups.values()) != {"treatment", "control"}:
            return {"status": "INCONCLUSIVE", "reason": "DiD assignment ledger must include both groups", "causal_claim": False}
        by_unit = {unit: {"group": group} for unit, group in ledger_groups.items()}
        for row in records:
            unit = row.get("unit_id")
            if not isinstance(unit, str) or not unit.strip():
                return {"status": "INCONCLUSIVE", "reason": "DiD requires independent unit IDs", "causal_claim": False}
            if unit not in ledger_groups or ledger_groups[unit] != row["group"]:
                return {"status": "INCONCLUSIVE", "reason": "DiD observations do not match the assignment ledger", "causal_claim": False}
            entry = by_unit[unit]
            if entry["group"] != row["group"] or row["period"] in entry:
                return {"status": "INCONCLUSIVE", "reason": "DiD assignments and period records must be unique", "causal_claim": False}
            entry[row["period"]] = float(row[metric]) if _finite_number(row.get(metric)) else None
            intervention_id = row.get("concurrent_intervention_id")
            entry[f"concurrent_intervention_{row['period']}"] = (
                intervention_id.strip() if isinstance(intervention_id, str) and intervention_id.strip() else None)
            if population_fields:
                entry.setdefault("population_context", {})[row["period"]] = {
                    field: row.get(field) for field in population_fields}
            if negative_control_metric:
                entry[f"negative_control_{row['period']}"] = (float(row[negative_control_metric])
                                                                 if _finite_number(row.get(negative_control_metric)) else None)
        attrition = {group: {"assigned": 0, "complete_pre_post": 0, "complete_pretrend": 0,
                             "complete_pretrend_stability": 0}
                    for group in ("treatment", "control")}
        changes = {group: [] for group in ("treatment", "control")}
        for unit, val in by_unit.items():
            group = val["group"]
            attrition[group]["assigned"] += 1
            if _finite_number(val.get("pre")) and _finite_number(val.get("post")):
                changes[group].append(val["post"] - val["pre"])
                attrition[group]["complete_pre_post"] += 1
            if _finite_number(val.get("pre2")) and _finite_number(val.get("pre")):
                attrition[group]["complete_pretrend"] += 1
            if all(_finite_number(val.get(period)) for period in ("pre3", "pre2", "pre")):
                attrition[group]["complete_pretrend_stability"] += 1
        t, c = changes["treatment"], changes["control"]
        if len(t) < 2 or len(c) < 2:
            return {"status": "INCONCLUSIVE", "reason": "DiD requires two complete independent units per group", "attrition": attrition, "causal_claim": False}
        if any(attrition[group]["complete_pre_post"] != attrition[group]["assigned"] for group in attrition):
            return {"status": "INCONCLUSIVE", "reason": "incomplete DiD outcome panels are not imputed; causal and point estimates withheld",
                    "attrition": attrition, "causal_claim": False}
        if dependence_diagnostic.get("status") == "SHARED_GROUPS_DETECTED":
            return {"status": "INCONCLUSIVE", "design": design, "metric": metric, "metric_unit": metric_unit,
                    "descriptive_did_estimate": mean(t) - mean(c),
                    "estimate_scope": "unadjusted difference in unit-level changes only; no inferential interval or causal effect is reported",
                    "uncertainty_status": "WITHHELD_SHARED_GROUP_DEPENDENCE",
                    "dependence_diagnostic": dependence_diagnostic, "attrition": attrition,
                    "reason": "declared dependence groups span independent units; provide a qualified cluster-aware DiD design and adequate independent-group diagnostics",
                    "secondary_diagnostics_status": "NOT_EVALUATED_AFTER_DEPENDENCE_REFUSAL",
                    "causal_claim": False}
        estimate, se, df, interval = _mean_difference_interval(t, c)
        population_compatibility = {"status": "NOT_PROVIDED",
                                    "reason": "declare population_fields to audit product/tool mix stability and treatment-control composition"}
        if population_fields:
            category_counts = {group: {field: {} for field in population_fields}
                               for group in ("treatment", "control")}
            incomplete_population_units = []
            shifted_population_units = []
            population_values = {group: {field: [] for field in population_fields}
                                 for group in ("treatment", "control")}
            for unit, val in by_unit.items():
                contexts = val.get("population_context", {})
                group = val["group"]
                unit_missing = False
                unit_shifted = False
                for field in population_fields:
                    period_values = []
                    for period in ("pre2", "pre", "post"):
                        if period not in contexts or field not in contexts[period]:
                            continue
                        value = contexts[period][field]
                        if (not isinstance(value, (str, int, float, bool)) or value is None
                                or (isinstance(value, float) and not isfinite(value))):
                            unit_missing = True
                            continue
                        period_values.append((period, value))
                    pre_value = contexts.get("pre", {}).get(field)
                    if pre_value is None:
                        unit_missing = True
                    else:
                        population_values[group][field].append(pre_value)
                    if len({(type(value).__name__, repr(value)) for _, value in period_values}) > 1:
                        unit_shifted = True
                if unit_missing:
                    incomplete_population_units.append(unit)
                if unit_shifted:
                    shifted_population_units.append(unit)
            group_composition_mismatch = False
            for group in ("treatment", "control"):
                for field in population_fields:
                    counts = {}
                    for value in population_values[group][field]:
                        key = f"{type(value).__name__}:{value!r}"
                        counts[key] = counts.get(key, 0) + 1
                    category_counts[group][field] = counts
            for field in population_fields:
                if category_counts["treatment"][field] != category_counts["control"][field]:
                    group_composition_mismatch = True
            population_status = ("INCOMPLETE_COVERAGE" if incomplete_population_units else
                                 "WITHIN_UNIT_POPULATION_SHIFT" if shifted_population_units else
                                 "TREATMENT_CONTROL_COMPOSITION_MISMATCH" if group_composition_mismatch else
                                 "MATCHED_DECLARED_CATEGORICAL_COMPOSITION")
            population_compatibility = {
                "status": population_status, "fields": population_fields,
                "preperiod_unit_counts": category_counts,
                "incomplete_unit_count": len(incomplete_population_units),
                "incomplete_unit_ids": sorted(incomplete_population_units),
                "within_unit_shift_count": len(shifted_population_units),
                "within_unit_shift_ids": sorted(shifted_population_units),
                "interpretation": "exact declared categorical composition checks are descriptive; matching does not establish exchangeability or eliminate unmeasured confounding"}
        pretrend = {"status": "NOT_ESTIMABLE", "reason": "at least two pre-intervention periods are required"}
        trend_t, trend_c = [], []
        for val in by_unit.values():
            if _finite_number(val.get("pre2")) and _finite_number(val.get("pre")):
                delta = val["pre"]-val["pre2"]
                (trend_t if val["group"] == "treatment" else trend_c).append(delta)
        if len(trend_t) >= 2 and len(trend_c) >= 2:
            trend_estimate, trend_se, trend_df, trend_interval = _mean_difference_interval(trend_t, trend_c)
            equivalence_bound = study.get("pretrend_equivalence_bound")
            equivalence_source = study.get("pretrend_equivalence_bound_source")
            equivalence_method = study.get("pretrend_equivalence_bound_method")
            equivalence_unit = study.get("pretrend_equivalence_bound_unit")
            complete_pretrend = all(attrition[group]["complete_pretrend"] == attrition[group]["assigned"]
                                    for group in attrition)
            documented_equivalence_bound = (_finite_number(equivalence_bound) and equivalence_bound >= 0
                                            and isinstance(equivalence_source, str) and bool(equivalence_source.strip())
                                            and isinstance(equivalence_method, str) and bool(equivalence_method.strip())
                                            and isinstance(metric_unit, str) and bool(metric_unit.strip())
                                            and equivalence_unit == metric_unit)
            within_bound = (documented_equivalence_bound and trend_interval[0] >= -equivalence_bound
                            and trend_interval[1] <= equivalence_bound)
            trend_status = ("INCOMPLETE_COVERAGE" if not complete_pretrend else
                            "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF" if within_bound else
                            "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND" if documented_equivalence_bound else
                            "EQUIVALENCE_BOUND_NOT_DOCUMENTED")
            pretrend = {"status": trend_status, "estimate": trend_estimate, "se": trend_se,
                        "welch_df": trend_df, "ci95": trend_interval,
                        "equivalence_bound": equivalence_bound,
                        "equivalence_bound_source": equivalence_source,
                        "equivalence_bound_method": equivalence_method,
                        "equivalence_bound_unit": equivalence_unit,
                        "complete_coverage": complete_pretrend,
                        "complete_units": {"treatment": len(trend_t), "control": len(trend_c)}}
        stability_placebo = {"status": "NOT_PROVIDED",
                             "reason": "a third pre-intervention period was not supplied; two-period trend checks cannot assess pretrend curvature"}
        has_third_preperiod = any("pre3" in val for val in by_unit.values())
        if has_third_preperiod:
            curvature = {group: [] for group in ("treatment", "control")}
            for val in by_unit.values():
                if all(_finite_number(val.get(period)) for period in ("pre3", "pre2", "pre")):
                    early_change = val["pre2"] - val["pre3"]
                    recent_change = val["pre"] - val["pre2"]
                    curvature[val["group"]].append(recent_change - early_change)
            complete_stability = all(
                attrition[group]["complete_pretrend_stability"] == attrition[group]["assigned"]
                for group in attrition)
            if not complete_stability:
                stability_placebo = {"status": "INCOMPLETE_COVERAGE", "metric": metric,
                                     "complete_units": {group: len(curvature[group]) for group in curvature},
                                     "complete_coverage": False}
            elif len(curvature["treatment"]) < 2 or len(curvature["control"]) < 2:
                stability_placebo = {"status": "NOT_ESTIMABLE", "metric": metric,
                                     "complete_units": {group: len(curvature[group]) for group in curvature},
                                     "complete_coverage": True}
            else:
                stability_estimate, stability_se, stability_df, stability_interval = _mean_difference_interval(
                    curvature["treatment"], curvature["control"])
                equivalence_bound = study.get("pretrend_equivalence_bound")
                equivalence_source = study.get("pretrend_equivalence_bound_source")
                equivalence_method = study.get("pretrend_equivalence_bound_method")
                equivalence_unit = study.get("pretrend_equivalence_bound_unit")
                documented_bound = (_finite_number(equivalence_bound) and equivalence_bound >= 0
                                    and isinstance(equivalence_source, str) and bool(equivalence_source.strip())
                                    and isinstance(equivalence_method, str) and bool(equivalence_method.strip())
                                    and isinstance(metric_unit, str) and bool(metric_unit.strip())
                                    and equivalence_unit == metric_unit)
                within_bound = (documented_bound and stability_interval[0] >= -equivalence_bound
                                and stability_interval[1] <= equivalence_bound)
                stability_status = ("INCOMPLETE_COVERAGE" if not complete_stability else
                                    "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF" if within_bound else
                                    "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND" if documented_bound else
                                    "EQUIVALENCE_BOUND_NOT_DOCUMENTED")
                stability_placebo = {"status": stability_status, "metric": metric,
                                     "estimate": stability_estimate, "se": stability_se,
                                     "welch_df": stability_df, "ci95": stability_interval,
                                     "equivalence_bound": equivalence_bound,
                                     "equivalence_bound_source": equivalence_source,
                                     "equivalence_bound_method": equivalence_method,
                                     "equivalence_bound_unit": equivalence_unit,
                                     "complete_coverage": complete_stability,
                                     "complete_units": {group: len(curvature[group]) for group in curvature},
                                     "interpretation": "difference between adjacent pre-intervention slope changes is a placebo falsification diagnostic, not proof of parallel trends"}
        negative_control_diagnostic = {"status": "NOT_PROVIDED"}
        if negative_control_metric:
            nc_changes = {group: [] for group in ("treatment", "control")}
            nc_complete = {group: 0 for group in nc_changes}
            for val in by_unit.values():
                pre_value = val.get("negative_control_pre")
                post_value = val.get("negative_control_post")
                if _finite_number(pre_value) and _finite_number(post_value):
                    nc_changes[val["group"]].append(post_value-pre_value)
                    nc_complete[val["group"]] += 1
            complete_nc_panel = all(nc_complete[group] == attrition[group]["assigned"] for group in nc_complete)
            if len(nc_changes["treatment"]) < 2 or len(nc_changes["control"]) < 2:
                negative_control_diagnostic = {"status": "NOT_ESTIMABLE", "metric": negative_control_metric,
                                               "complete_units": nc_complete,
                                               "assigned_units": {group: attrition[group]["assigned"] for group in attrition}}
            else:
                nc_estimate, nc_se, nc_df, nc_interval = _mean_difference_interval(
                    nc_changes["treatment"], nc_changes["control"])
                nc_bound = float(negative_control["equivalence_bound"])
                within_nc_bound = complete_nc_panel and nc_interval[0] >= -nc_bound and nc_interval[1] <= nc_bound
                negative_control_diagnostic = {
                    "status": ("WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF" if within_nc_bound else
                               "INCOMPLETE_COVERAGE" if not complete_nc_panel else
                               "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND"),
                    "metric": negative_control_metric, "did_estimate": nc_estimate, "se": nc_se,
                    "welch_df": nc_df, "ci95": nc_interval,
                    "equivalence_bound": nc_bound,
                    "equivalence_bound_unit": negative_control["bound_unit"],
                    "bound_source": negative_control["bound_source"],
                    "bound_method": negative_control["bound_method"],
                    "complete_units": nc_complete,
                    "assigned_units": {group: attrition[group]["assigned"] for group in attrition},
                    "qualification": "negative-control equivalence is only a falsification diagnostic; it cannot establish absence of unmeasured confounding"}
        trend_bound = study.get("differential_trend_bound")
        trend_bound_source = study.get("differential_trend_bound_source")
        trend_bound_method = study.get("differential_trend_bound_method")
        trend_bound_unit = study.get("differential_trend_bound_unit")
        documented_sensitivity_bound = (_finite_number(trend_bound) and trend_bound >= 0
                                        and isinstance(trend_bound_source, str) and bool(trend_bound_source.strip())
                                        and isinstance(trend_bound_method, str) and bool(trend_bound_method.strip())
                                        and isinstance(metric_unit, str) and bool(metric_unit.strip())
                                        and trend_bound_unit == metric_unit)
        sensitivity = ({"differential_trend_bound": trend_bound,
                        "bound_source": trend_bound_source, "bound_method": trend_bound_method,
                        "bound_unit": trend_bound_unit,
                        "effect_range_under_bound": [estimate-trend_bound, estimate+trend_bound],
                        "ci95_under_bound": [interval[0]-trend_bound, interval[1]+trend_bound],
                        "point_estimate_tipping_point_abs_trend": abs(estimate),
                        "ci95_tipping_point_abs_trend": (0.0 if interval[0] <= 0 <= interval[1]
                            else min(abs(interval[0]), abs(interval[1]))),
                        "robust_to_declared_bound": (interval[0]-trend_bound > 0 or interval[1]+trend_bound < 0),
                        "bound_authentication": "NOT_VERIFIABLE_BY_P4",
                        "interpretation": "Welch interval expanded by the declared absolute differential-trend bias bound; valid only if the bound is externally justified for this metric, unit, population, and post period. P4 cannot authenticate the source or establish the bound is adequate."}
                       if documented_sensitivity_bound else
                       {"reason": "supply a nonnegative differential_trend_bound with its source, method, and a unit exactly matching the declared outcome metric unit for quantitative sensitivity"})
        minimum_units_for_conditional_interpretation = 10
        adequate_sample = min(len(t), len(c)) >= minimum_units_for_conditional_interpretation
        concurrent_intervention_ids = {group: sorted({row["concurrent_intervention_id"].strip()
                                               for row in records if row.get("group") == group
                                               and isinstance(row.get("concurrent_intervention_id"), str)
                                               and row["concurrent_intervention_id"].strip()})
                                       for group in ("treatment", "control")}
        observed_periods = [period for period in ("pre3", "pre2", "pre", "post")
                            if any(row.get("period") == period for row in records)]
        period_intervention_counts = {group: {period: {} for period in observed_periods}
                                      for group in ("treatment", "control")}
        transition_counts = {group: {} for group in ("treatment", "control")}
        unreported_intervention_units = {group: {period: 0 for period in observed_periods}
                                         for group in ("treatment", "control")}
        for value in by_unit.values():
            group = value["group"]
            for period in observed_periods:
                label = value.get(f"concurrent_intervention_{period}")
                if label is None:
                    label = "UNREPORTED"
                    unreported_intervention_units[group][period] += 1
                counts = period_intervention_counts[group][period]
                counts[label] = counts.get(label, 0) + 1
            for before, after in zip(observed_periods, observed_periods[1:]):
                transition = (value.get(f"concurrent_intervention_{before}") or "UNREPORTED",
                              value.get(f"concurrent_intervention_{after}") or "UNREPORTED")
                transition_key = f"{before} -> {after}"
                transition_counts[group].setdefault(transition_key, {})
                counts = transition_counts[group][transition_key]
                label = f"{transition[0]} -> {transition[1]}"
                counts[label] = counts.get(label, 0) + 1

        def proportions_differ(left, right):
            left_total, right_total = sum(left.values()), sum(right.values())
            if not left_total or not right_total:
                return left_total != right_total
            return any(left.get(category, 0)*right_total != right.get(category, 0)*left_total
                       for category in set(left) | set(right))

        mismatched_periods = [period for period in observed_periods
                             if proportions_differ(period_intervention_counts["treatment"][period],
                                                   period_intervention_counts["control"][period])]
        transition_mismatches = [transition for transition in transition_counts["treatment"]
                                 if proportions_differ(transition_counts["treatment"][transition],
                                                       transition_counts["control"].get(transition, {}))]
        transition_mismatch = bool(transition_mismatches)
        incomplete_intervention_history = any(
            count for group_counts in unreported_intervention_units.values()
            for count in group_counts.values())
        differential_concurrent_intervention = (
            study.get("differential_concurrent_intervention") is True
            or bool(mismatched_periods) or transition_mismatch or incomplete_intervention_history)
        concurrent_intervention_diagnostic = {
            "status": ("INCOMPLETE_DECLARED_INTERVENTION_HISTORY" if incomplete_intervention_history
                       and not (mismatched_periods or transition_mismatch or study.get("differential_concurrent_intervention") is True)
                       else "DIFFERENTIAL_OR_INCOMPLETE_DECLARED_MIX" if differential_concurrent_intervention
                       else "MATCHED_DECLARED_PERIOD_AND_TRANSITION_PROPORTIONS"),
            "periods_with_different_group_proportions": mismatched_periods,
            "transitions_with_different_group_proportions": transition_mismatches,
            "transition_proportions_differ": transition_mismatch,
            "periods_with_unreported_intervention_ids": unreported_intervention_units,
            "period_category_counts": period_intervention_counts,
            "adjacent_period_transition_counts": transition_counts,
            "interpretation": "declared intervention-label proportions are compared by arm across every observed period and adjacent transition; missing labels or differing declared distributions withhold the numerical assumption gate. Labels do not authenticate source semantics or rule out unmeasured confounding"}
        sensitivity_interval = sensitivity.get("ci95_under_bound")
        direction_supported = (sensitivity_interval is not None
                               and (sensitivity_interval[0] > 0 or sensitivity_interval[1] < 0))
        negative_control_supported = (negative_control_diagnostic.get("status") in (
            "NOT_PROVIDED", "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF"))
        stability_placebo_supported = stability_placebo.get("status") in (
            "NOT_PROVIDED", "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF")
        population_compatible = population_compatibility.get("status") == "MATCHED_DECLARED_CATEGORICAL_COMPOSITION"
        assumption_gates_passed = (pretrend.get("status") == "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF"
                        and documented_sensitivity_bound and adequate_sample
                        and not differential_concurrent_intervention and direction_supported
                        and negative_control_supported and stability_placebo_supported and population_compatible)
        # The available adapter validates data semantics and source hashes, not
        # the substantive adequacy of an engineering-supplied confounding bound.
        # Keep the diagnostic gate visible, but do not promote it to eligibility.
        bound_source_qualification = "NOT_ESTABLISHED_BY_AVAILABLE_ADAPTER"
        conditional_eligible = False
        return {"status": "ESTIMATED", "design": design, "metric": metric, "metric_unit": metric_unit,
                "treatment_n": len(t), "control_n": len(c),
                "estimate": estimate, "se": se, "welch_df": df, "ci95_welch_t_approximation": interval,
                "causal_claim": False,
                "conditional_assumptions_passed": assumption_gates_passed,
                "conditional_interpretation_eligible": conditional_eligible,
                "conditional_interpretation_scope": ("PENDING_BOUND_SOURCE_QUALIFICATION"
                    if assumption_gates_passed else "WITHHELD"),
                "bound_source_qualification": bound_source_qualification,
                "causal_claim_limitation": "P4 reports observational DiD as a descriptive estimate with sensitivity diagnostics. The available adapter cannot substantively qualify the supplied bound against independent engineering evidence, so P4 neither marks a conditional interpretation eligible nor emits an observational DiD causal claim",
                "attrition": attrition, "pretrend_diagnostic": pretrend,
                "intervention_timing_diagnostic": timing_diagnostic,
                "placebo_pretrend": {**pretrend, "interpretation": "pre-intervention treatment-control trend contrast is a placebo diagnostic, not proof of parallel trends"},
                "pretrend_stability_placebo": stability_placebo,
                "population_compatibility": population_compatibility,
                "negative_control_diagnostic": negative_control_diagnostic,
                "dependence_diagnostic": dependence_diagnostic,
                "concurrent_intervention_diagnostic": concurrent_intervention_diagnostic,
                "sensitivity": sensitivity, "assumptions": ["parallel trends cannot be proven by pretrend data",
                    "no differential concurrent intervention", "independent units; P4 does not detect undeclared shared shocks", "consistent outcome measurement",
                    *( ["three complete preperiods were supplied; adjacent-slope stability is only a falsification diagnostic"] if has_third_preperiod else []),
                    *(["negative-control metric is truly unaffected by treatment and measured comparably"] if negative_control_metric else [])],
                "diagnostics": {"small_sample_warning": min(len(t), len(c)) < 10,
                                "minimum_units_for_conditional_interpretation": minimum_units_for_conditional_interpretation,
                                "pretrend_coverage_complete": pretrend.get("complete_coverage", False),
                                "pretrend_stability_placebo_status": stability_placebo.get("status"),
                                "population_compatibility_status": population_compatibility.get("status"),
                                "placebo_pretrend_status": pretrend.get("status"),
                                "negative_control_status": negative_control_diagnostic.get("status"),
                                "intervention_timing_status": timing_diagnostic["status"],
                                "differential_concurrent_intervention": differential_concurrent_intervention,
                                "concurrent_intervention_ids": {group: sorted(values) for group, values in concurrent_intervention_ids.items()},
                                "effect_direction_supported_under_trend_bound": direction_supported,
                                "pretrend_stability_supported": stability_placebo_supported,
                                "declared_population_mix_compatible": population_compatible,
                                "conditional_assumption_gates_passed": assumption_gates_passed,
                                "bound_source_qualification": bound_source_qualification},
                "reason": ("DiD point estimate is descriptive; numerical checks passed but bound-source qualification is unavailable"
                           if assumption_gates_passed else
                           "DiD point estimate is descriptive; conditional interpretation withheld because design diagnostics or sensitivity bound are incomplete"),
                "qualification": "conditional study estimate; parallel-trends sensitivity and engineer review required"}
    vals = [r.get(metric) for r in records if _finite_number(r.get(metric))]
    before = [r[metric] for r in records if r.get("period") == "pre" and _finite_number(r.get(metric))]
    after = [r[metric] for r in records if r.get("period") == "post" and _finite_number(r.get(metric))]
    return {"status": "INCONCLUSIVE", "descriptive_before_after": mean(after) - mean(before) if before and after else None,
            "observed_count": len(vals), "reason": "no supported causal design; any before/after difference is descriptive only",
            "causal_claim": False}


def _validate_time_split(validation, rows=None, factor_defs=None, metric_defs=None,
                         model_options=None, primary_metric=None, cancel=None):
    if not isinstance(validation, dict) or validation.get("split_type") != "time":
        return {"status": "NOT_PROVIDED", "generalization_claim": "withheld"}
    train, test = validation.get("train_timestamps"), validation.get("test_timestamps")
    if not isinstance(train, list) or not train or not isinstance(test, list) or not test:
        return {"status": "INCONCLUSIVE", "reason": "time split needs nonempty train and test timestamps"}
    try:
        train_dt = [datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in train]
        test_dt = [datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in test]
        if any(v.tzinfo is None for v in train_dt + test_dt):
            raise ValueError("timezone missing")
    except ValueError:
        return {"status": "INCONCLUSIVE", "reason": "split timestamps must be timezone-aware ISO-8601 values"}
    if max(train_dt) >= min(test_dt):
        return {"status": "REFUSED", "reason": "temporal leakage: training timestamps overlap or follow holdout"}
    raw_train_groups, raw_test_groups = validation.get("train_groups"), validation.get("test_groups")
    if (not isinstance(raw_train_groups, list) or not raw_train_groups
            or not isinstance(raw_test_groups, list) or not raw_test_groups
            or any(not isinstance(value, str) or not value for value in raw_train_groups + raw_test_groups)):
        return {"status": "INCONCLUSIVE", "reason": "group-separated holdout IDs are required"}
    train_groups, test_groups = set(raw_train_groups), set(raw_test_groups)
    if train_groups.intersection(test_groups):
        return {"status": "INCONCLUSIVE", "reason": "group leakage: holdout groups overlap training groups"}
    timestamp_field = validation.get("timestamp_field")
    group_field = validation.get("group_field")
    metric = validation.get("metric", primary_metric)
    split_reference = validation.get("split_reference")
    if (not isinstance(timestamp_field, str) or not timestamp_field
            or not isinstance(group_field, str) or not group_field
            or not isinstance(metric, str) or not metric
            or metric not in (metric_defs or {})
            or not isinstance(split_reference, str) or not split_reference.strip()):
        return {"status": "DECLARATION_ONLY",
                "reason": "chronology/group declarations were checked, but actual out-of-time evaluation requires timestamp_field, group_field, metric, and a split_reference",
                "train_end": max(train_dt).isoformat(), "test_start": min(test_dt).isoformat(),
                "group_disjoint": True, "generalization_claim": "withheld; no observations were evaluated"}
    if not isinstance(rows, list) or not isinstance(factor_defs, dict):
        return {"status": "INCONCLUSIVE", "reason": "actual observations and factor definitions are required for time-holdout evaluation"}
    train_start, train_end = min(train_dt), max(train_dt)
    test_start, test_end = min(test_dt), max(test_dt)
    train_rows, test_rows = [], []
    try:
        for row in rows:
            _check_cancel(cancel)
            group = row
            for part in group_field.split("."):
                group = group[part]
            raw_time = row
            for part in timestamp_field.split("."):
                raw_time = raw_time[part]
            timestamp = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("row timestamp is missing timezone")
            if str(group) in train_groups and train_start <= timestamp <= train_end:
                train_rows.append(row)
            if str(group) in test_groups and test_start <= timestamp <= test_end:
                test_rows.append(row)
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "INCONCLUSIVE", "reason": f"actual holdout row has an invalid group or timestamp: {exc}"}
    # The row-level membership check below is the authority; config-only IDs do
    # not count as observed independent groups.
    observed_train_groups = set()
    observed_test_groups = set()
    for row in train_rows:
        value = row
        for part in group_field.split("."):
            value = value[part]
        observed_train_groups.add(str(value))
    for row in test_rows:
        value = row
        for part in group_field.split("."):
            value = value[part]
        observed_test_groups.add(str(value))
    if not train_rows or not test_rows:
        return {"status": "INCONCLUSIVE", "reason": "declared train/test groups and time windows must match actual observations",
                "training_row_count": len(train_rows), "test_row_count": len(test_rows),
                "declared_train_groups": len(train_groups), "declared_test_groups": len(test_groups)}
    if observed_train_groups.intersection(observed_test_groups):
        return {"status": "REFUSED", "reason": "an independent group appears in both actual train and test rows"}
    if metric not in (metric_defs or {}):
        return {"status": "INCONCLUSIVE", "reason": "time-holdout metric is not defined"}
    fit_options = dict(model_options or {})
    fit_options.setdefault("independent_unit_field", group_field)
    try:
        training_report, model = fit_linear_model(train_rows, factor_defs, metric, fit_options, cancel=cancel)
    except ModelError as exc:
        return {"status": "INCONCLUSIVE", "reason": f"training partition cannot fit the requested model: {exc}",
                "training_row_count": len(train_rows), "test_row_count": len(test_rows),
                "split_reference": split_reference}
    if model is None or training_report.get("status") != "VALID":
        return {"status": "INCONCLUSIVE", "reason": "the training partition does not support the requested sensitivity model",
                "training_model": training_report, "training_row_count": len(train_rows),
                "test_row_count": len(test_rows), "split_reference": split_reference}
    fixed_fields = fit_options.get("fixed_effect_fields", [])
    predictions, actuals, group_errors = [], [], {}
    try:
        for row in test_rows:
            _check_cancel(cancel)
            fixed = {}
            for field in fixed_fields:
                value = row
                for part in field.split("."):
                    value = value[part]
                fixed[field] = value
            estimate = model.predict(row["factors"], fixed).get("estimate")
            actual = float(row["metrics"][metric])
            if not _finite_number(estimate) or not _finite_number(actual):
                raise ValueError("test predictions and outcomes must be finite")
            predictions.append(float(estimate)); actuals.append(actual)
            group = row
            for part in group_field.split("."):
                group = group[part]
            group_errors.setdefault(str(group), []).append(float(estimate)-actual)
    except (KeyError, TypeError, ValueError, ModelError) as exc:
        return {"status": "INCONCLUSIVE", "reason": f"test rows are not estimable under the training model: {exc}",
                "training_row_count": len(train_rows), "test_row_count": len(test_rows),
                "split_reference": split_reference}
    errors = [predicted-observed for predicted, observed in zip(predictions, actuals)]
    training_mean = mean(float(row["metrics"][metric]) for row in train_rows)
    baseline_errors = [training_mean-value for value in actuals]
    rmse = sqrt(mean(error*error for error in errors))
    baseline_rmse = sqrt(mean(error*error for error in baseline_errors))
    group_summary = [{"group": group, "mean_error": mean(values),
                      "mae": mean(abs(value) for value in values)}
                     for group, values in group_errors.items()]
    group_summary.sort(key=lambda item: item["mae"], reverse=True)
    return {"status": "COMPLETED_DIAGNOSTIC", "split_reference": split_reference,
            "split_reference_status": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
            "train_end": train_end.isoformat(), "test_start": test_start.isoformat(),
            "group_field": group_field, "timestamp_field": timestamp_field, "metric": metric,
            "training_row_count": len(train_rows), "test_row_count": len(test_rows),
            "training_group_count": len(observed_train_groups), "test_group_count": len(observed_test_groups),
            "heldout_performance": {"bias_prediction_minus_observed": mean(errors),
                                    "mae": mean(abs(error) for error in errors), "rmse": rmse,
                                    "training_mean_baseline_rmse": baseline_rmse,
                                    "rmse_skill_vs_training_mean": (1-rmse/baseline_rmse if baseline_rmse else None),
                                    "worst_test_groups_by_mae": group_summary[:10]},
            "training_fit": {"status": training_report["status"],
                             "covariance": training_report.get("inference", {}).get("covariance")},
            "generalization_claim": "descriptive performance on the supplied time/group holdout only; split provenance is not authenticated and this is not a future guarantee",
            "causal_claim": False}


def _declared_adjustment_fields(options):
    adjustment_fields = options.get("adjustment_sensitivity_fields", [])
    if (not isinstance(adjustment_fields, list) or len(adjustment_fields) > 16
            or any(not isinstance(field, str) or not field.strip() or field != field.strip()
                   for field in adjustment_fields)
            or len(set(adjustment_fields)) != len(adjustment_fields)):
        raise ModelError("adjustment_sensitivity_fields must contain at most 16 unique nonempty row field paths")
    return adjustment_fields


def _model_specification_sensitivity(rows, factor_defs, metric, options, base_report, cancel=None):
    """Compare fixed terms and caller-nominated adjustments; never select a formula."""
    specification = base_report.get("model_specification", {})
    factors = specification.get("factors", [])
    adjustment_fields = _declared_adjustment_fields(options)

    def signature(candidate):
        selected = candidate.get("factor_fields", factors)
        interaction_choice = candidate.get("interactions", False)
        if interaction_choice is True:
            interactions = tuple(combinations(selected, 2))
        elif isinstance(interaction_choice, list):
            interactions = tuple(tuple(pair) for pair in interaction_choice)
        else:
            interactions = ()
        quadratic_choice = candidate.get("quadratic", False)
        if quadratic_choice is True:
            quadratic = tuple(selected)
        elif isinstance(quadratic_choice, list):
            quadratic = tuple(quadratic_choice)
        else:
            quadratic = ()
        return (tuple(selected), interactions, quadratic,
                tuple(candidate.get("fixed_effect_fields", [])),
                tuple(tuple(pair) for pair in candidate.get("fixed_effect_interactions", [])))

    requested = []
    linear = dict(options)
    linear.update({"interactions": False, "quadratic": False, "fixed_effect_interactions": []})
    requested.append(("linear_additive", linear))
    quadratic = dict(options)
    quadratic.update({"interactions": False, "quadratic": True, "fixed_effect_interactions": []})
    requested.append(("quadratic_additive", quadratic))
    nonlinear = dict(options)
    nonlinear.update({"interactions": True, "quadratic": True})
    requested.append(("quadratic_pairwise_interactions", nonlinear))
    if specification.get("fixed_effect_fields"):
        without_fixed_effects = dict(options)
        without_fixed_effects.update({"fixed_effect_fields": [], "fixed_effect_interactions": []})
        requested.append(("without_declared_fixed_effects", without_fixed_effects))
    base_fixed_fields = list(specification.get("fixed_effect_fields", []))
    already_adjusted = [field for field in adjustment_fields if field in base_fixed_fields]
    for field in adjustment_fields:
        if field in base_fixed_fields:
            continue
        adjusted = dict(options)
        adjusted["fixed_effect_fields"] = [*base_fixed_fields, field]
        requested.append((f"adjustment_field:{field}", adjusted))

    base_signature = signature(options)
    unique = []
    seen = {base_signature}
    for name, candidate in requested:
        candidate_signature = signature(candidate)
        if candidate_signature in seen:
            continue
        seen.add(candidate_signature)
        unique.append((name, candidate))
    if not unique:
        return {"status": "NOT_REQUIRED", "reason": "the caller formula is already the only distinct supported specification in the comparison set"}

    variants = []
    factor_estimates = {factor: [{"formula": "caller_specification",
                                  "estimate": base_report.get("terms", {}).get(factor, {}).get("estimate"),
                                  "standard_error": base_report.get("terms", {}).get(factor, {}).get("standard_error"),
                                  "ci95": base_report.get("terms", {}).get(factor, {}).get("ci95")}]
                        for factor in factors}
    for name, candidate in unique:
        if cancel and cancel():
            raise RegressionCancelled("model-specification sensitivity cancelled")
        try:
            report, _model = fit_linear_model(rows, factor_defs, metric, candidate, cancel=cancel)
        except ModelError as exc:
            variants.append({"formula": name, "status": "INCONCLUSIVE", "reason": str(exc), "factor_terms": {}})
            continue
        report_terms = report.get("terms", {})
        if not isinstance(report_terms, dict):
            report_terms = {}
        terms = {factor: report_terms.get(factor, {}) for factor in factors}
        variants.append({"formula": name, "status": report.get("status"),
                         "term_count": report.get("term_count"),
                         "fixed_effect_fields": report.get("model_specification", {}).get("fixed_effect_fields", []),
                         "factor_terms": terms,
                         "reason": report.get("reason")})
        if report.get("status") == "VALID":
            for factor in factors:
                term = terms.get(factor, {})
                if _finite_number(term.get("estimate")):
                    factor_estimates[factor].append({"formula": name, "estimate": term["estimate"],
                                                     "standard_error": term.get("standard_error"),
                                                     "ci95": term.get("ci95")})

    stability = {}
    for factor, entries in factor_estimates.items():
        estimates = [entry["estimate"] for entry in entries if _finite_number(entry.get("estimate"))]
        signs = {"positive" if value > 1e-12 else "negative" if value < -1e-12 else "near_zero"
                 for value in estimates}
        stability[factor] = {"formula_estimates": entries,
                             "point_direction_stable": not ("positive" in signs and "negative" in signs),
                             "sign_reversal_observed": "positive" in signs and "negative" in signs,
                             "estimate_range": [min(estimates), max(estimates)] if estimates else None}
    return {"status": "COMPLETED_DIAGNOSTIC", "method": "caller-specified formula plus fixed linear, quadratic, interaction, declared-fixed-effect ablations, and one-at-a-time caller-nominated adjustments",
            "base_formula": specification, "variants": variants, "factor_stability": stability,
            "adjustment_sensitivity": {"requested_fields": adjustment_fields,
                                       "already_in_base_formula": already_adjusted,
                                       "scope": "same-sample descriptive adjustment using caller-supplied measured row fields; does not identify confounders, establish causal effects, auto-adjust, or select a formula"},
            "model_selection": "none; the caller formula is retained and no variant is chosen by these diagnostics",
            "interpretation": "formula sensitivity is descriptive on the same observations; point-sign changes flag model dependence, and displayed intervals are unadjusted across formulas"}


def _source_refs(data):
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    for source in sources:
        if not isinstance(source, dict) or not str(source.get("id", "")).startswith("SYN-"):
            raise ValueError("this build accepts synthetic source references only")
        if not str(source.get("approved_semantic_version", "")).startswith("SYNTHETIC-"):
            raise ValueError("synthetic mode cannot label a source as company-approved")
        source_hash = source.get("source_hash")
        if not isinstance(source.get("grain"), str) or not source["grain"]:
            raise ValueError("source references require grain and source_hash")
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash.lower()):
            raise ValueError("synthetic source_hash must be a 64-character SHA-256 hex digest")
    return sources


def _validate_lineage(rows, sources, data):
    known = {source["id"] for source in sources}
    used = set()
    for row in rows:
        refs = row.get("source_ids")
        if refs is None:
            one = row.get("source_id")
            refs = [one] if one is not None else []
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in known for ref in refs):
            if sources or refs:
                raise ValueError("each sourced observation must identify its synthetic source ID")
            continue
        if len(refs) > 1:
            linkage = data.get("linkage", {})
            if (not isinstance(linkage, dict) or linkage.get("approved") is not True
                    or not str(linkage.get("relationship_id", "")).startswith("SYN-")
                    or not str(linkage.get("approval_reference", "")).startswith("SYN-")):
                raise ValueError("multi-source observations require an explicit versioned relationship contract reference")
        used.update(refs)
    if sources and used != known:
        raise ValueError("source references must exactly match the sources used by observations")
    return sorted(used)


def analyze(data: dict[str, Any], *, cancel=None):
    """Build one reproducible evidence dossier; every data path is read-only and synthetic."""
    if not isinstance(data, dict):
        data = {"_invalid_input_type": type(data).__name__}
    if data.get("request_actuation") or data.get("request_recipe_change"):
        return envelope("p4", data, "REFUSED", [], ["No equipment commands, recipe writes, or manufacturing actuation are available."])
    if data.get("mode") == "INTERNAL_AUTHORIZED":
        return envelope("p4", data, "REFUSED", [], ["No real Fab Insight MCP connector is configured; synthetic-only analysis cannot qualify internal data."])
    if data.get("constraints_approved") is not True:
        return envelope("p4", data, "REFUSED", [], ["Engineer-approved factor bounds and process constraints are absent."])
    if isinstance(data.get("factors"), list):
        context = data.get("context")
        metadata = ("grain", "sampling_unit", "timestamp_semantics")
        if (not isinstance(data.get("objective"), str) or not data["objective"].strip() or
                not isinstance(context, dict) or not context or
                any(not isinstance(data.get(k), str) or not data[k].strip() for k in metadata)):
            return envelope("p4", data, "REFUSED", [], ["Canonical investigations require an objective, process context, row grain, sampling unit, and timestamp semantics."])
    try:
        _check_cancel(cancel)
        sources = _source_refs(data)
        fdefs, mdefs, rows = _normalise(data, cancel)
        _validate_declared_independent_unit(rows, data)
        source_ids = _validate_lineage(rows, sources, data)
        primary_metric = data.get("primary_metric", next(iter(mdefs)))
        if primary_metric not in mdefs:
            raise ValueError("primary_metric must name a defined metric")
        options = data.get("model", {})
        if not isinstance(options, dict):
            raise ValueError("model options must be an object")
        _declared_adjustment_fields(options)
        sensitivity_options = dict(options)
        robustness_spec = data.get("robustness", {})
        declared_unit = robustness_spec.get("independent_unit_field") if isinstance(robustness_spec, dict) else None
        if isinstance(declared_unit, str) and declared_unit:
            sensitivity_options.setdefault("independent_unit_field", declared_unit)
        sensitivity, sensitivity_model = fit_linear_model(
            rows, fdefs, primary_metric, sensitivity_options, cancel=cancel)
        if sensitivity.get("status") == "VALID":
            sensitivity["formula_sensitivity"] = _model_specification_sensitivity(
                rows, fdefs, primary_metric, sensitivity_options, sensitivity, cancel=cancel)
        feasible = _process_window(rows, fdefs, mdefs, data, cancel)
        supported_region = (explore_window(rows, fdefs, mdefs, data, cancel)
                            if isinstance(data.get("factors"), list) else {"status": "NOT_REQUESTED", "grid": [], "candidate_cells": []})
        robustness = _robust_window(rows, fdefs, mdefs, data, feasible)
        tradeoffs = _pareto(rows, mdefs, fdefs, data, cancel)
        doe = _experiment_design(fdefs, data, rows, mdefs, supported_region, cancel)
        effect = _effectiveness(data, mdefs)
        split = _validate_time_split(data.get("validation_split"), rows, fdefs, mdefs,
                                     sensitivity_options, primary_metric, cancel)
    except AnalysisCancelled:
        return envelope("p4", data, "REFUSED", [], ["Analysis was cancelled before a result was produced; no external operation was started."])
    except RegressionCancelled:
        return envelope("p4", data, "REFUSED", [], ["Analysis was cancelled before a result was produced; no external operation was started."])
    except InterruptedError:
        return envelope("p4", data, "REFUSED", [], ["Analysis was cancelled before a result was produced; no external operation was started."])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return envelope("p4", data, "REFUSED", [], [f"Invalid or unsupported investigation: {exc}"])

    limitations = ["Synthetic demonstration only; no company sources, permissions, or engineering approval were used.",
                   "Associations are not intervention effects; observed feasible points are not production recipes."]
    claims = []
    partial = False
    if sensitivity.get("status") == "VALID":
        terms = sensitivity["terms"]
        fit_factors = sensitivity.get("model_specification", {}).get("factors", list(fdefs))
        if len(fit_factors) == 1 and "factor" in terms:
            estimate = terms["factor"]["estimate"]
            observed = feasible.get("candidate_factor_values", {}).get(fit_factors[0], [])
            statement = f"Observational slope = {estimate:g} response units/factor unit; observed candidate settings meeting threshold = {observed}."
        else:
            statement = f"Adjusted observational associations were estimated for {len(fit_factors)} factors on {len(rows)} observations; no coefficient is a causal effect."
        claims.append(claim(statement, category="ASSOCIATION", method="robust_linear_model", source_ids=source_ids,
                            certainty="SUPPORTED" if sensitivity.get("residual_df", 0) > 0 else "CONDITIONAL"))
    elif sensitivity.get("diagnostics", {}).get("degenerate_residual_variation"):
        fit_factors = sensitivity.get("model_specification", {}).get("factors", [])
        if len(fit_factors) == 1 and fit_factors[0] in sensitivity.get("terms", {}):
            factor = fit_factors[0]
            estimate = sensitivity["terms"][factor]["estimate"]
            observed = feasible.get("candidate_factor_values", {}).get(factor, [])
            statement = (f"Observational slope = {estimate:g} response units/factor unit; observed candidate settings meeting threshold = {observed}. "
                         "Exact-fit residuals did not support inferential intervals.")
        else:
            statement = "Factor point estimates were identified, but exact-fit residuals did not support inferential intervals."
        claims.append(claim(statement,
                            category="ASSOCIATION", method="rank-identified_model_without_estimable_residual_variation",
                            source_ids=source_ids, certainty="CONDITIONAL"))
    elif sensitivity.get("rank_deficient") is True:
        partial = True
        claims.append(claim("Separate factor sensitivities could not be identified from this design.", category="ASSOCIATION",
                            method="qr_rank_diagnostic", source_ids=source_ids, certainty="INCONCLUSIVE"))
    else:
        # Other inference refusals (for example invalid cluster nesting or too
        # few independent groups) do not imply rank deficiency. Preserve the
        # diagnostic in D01, but do not turn it into a misleading claim.
        partial = True
    if supported_region.get("status") == "VALID":
        region_counts = supported_region.get("candidate_counts_by_region", {})
        observed_count = region_counts.get("observed", 0) if isinstance(region_counts, dict) else 0
        interpolated_count = region_counts.get("interpolated", 0) if isinstance(region_counts, dict) else 0
        claims.append(claim(
                            f"The response-surface model screened {supported_region['candidate_count']} settings for advisory review "
                            f"({observed_count} observed, {interpolated_count} interpolated). Interpolated settings are unvalidated model hypotheses "
                            "and require exact-setting confirmation on independent lots; this screen does not validate a process window, "
                            "conditional coverage, or future performance.",
                            category="DESCRIPTIVE", method=supported_region["method"], source_ids=source_ids,
                            certainty="CONDITIONAL"))
    elif supported_region.get("status") not in ("NOT_REQUESTED",):
        partial = True
    if feasible.get("status") == "VALID":
        claims.append(claim(f"Observed feasible candidates: {feasible['candidate_count']} rows within approved bounds and metric constraints.",
                            category="DESCRIPTIVE", method="observed_feasible_filter", source_ids=source_ids,
                            certainty="CONDITIONAL"))
    else:
        partial = True
    if data.get("robustness") and robustness.get("status") != "VALID":
        partial = True
    if tradeoffs.get("status") == "VALID":
        claims.append(claim(f"Observed multiobjective Pareto set contains {tradeoffs['tradeoff_count']} candidates.",
                            category="DESCRIPTIVE", method="observed_pareto_filter", source_ids=source_ids,
                            certainty="CONDITIONAL"))
    elif tradeoffs.get("status") in ("LIMITED_SCOPE", "REFUSED") and (len(mdefs) > 1 or data.get("multi_step") is True):
        partial = True
    if doe.get("status") == "PROPOSED":
        statement = (f"A non-executing {doe['design']} slate contains {doe['alternative_count']} objective-specific one-run alternatives; no combined preference was inferred."
                     if isinstance(doe.get("run_options"), list) else
                     f"A non-executing {doe['design']} proposal contains {doe['run_count']} runs.")
        claims.append(claim(statement,
                            category="DESCRIPTIVE", method=doe.get("claim_method", "seeded_factorial_design"), source_ids=source_ids,
                            certainty="CONDITIONAL"))
    elif doe.get("status") == "REFUSED":
        partial = True
    if effect.get("status") == "ESTIMATED" and effect.get("causal_claim"):
        interval = effect["ci95_welch_t_approximation"]
        claims.append(claim(f"Synthetic-data {effect['design']} estimate for {effect['metric']} = {effect['estimate']:.6g} (95% Welch-t interval approximation [{interval[0]:.6g}, {interval[1]:.6g}]).",
                            category="CAUSAL_ESTIMATE", method=effect["design"], source_ids=source_ids, certainty="CONDITIONAL"))
    elif data.get("effectiveness"):
        partial = True
    if split.get("status") in ("REFUSED", "INCONCLUSIVE"):
        partial = True

    out = envelope("p4", data, "PARTIAL" if partial else "VALID", claims, limitations,
                   assumptions=["All observations and source references are supplied synthetic fixtures.",
                                "No actuation, recipe recommendation, or real company-data access is available."], sources=sources)
    out["provenance"].update({"engine_version": ENGINE_VERSION, "method_version": "p4-robust-surface-2"})
    out["populations"] = [{"n": len(rows), "grain": data.get("grain", "one supplied observation row"),
                           "sampled_unit": data.get("sampling_unit", "not specified"),
                           "timestamp_semantics": data.get("timestamp_semantics", "not specified")}]
    out["units"] = {"factors": {n: f.get("unit", "unspecified") for n, f in fdefs.items()},
                    "metrics": {n: f.get("unit", "unspecified") for n, f in mdefs.items()}}
    out["transformations"] = [{"id": "p4-robust-surface-2", "method": "pivoted QR regression with HC3 or nested declared-cluster sandwich covariance, explicit sampling-unit validation, supported 1D/2D predictive grid, typed tradeoff identities, and study-design gates"}]
    out["uncertainty"] = {"sensitivity": {k: v for k, v in sensitivity.items() if k in ("residual_sd", "residual_df", "diagnostic_warnings", "inference", "diagnostics")},
                          "supported_region": {"status": supported_region.get("status"), "region_counts": supported_region.get("region_counts"),
                                               "uncertainty_rule": supported_region.get("uncertainty_rule")},
                          "effectiveness": {k: effect.get(k) for k in ("se", "ci95_welch_t_approximation") if k in effect}}
    out["counterevidence"] = [{"check": "extrapolation", "result": feasible.get("extrapolation", "not applicable")},
                              {"check": "study-design validity", "result": effect.get("reason", effect.get("design", "not requested"))},
                              {"check": "temporal/group holdout", "result": split.get("status")}]
    out["artifacts"] = [{"type": "p4_decision_dossier", "objective": data.get("objective", "unspecified engineering objective"),
                         "context": data.get("context", {}), "source_inspection": {"mode": "SYNTHETIC_DEMO", "sources": sources,
                             "permissions": "synthetic only", "approved_company_semantics": False},
                         "D01_sensitivity": sensitivity, "D03_tradeoffs": tradeoffs,
                         "D02_observed_process_window": feasible, "D02_supported_region": supported_region,
                         "D02_robust_observed_region": robustness,
                         "D04_experiment_proposal": doe,
                         "D05_effectiveness": effect, "validation_split": split,
                         "review_fields": ["objective", "source and population eligibility", "factor roles and units", "constraints", "assumptions", "counterevidence", "approval IDs"]}]
    validate_envelope(out)
    return out


def _legacy_bounds(data):
    bounds = data.get("bounds")
    return tuple(bounds) if isinstance(bounds, (list, tuple)) and len(bounds) == 2 else ()
