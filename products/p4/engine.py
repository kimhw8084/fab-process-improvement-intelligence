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
from products.p4.design import assign_blocks, propose_design

ENGINE_VERSION = "1.1.0"
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
            raise ValueError(f"observation {i} has missing or non-finite factor values")
        my = row.get("metrics")
        if my is None and len(mdefs) == 1 and "response" in row:
            my = {next(iter(mdefs)): row["response"]}
        if not isinstance(my, dict) or any(n not in my or not _finite_number(my[n]) for n in mdefs):
            raise ValueError(f"observation {i} has missing or non-finite metric values")
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


def _experiment_design(fdefs, data, rows=None, mdefs=None, cancel=None):
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
    if strategy != "full_factorial":
        return propose_design(strategy, controls, bounds, spec, data.get("forbidden_regions", []),
                              rows=rows, metric_defs=mdefs, model_options=data.get("model", {}), cancel=cancel)
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
    return {"status": "PROPOSED", "design": "randomized full factorial at approved bounds",
            "factors": controls, "run_count": len(runs), "runs": runs,
            "randomization_seed": seed, "blocking": blocking,
            "power": power, "authorization_fields": ["engineer_approval_id", "process_owner_approval_id", "safety_review_id"],
            "executed": False, "actuation": "none"}


def _effectiveness(data):
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
        if (any(unit is None or str(unit) == "" for unit in ledger_ids) or len(set(map(str, ledger_ids))) != len(ledger_ids)
                or any(item.get("group") not in ("treatment", "control") for item in ledger)):
            return {"status": "INCONCLUSIVE", "reason": "assignment_ledger requires unique unit IDs and valid randomized groups", "causal_claim": False}
        observed_ids = [r.get("unit_id") for r in records]
        if any(unit is None or str(unit) == "" for unit in observed_ids) or len(set(map(str, observed_ids))) != len(observed_ids):
            return {"status": "INCONCLUSIVE", "reason": "randomized analysis requires one record per unique assigned independent unit", "causal_claim": False}
        ledger_groups = {str(item["unit_id"]): item["group"] for item in ledger}
        if any(str(row["unit_id"]) not in ledger_groups or ledger_groups[str(row["unit_id"])] != row["group"] for row in records):
            return {"status": "INCONCLUSIVE", "reason": "study observations do not match the randomized assignment ledger", "causal_claim": False}
        observed_by_id = {str(row["unit_id"]): row for row in records}
        complete_records = [observed_by_id.get(str(item["unit_id"]), {"unit_id": item["unit_id"], "group": item["group"]})
                           for item in ledger]
        assigned = {group: [r for r in complete_records if r["group"] == group] for group in ("treatment", "control")}
        observed = {group: [float(r[metric]) for r in units_for_group if _finite_number(r.get(metric))]
                    for group, units_for_group in assigned.items()}
        attrition = {group: {"assigned": len(assigned[group]), "observed": len(observed[group]),
                             "missing_outcome": len(assigned[group])-len(observed[group]),
                             "rate": (len(assigned[group])-len(observed[group]))/len(assigned[group]) if assigned[group] else None}
                    for group in assigned}
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
        if len(treated) < 2 or len(control) < 2:
            return {"status": "INCONCLUSIVE", "reason": "at least two independent units per randomized arm are required", "attrition": attrition, "causal_claim": False}
        estimate, se, df, interval = _mean_difference_interval(treated, control)
        baseline = {}
        baseline_fields = study.get("baseline_covariates", [])
        if baseline_fields and (not isinstance(baseline_fields, list) or any(not isinstance(field, str) for field in baseline_fields)):
            return {"status": "INCONCLUSIVE", "reason": "baseline_covariates must be a list of field names", "causal_claim": False}
        for field in baseline_fields:
            if any(not _finite_number(row.get(field)) for row in records):
                baseline[field] = {"status": "NOT_AVAILABLE"}
                continue
            values = {group: [float(row[field]) for row in assigned[group]] for group in assigned}
            pool_var = ((len(values["treatment"])-1)*variance(values["treatment"])
                        +(len(values["control"])-1)*variance(values["control"]))/(len(records)-2)
            smd = (mean(values["treatment"])-mean(values["control"]))/sqrt(pool_var) if pool_var > 0 else None
            baseline[field] = {"standardized_mean_difference": smd,
                               "imbalance_flag_abs_smd_over_0_1": abs(smd) > 0.1 if smd is not None else None}
        return {"status": "ESTIMATED", "design": "randomized two-arm difference in means", "metric": metric,
                "intervention_id": study["intervention_id"], "treatment_n": len(treated), "control_n": len(control),
                "estimate": estimate, "se": se, "welch_df": df, "ci95_welch_t_approximation": interval,
                "attrition": attrition, "baseline_balance": baseline,
                "causal_claim": True, "assumptions": ["valid documented random allocation", "independent units", "no interference", "consistent outcome measurement"],
                "diagnostics": {"small_sample_warning": min(len(treated), len(control)) < 10,
                                "assignment_unit_count": len(ledger_ids), "concurrent_intervention_ids": {group: sorted(values) for group, values in cointerventions.items()}},
                "sensitivity": {"type": "outcome_attrition", "missing_outcomes": 0,
                                "qualification": "report outcome_bounds to compute worst-case attrition bounds if missingness is present"},
                "qualification": "conditional randomized study estimate; small samples and baseline imbalance require review; not production qualification"}
    if design == "difference_in_differences":
        if (not str(study.get("authorization_id", "")).startswith("SYN-") or
                not str(study.get("intervention_id", "")).startswith("SYN-")):
            return {"status": "INCONCLUSIVE", "reason": "documented authorized intervention is required", "causal_claim": False}
        if any(row.get("group") not in ("treatment", "control") or row.get("period") not in ("pre2", "pre", "post") for row in records):
            return {"status": "INCONCLUSIVE", "reason": "DiD requires group and periods pre2, pre, and/or post", "causal_claim": False}
        ledger = study.get("assignment_ledger")
        if not isinstance(ledger, list) or not ledger or any(not isinstance(item, dict) for item in ledger):
            return {"status": "INCONCLUSIVE", "reason": "DiD requires an assignment ledger to establish the independent-unit denominator", "causal_claim": False}
        ledger_ids = [item.get("unit_id") for item in ledger]
        if (any(unit is None or str(unit) == "" for unit in ledger_ids) or len(set(map(str, ledger_ids))) != len(ledger_ids)
                or any(item.get("group") not in ("treatment", "control") for item in ledger)):
            return {"status": "INCONCLUSIVE", "reason": "DiD assignment ledger requires unique unit IDs and valid groups", "causal_claim": False}
        ledger_groups = {str(item["unit_id"]): item["group"] for item in ledger}
        if set(ledger_groups.values()) != {"treatment", "control"}:
            return {"status": "INCONCLUSIVE", "reason": "DiD assignment ledger must include both groups", "causal_claim": False}
        by_unit = {unit: {"group": group} for unit, group in ledger_groups.items()}
        for row in records:
            unit = row.get("unit_id")
            if unit is None or str(unit) == "":
                return {"status": "INCONCLUSIVE", "reason": "DiD requires independent unit IDs", "causal_claim": False}
            unit = str(unit)
            if unit not in ledger_groups or ledger_groups[unit] != row["group"]:
                return {"status": "INCONCLUSIVE", "reason": "DiD observations do not match the assignment ledger", "causal_claim": False}
            entry = by_unit[unit]
            if entry["group"] != row["group"] or row["period"] in entry:
                return {"status": "INCONCLUSIVE", "reason": "DiD assignments and period records must be unique", "causal_claim": False}
            entry[row["period"]] = float(row[metric]) if _finite_number(row.get(metric)) else None
        attrition = {group: {"assigned": 0, "complete_pre_post": 0, "complete_pretrend": 0}
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
        t, c = changes["treatment"], changes["control"]
        if len(t) < 2 or len(c) < 2:
            return {"status": "INCONCLUSIVE", "reason": "DiD requires two complete independent units per group", "attrition": attrition, "causal_claim": False}
        if any(attrition[group]["complete_pre_post"] != attrition[group]["assigned"] for group in attrition):
            return {"status": "INCONCLUSIVE", "reason": "incomplete DiD outcome panels are not imputed; causal and point estimates withheld",
                    "attrition": attrition, "causal_claim": False}
        estimate, se, df, interval = _mean_difference_interval(t, c)
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
            complete_pretrend = all(attrition[group]["complete_pretrend"] == attrition[group]["assigned"]
                                    for group in attrition)
            documented_equivalence_bound = (_finite_number(equivalence_bound) and equivalence_bound >= 0
                                            and isinstance(equivalence_source, str) and bool(equivalence_source.strip())
                                            and isinstance(equivalence_method, str) and bool(equivalence_method.strip()))
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
                        "complete_coverage": complete_pretrend,
                        "complete_units": {"treatment": len(trend_t), "control": len(trend_c)}}
        trend_bound = study.get("differential_trend_bound")
        trend_bound_source = study.get("differential_trend_bound_source")
        trend_bound_method = study.get("differential_trend_bound_method")
        documented_sensitivity_bound = (_finite_number(trend_bound) and trend_bound >= 0
                                        and isinstance(trend_bound_source, str) and bool(trend_bound_source.strip())
                                        and isinstance(trend_bound_method, str) and bool(trend_bound_method.strip()))
        sensitivity = ({"differential_trend_bound": trend_bound,
                        "bound_source": trend_bound_source, "bound_method": trend_bound_method,
                        "effect_range_under_bound": [estimate-trend_bound, estimate+trend_bound],
                        "ci95_under_bound": [interval[0]-trend_bound, interval[1]+trend_bound],
                        "point_estimate_tipping_point_abs_trend": abs(estimate),
                        "ci95_tipping_point_abs_trend": max(0.0, abs(estimate)-max(abs(interval[0]-estimate), abs(interval[1]-estimate)))}
                       if documented_sensitivity_bound else
                       {"reason": "supply a nonnegative differential_trend_bound with its source and method for quantitative sensitivity"})
        minimum_units_for_conditional_interpretation = 10
        adequate_sample = min(len(t), len(c)) >= minimum_units_for_conditional_interpretation
        concurrent_intervention_ids = {group: {str(row.get("concurrent_intervention_id", "none"))
                                               for row in records if row.get("group") == group}
                                       for group in ("treatment", "control")}
        differential_concurrent_intervention = (study.get("differential_concurrent_intervention") is True
                                                or concurrent_intervention_ids["treatment"] != concurrent_intervention_ids["control"])
        sensitivity_interval = sensitivity.get("ci95_under_bound")
        direction_supported = (sensitivity_interval is not None
                               and (sensitivity_interval[0] > 0 or sensitivity_interval[1] < 0))
        causal_ready = (pretrend.get("status") == "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF"
                        and documented_sensitivity_bound and adequate_sample
                        and not differential_concurrent_intervention and direction_supported)
        return {"status": "ESTIMATED", "design": design, "metric": metric, "treatment_n": len(t), "control_n": len(c),
                "estimate": estimate, "se": se, "welch_df": df, "ci95_welch_t_approximation": interval,
                "causal_claim": causal_ready, "attrition": attrition, "pretrend_diagnostic": pretrend,
                "sensitivity": sensitivity, "assumptions": ["parallel trends cannot be proven by pretrend data",
                    "no differential concurrent intervention", "independent units", "consistent outcome measurement"],
                "diagnostics": {"small_sample_warning": min(len(t), len(c)) < 10,
                                "minimum_units_for_conditional_interpretation": minimum_units_for_conditional_interpretation,
                                "pretrend_coverage_complete": pretrend.get("complete_coverage", False),
                                "differential_concurrent_intervention": differential_concurrent_intervention,
                                "concurrent_intervention_ids": {group: sorted(values) for group, values in concurrent_intervention_ids.items()},
                                "effect_direction_supported_under_trend_bound": direction_supported},
                "reason": None if causal_ready else "DiD point estimate is descriptive; causal interpretation withheld because design diagnostics or sensitivity bound are incomplete",
                "qualification": "conditional study estimate; parallel-trends sensitivity and engineer review required"}
    vals = [r.get(metric) for r in records if _finite_number(r.get(metric))]
    before = [r[metric] for r in records if r.get("period") == "pre" and _finite_number(r.get(metric))]
    after = [r[metric] for r in records if r.get("period") == "post" and _finite_number(r.get(metric))]
    return {"status": "INCONCLUSIVE", "descriptive_before_after": mean(after) - mean(before) if before and after else None,
            "observed_count": len(vals), "reason": "no supported causal design; any before/after difference is descriptive only",
            "causal_claim": False}


