"""Approved, paired cross-step objective comparison for D03."""
from __future__ import annotations

from datetime import datetime
from itertools import combinations
from math import isfinite, sqrt
from statistics import mean, variance

from products.p4.regression import critical_t_975


class RelationshipError(ValueError):
    pass


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
    eligible = [row for row in rows if all(metric_pass(row["metrics"][name], definition) for name, definition in metric_defs.items())]
    groups = {}
    for row in eligible:
        if cancel and cancel():
            raise InterruptedError("tradeoff analysis cancelled")
        setting = tuple(row["factors"][name] for name in controls)
        unit = _path(row, unit_field)
        if unit is None or str(unit) == "":
            continue
        groups.setdefault(setting, {}).setdefault(str(unit), []).append(row)
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
            estimates[metric] = {"mean": avg, "standard_error": se, "marginal_ci95": interval}
        candidates.append({"id": "SYN-SETTING-"+"-".join(f"{value:g}" for value in setting),
                           "factors": dict(zip(controls, setting)), "independent_units": len(unit_rows),
                           "observation_count": sum(len(members) for members in unit_rows.values()),
                           "source_observation_ids": sorted(observation_ids),
                           "means": {metric: value["mean"] for metric, value in estimates.items()}, "uncertainty": estimates})
    if not candidates:
        return {"status": "LIMITED_SCOPE", "reason": "no setting met the independent-unit minimum",
                "minimum_independent_units": minimum_units, "pareto_observation_ids": []}
    front = [candidate for candidate in candidates if not any(other is not candidate and _dominates(other, candidate, objectives)
                                                               for other in candidates)]
    return {"status": "VALID" if uncertainty_available else "LIMITED_SCOPE",
            "method": "independent-unit-aggregated-Pareto-with-marginal-t-intervals",
            "objective_metrics": objectives, "decision_factors": controls, "independent_unit_field": unit_field,
            "minimum_independent_units": minimum_units, "candidate_settings": candidates,
            "pareto_setting_ids": [candidate["id"] for candidate in front],
            "pareto_observation_ids": sorted({row_id for candidate in front for row_id in candidate["source_observation_ids"]}),
            "pareto_values": [{"id": c["id"], "factors": c["factors"], **c["means"]} for c in front],
            "tradeoff_count": len(front), "uncertainty_available": uncertainty_available,
            "multiplicity_adjusted": False, "causal_claim": False,
            "qualification": "setting-level descriptive Pareto means with marginal intervals; no multiplicity-adjusted superiority or causal claim"}


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
    if (not str(link["relationship_id"]).startswith("SYN-") or link["contract_version"] != "1.0.0"
            or not str(link["approval_reference"]).startswith("SYN-")):
        return {"status": "LIMITED_SCOPE", "reason": "only the versioned synthetic relationship contract can be qualified offline",
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
    source_ids = {source.get("id") for source in data.get("sources", [])}
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
    if len(set(decision_factors)) != len(decision_factors) or any(name not in rows[0]["factors"] for name in decision_factors):
        raise RelationshipError("decision_factors must refer to normalized factors")
    objectives = data.get("objectives", [])
    objective_map = {item.get("metric"): item.get("direction") for item in objectives if isinstance(item, dict)}
    expected_metrics = {upstream["metric"], downstream["metric"]}
    if set(objective_map) != expected_metrics:
        return {"status": "LIMITED_SCOPE", "reason": "objectives must match the approved upstream/downstream metric pair",
                "pareto_observation_ids": [], "downstream_claim": "withheld"}
    for metric, direction in objective_map.items():
        if direction != metric_defs[metric].get("direction", "maximize"):
            raise RelationshipError("objective direction must agree with its approved metric definition")
    minimum_units = link.get("minimum_independent_units", 30)
    if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 3:
        raise RelationshipError("minimum_independent_units must be at least 3")

    seen_pairs, seen_units = set(), set()
    groups = {}
    for index, row in enumerate(rows):
        if cancel and cancel():
            raise InterruptedError("cross-step analysis cancelled")
        up_key = _path(row, upstream["key_field"])
        down_key = _path(row, downstream["key_field"])
        if up_key is None or down_key is None or up_key != down_key:
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
        pair = (str(up_key), str(down_key))
        unit = _path(row, unit_field)
        if pair in seen_pairs or str(unit) in seen_units:
            return {"status": "LIMITED_SCOPE", "reason": "duplicate paired key or non-independent repeated unit detected",
                    "pareto_observation_ids": [], "downstream_claim": "withheld"}
        seen_pairs.add(pair); seen_units.add(str(unit))
        refs = row.get("source_ids")
        if refs is None:
            refs = [row.get("source_id")] if row.get("source_id") is not None else []
        if upstream["source_id"] not in refs or downstream["source_id"] not in refs:
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
        groups.setdefault(setting, []).append(mapped_row)

    candidates = []
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
            critical = critical_t_975(n-1)
            estimates[metric] = {"mean": avg, "standard_error": se,
                                 "marginal_ci95": [avg-critical*se, avg+critical*se]}
        up_values = [member["metrics"][upstream["metric"]] for member in members]
        down_values = [member["metrics"][downstream["metric"]] for member in members]
        paired_covariance = sum((a-mean(up_values))*(b-mean(down_values)) for a, b in zip(up_values, down_values))/(n-1) if n > 1 else None
        candidates.append({"id": "SYN-SETTING-" + "-".join(f"{value:g}" for value in setting),
                           "factors": dict(zip(decision_factors, setting)), "independent_units": n,
                           "means": {metric: value["mean"] for metric, value in estimates.items()},
                           "uncertainty": estimates, "paired_covariance": paired_covariance})
    if not candidates:
        return {"status": "LIMITED_SCOPE", "reason": "no decision setting met the independent-unit minimum",
                "minimum_independent_units": minimum_units, "pareto_observation_ids": [], "downstream_claim": "withheld"}
    front = [candidate for candidate in candidates if not any(other is not candidate and _dominates(other, candidate, objectives)
                                                               for other in candidates)]
    comparisons = []
    for left, right in combinations(candidates, 2):
        comparisons.append({"settings": [left["id"], right["id"]],
                            "marginal_intervals_overlap": {
                                metric: not (left["uncertainty"][metric]["marginal_ci95"][0] > right["uncertainty"][metric]["marginal_ci95"][1]
                                             or right["uncertainty"][metric]["marginal_ci95"][0] > left["uncertainty"][metric]["marginal_ci95"][1])
                                for metric in expected_metrics}})
    return {"status": "VALID", "method": "paired_population_marginal_pareto_with_t_intervals",
            "relationship_id": link["relationship_id"], "relationship_contract_version": link["contract_version"],
            "approval_reference": link["approval_reference"], "population_id": upstream["population_id"],
            "upstream_source_id": upstream["source_id"], "downstream_source_id": downstream["source_id"],
            "objective_metrics": objectives, "minimum_independent_units": minimum_units,
            "compatible_paired_units": len(seen_units), "candidate_settings": candidates,
            "pareto_observation_ids": [candidate["id"] for candidate in front],
            "pareto_values": [{"id": c["id"], "factors": c["factors"], **c["means"]} for c in front],
            "tradeoff_count": len(front), "uncertainty_comparisons": comparisons,
            "multiplicity_adjusted": False, "causal_claim": False,
            "scope": "paired approved relationship contract; synthetic observations only",
            "qualification": "marginal intervals are not multiplicity-adjusted and do not establish causal effects or engineering approval"}