def _validate_time_split(validation):
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
    train_groups, test_groups = set(validation.get("train_groups", [])), set(validation.get("test_groups", []))
    if not train_groups or not test_groups:
        return {"status": "INCONCLUSIVE", "reason": "group-separated holdout IDs are required"}
    if train_groups.intersection(test_groups):
        return {"status": "INCONCLUSIVE", "reason": "group leakage: holdout groups overlap training groups"}
    return {"status": "VALID", "train_end": max(train_dt).isoformat(), "test_start": min(test_dt).isoformat(),
            "group_disjoint": True, "generalization_claim": "limited to supplied time/group holdout"}


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
        source_ids = _validate_lineage(rows, sources, data)
        primary_metric = data.get("primary_metric", next(iter(mdefs)))
        if primary_metric not in mdefs:
            raise ValueError("primary_metric must name a defined metric")
        options = data.get("model", {})
        if not isinstance(options, dict):
            raise ValueError("model options must be an object")
        sensitivity, sensitivity_model = fit_linear_model(rows, fdefs, primary_metric, options, cancel=cancel)
        feasible = _process_window(rows, fdefs, mdefs, data, cancel)
        supported_region = (explore_window(rows, fdefs, mdefs, data, cancel)
                            if isinstance(data.get("factors"), list) else {"status": "NOT_REQUESTED", "grid": [], "candidate_cells": []})
        robustness = _robust_window(rows, fdefs, mdefs, data, feasible)
        tradeoffs = _pareto(rows, mdefs, fdefs, data, cancel)
        doe = _experiment_design(fdefs, data, rows, mdefs, cancel)
        effect = _effectiveness(data)
        split = _validate_time_split(data.get("validation_split"))
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
    else:
        partial = True
        claims.append(claim("Separate factor sensitivities could not be identified from this design.", category="ASSOCIATION",
                            method="qr_rank_diagnostic", source_ids=source_ids, certainty="INCONCLUSIVE"))
    if supported_region.get("status") == "VALID":
        claims.append(claim(f"A supported response-surface region contains {supported_region['candidate_count']} conservative candidate cells; the cells are advisory and remain subject to engineer review.",
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
        claims.append(claim(f"A non-executing {doe['design']} proposal contains {doe['run_count']} runs.",
                            category="DESCRIPTIVE", method="seeded_factorial_design", source_ids=source_ids,
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
    out["provenance"].update({"engine_version": ENGINE_VERSION, "method_version": "p4-robust-surface-1"})
    out["populations"] = [{"n": len(rows), "grain": data.get("grain", "one supplied observation row"),
                           "sampled_unit": data.get("sampling_unit", "not specified"),
                           "timestamp_semantics": data.get("timestamp_semantics", "not specified")}]
    out["units"] = {"factors": {n: f.get("unit", "unspecified") for n, f in fdefs.items()},
                    "metrics": {n: f.get("unit", "unspecified") for n, f in mdefs.items()}}
    out["transformations"] = [{"id": "p4-robust-surface-1", "method": "pivoted QR regression with HC3 or declared cluster sandwich covariance, observed filters, supported 1D/2D predictive grid, explicit study-design gates"}]
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
