"""Supported one- and two-factor response-surface exploration for D02."""
from __future__ import annotations

from hashlib import sha256
from itertools import product
from math import ceil, isfinite, sqrt
import json

from products.p4.regression import fit_linear_model, _get_field


class WindowError(ValueError):
    pass


def _check_cancel(cancel):
    if cancel and cancel():
        raise InterruptedError("window exploration cancelled")


def _hull(points):
    points = sorted(set((float(x), float(y)) for x, y in points))
    if len(points) < 3:
        return points
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 1e-12:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 1e-12:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inside_polygon(point, polygon, eps=1e-10):
    if len(polygon) < 3:
        return False
    sign = None
    for i, a in enumerate(polygon):
        b = polygon[(i+1) % len(polygon)]
        cross = (b[0]-a[0])*(point[1]-a[1]) - (b[1]-a[1])*(point[0]-a[0])
        if abs(cross) <= eps:
            continue
        current = cross > 0
        if sign is None:
            sign = current
        elif current != sign:
            return False
    return sign is not None


def _metric_pass_interval(prediction, definition):
    interval = prediction.get("predictive_interval95")
    if interval is None:
        return None
    return ((definition.get("min") is None or interval[0] >= definition["min"])
            and (definition.get("max") is None or interval[1] <= definition["max"]))


def _metric_pass(value, definition):
    return ((definition.get("min") is None or value >= definition["min"])
            and (definition.get("max") is None or value <= definition["max"]))


def _unit_key(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Numeric identifiers can arrive as either 7 or 7.0 after source/JSON
        # normalization. Treat equal numeric values as one independent unit so
        # representation drift cannot leak a lot across analysis partitions.
        normalized = int(value) if isinstance(value, float) and isfinite(value) and value.is_integer() else value
        identity = {"type": "number", "value": normalized}
    else:
        identity = {"type": type(value).__name__, "value": value}
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _split_calibration(rows, unit_field, config, minimum_calibration_units):
    if not isinstance(config, dict):
        return None, "a declared independent-group calibration holdout is required", None, None
    group_field = config.get("group_field")
    partition_field = config.get("partition_field")
    training_value = config.get("training_value")
    calibration_value = config.get("calibration_value")
    evaluation_value = config.get("evaluation_value")
    split_reference = config.get("split_reference")
    if (not isinstance(group_field, str) or group_field != unit_field
            or not isinstance(partition_field, str) or not partition_field
            or not isinstance(training_value, str) or not training_value
            or not isinstance(calibration_value, str) or not calibration_value
            or not isinstance(split_reference, str) or not split_reference.strip()
            or training_value == calibration_value
            or (evaluation_value is not None and
                (not isinstance(evaluation_value, str) or not evaluation_value
                 or evaluation_value in (training_value, calibration_value)))):
        return None, "calibration needs an independent-unit partition and a precommit/split reference", None, None
    partitions_by_unit = {}
    row_partitions = []
    allowed_partitions = (training_value, calibration_value) + ((evaluation_value,) if evaluation_value is not None else ())
    for row in rows:
        try:
            unit_value = _get_field(row, group_field)
            partition = _get_field(row, partition_field)
        except (KeyError, ValueError):
            return None, "calibration group or partition field is missing", None, None
        if (unit_value is None or isinstance(unit_value, bool)
                or (isinstance(unit_value, str) and not unit_value.strip())
                or (isinstance(unit_value, float) and not isfinite(unit_value))
                or not isinstance(unit_value, (str, int, float))):
            return None, "the independent unit field contains a null, empty, or non-scalar identifier", None, None
        unit = _unit_key(unit_value)
        if partition not in allowed_partitions:
            return None, "every eligible row must be assigned to a declared training, calibration, or evaluation partition", None, None
        partitions_by_unit.setdefault(unit, set()).add(partition)
        row_partitions.append(partition)
    if any(len(values) != 1 for values in partitions_by_unit.values()):
        return None, "an independent unit crosses the training and calibration partitions or the independent evaluation partition", None, None
    training = [row for row, partition in zip(rows, row_partitions) if partition == training_value]
    calibration = [row for row, partition in zip(rows, row_partitions) if partition == calibration_value]
    evaluation = ([row for row, partition in zip(rows, row_partitions) if partition == evaluation_value]
                  if evaluation_value is not None else [])
    training_units = {_unit_key(_get_field(row, group_field)) for row in training}
    calibration_units = {_unit_key(_get_field(row, group_field)) for row in calibration}
    if training_units & calibration_units:
        return None, "training, calibration, and evaluation units must be disjoint", None, None
    if len(calibration_units) < minimum_calibration_units:
        return None, f"at least {minimum_calibration_units} independent calibration units are required for a finite 95% bound", None, None
    evaluation_units = {_unit_key(_get_field(row, group_field)) for row in evaluation}
    if evaluation_value is not None and not evaluation_units:
        return None, "the declared independent evaluation partition has no eligible units", None, None
    return (training, calibration,
            {"group_field": group_field, "partition_field": partition_field,
             "training_value": training_value, "calibration_value": calibration_value,
             "evaluation_value": evaluation_value,
             "split_reference": split_reference,
             "training_unit_count": len(training_units), "calibration_unit_count": len(calibration_units),
             "evaluation_unit_count": len(evaluation_units),
             "training_row_count": len(training), "calibration_row_count": len(calibration),
             "evaluation_row_count": len(evaluation),
             "order_statistic_reference": 0.95,
             "coverage_guarantee": "none; this local score rank establishes neither conditional nor simultaneous coverage",
             "method": "local_grouped_holdout_absolute_error",
             "evaluation_role": "post-screening independent diagnostic only; evaluation outcomes do not alter fit, calibration, or candidate selection"}, evaluation)


def _fit_grouped_calibration(training, calibration, factor_defs, metric, options, fixed_effects, group_field, cancel):
    report, model = fit_linear_model(training, factor_defs, metric, options, cancel=cancel)
    if model is None or report.get("status") != "VALID":
        return report, model, None
    residuals = {}
    for row in calibration:
        _check_cancel(cancel)
        prediction = model.predict(row["factors"], fixed_effects)
        if not isinstance(prediction.get("estimate"), (int, float)) or not isfinite(prediction["estimate"]):
            return {"status": "INCONCLUSIVE", "reason": "calibration prediction is unavailable"}, None, None
        group = _unit_key(_get_field(row, group_field))
        error = abs(float(row["metrics"][metric]) - prediction["estimate"])
        residuals.setdefault(group, []).append({"row": row, "absolute_error": error})
    return report, model, residuals


def _finite_rank_quantile(scores, coverage=0.95):
    ordered = sorted(scores)
    rank = ceil((len(ordered) + 1) * coverage)
    if not ordered or rank > len(ordered):
        return None
    return ordered[rank - 1]


def _normalize_metric_bounds(metric_bounds, metrics):
    if not isinstance(metric_bounds, dict) or set(metric_bounds) != set(metrics):
        return None
    normalized = {}
    for metric in metrics:
        definition = metric_bounds.get(metric)
        if not isinstance(definition, dict) or set(definition) != {"min", "max"}:
            return None
        bounds = {}
        for name in ("min", "max"):
            value = definition[name]
            if value is None:
                bounds[name] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                bounds[name] = float(value)
            else:
                return None
        if (bounds["min"] is None and bounds["max"] is None
                or bounds["min"] is not None and bounds["max"] is not None
                and bounds["min"] > bounds["max"]):
            return None
        normalized[metric] = bounds
    return {name: normalized[name] for name in sorted(normalized)}


def _normalize_precommit_strata(value):
    """Validate caller-predeclared finite calibration strata; never infer categories from outcomes."""
    if value is None:
        return None, None
    if not isinstance(value, dict) or set(value) != {"fields", "categories"}:
        return None, "strata must contain exactly fields and categories"
    fields = value["fields"]
    categories = value["categories"]
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 5
            or any(not isinstance(field, str) or not field.strip() for field in fields)
            or len(fields) != len(set(fields))):
        return None, "strata fields must be one to five unique non-empty strings"
    if not isinstance(categories, list) or not 2 <= len(categories) <= 100:
        return None, "strata categories must predeclare two to one hundred categories"
    normalized = []
    keys = set()
    for category in categories:
        if not isinstance(category, dict) or set(category) != set(fields):
            return None, "each stratum category must supply exactly every predeclared field"
        clean = {}
        for field in fields:
            item = category[field]
            if isinstance(item, str) and item.strip():
                clean[field] = item
            elif isinstance(item, (int, float)) and not isinstance(item, bool) and isfinite(item):
                clean[field] = int(item) if isinstance(item, float) and item.is_integer() else float(item)
            else:
                return None, "stratum values must be non-empty strings or finite numbers"
        key = _precommit_stratum_key(clean, fields)
        if key in keys:
            return None, "strata categories must be unique"
        keys.add(key)
        normalized.append(clean)
    normalized.sort(key=lambda category: _precommit_stratum_key(category, fields))
    return {"fields": fields, "categories": normalized}, None


def _precommit_stratum_key(category, fields):
    return json.dumps([_unit_key(category[field]) for field in fields], separators=(",", ":"))


def _row_stratum_key(row, fields):
    category = {}
    for field in fields:
        try:
            value = _get_field(row, field)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"missing or invalid predeclared stratum field {field}") from exc
        if isinstance(value, str) and value.strip():
            category[field] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            category[field] = int(value) if isinstance(value, float) and value.is_integer() else float(value)
        else:
            raise ValueError(f"missing or invalid predeclared stratum field {field}")
    return _precommit_stratum_key(category, fields)


def _predeclared_strata_compatibility(rows, unit_field, strata):
    """Check that every independent unit is assignable to one planned category."""
    if not strata:
        return {"status": "NOT_DECLARED", "unit_count": 0, "unassignable_units": 0,
                "unplanned_category_units": 0, "mixed_category_units": 0}
    if not rows:
        return {"status": "NOT_PROVIDED", "unit_count": 0, "unassignable_units": 0,
                "unplanned_category_units": 0, "mixed_category_units": 0}
    fields = strata["fields"]
    planned = {_precommit_stratum_key(category, fields) for category in strata["categories"]}
    categories_by_unit = {}
    invalid_units = set()
    unplanned_units = set()
    for index, row in enumerate(rows):
        try:
            unit = _unit_key(_get_field(row, unit_field))
        except (KeyError, TypeError, ValueError):
            unit = ("INVALID_ROW", str(row.get("id", f"ROW-{index}")))
        try:
            category = _row_stratum_key(row, fields)
        except (KeyError, TypeError, ValueError):
            invalid_units.add(unit)
            continue
        categories_by_unit.setdefault(unit, set()).add(category)
        if category not in planned:
            unplanned_units.add(unit)
    mixed_units = {unit for unit, categories in categories_by_unit.items() if len(categories) != 1}
    invalid_unit_count = len(invalid_units)
    mixed_count = len(mixed_units)
    unplanned_count = len(unplanned_units)
    if invalid_unit_count or mixed_count:
        status = "UNASSIGNABLE_OR_MIXED_UNITS"
    elif unplanned_count:
        status = "UNPLANNED_CATEGORIES_OBSERVED"
    else:
        status = "MATCHED_PREDECLARED_CATEGORIES"
    return {"status": status,
            "unit_count": len(set(categories_by_unit) | invalid_units),
            "unassignable_units": invalid_unit_count,
            "unplanned_category_units": unplanned_count,
            "mixed_category_units": mixed_count,
            "fields": fields,
            "interpretation": "source-field membership check only; caller-defined labels and their engineering semantics are unauthenticated"}


def _validate_window_precommit(plan, metrics, model_factors, active_metric_bounds):
    if not isinstance(plan, dict):
        return None, {"status": "PRECOMMIT_NOT_PROVIDED",
                      "reason": "a precommitted model, threshold, metric-family, and exact-setting panel plan is required for simultaneous calibration"}
    references = ("plan_reference", "model_selection_reference", "threshold_selection_reference")
    if any(not isinstance(plan.get(name), str) or not plan[name].strip() for name in references):
        return None, {"status": "PRECOMMIT_INVALID",
                      "reason": "precommit plan, model-selection, and threshold-selection references must be non-empty strings"}
    metric_family = plan.get("metric_family")
    if (not isinstance(metric_family, list) or any(not isinstance(name, str) or not name for name in metric_family)
            or len(metric_family) != len(set(metric_family)) or set(metric_family) != set(metrics)):
        return None, {"status": "PRECOMMIT_METRIC_FAMILY_MISMATCH",
                      "reason": "the precommitted metric family must exactly match every constrained D02 metric"}
    expected_bounds = _normalize_metric_bounds(active_metric_bounds, metrics)
    declared_bounds = _normalize_metric_bounds(plan.get("metric_bounds"), metrics)
    if expected_bounds is None or declared_bounds != expected_bounds:
        return None, {"status": "PRECOMMIT_THRESHOLD_MISMATCH",
                      "reason": "the precommitted metric bounds must exactly match the active metric limits"}
    strata, strata_error = _normalize_precommit_strata(plan.get("strata"))
    if strata_error:
        return None, {"status": "PRECOMMIT_STRATA_INVALID", "reason": strata_error}
    observations_per_setting = plan.get("observations_per_setting", 1)
    if (not isinstance(observations_per_setting, int) or isinstance(observations_per_setting, bool)
            or not 1 <= observations_per_setting <= 5000):
        return None, {"status": "PRECOMMIT_REPLICATE_COUNT_INVALID",
                      "reason": "observations_per_setting must be a precommitted integer from 1 to 5000"}
    panel = plan.get("exact_setting_panel")
    if not isinstance(panel, list) or not panel or len(panel) > 1681:
        return None, {"status": "PRECOMMIT_PANEL_INVALID",
                      "reason": "the precommitted exact-setting panel must contain 1 to 1681 settings"}
    parsed = []
    for setting in panel:
        if (not isinstance(setting, dict) or set(setting) != set(model_factors)
                or any(not isinstance(setting[name], (int, float)) or isinstance(setting[name], bool)
                       or not isfinite(setting[name]) for name in model_factors)):
            return None, {"status": "PRECOMMIT_PANEL_INVALID",
                          "reason": "each precommitted setting must supply every modeled factor exactly once with a finite numeric value"}
        key = tuple(float(setting[name]) for name in model_factors)
        if key in parsed:
            return None, {"status": "PRECOMMIT_PANEL_INVALID", "reason": "the precommitted exact-setting panel contains duplicate settings"}
        parsed.append(key)
    ordered = sorted(parsed)
    normalized_plan = {
        "plan_reference": plan["plan_reference"],
        "model_selection_reference": plan["model_selection_reference"],
        "threshold_selection_reference": plan["threshold_selection_reference"],
        "metric_family": sorted(metric_family),
        "metric_bounds": expected_bounds,
        "observations_per_setting": observations_per_setting,
        "exact_setting_panel": [dict(zip(model_factors, setting)) for setting in ordered],
    }
    if strata is not None:
        normalized_plan["strata"] = strata
    digest = sha256(json.dumps(normalized_plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"keys": set(ordered), "settings": normalized_plan["exact_setting_panel"],
            "observations_per_setting": observations_per_setting,
            "strata": strata,
            "evidence": {**normalized_plan, "status": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
                         "plan_sha256": digest}}, None


def _simultaneous_exact_setting_calibration(calibration_rows, metrics, models, model_factors,
                                             fixed_effects, group_field, precommit_plan,
                                             active_metric_bounds, alpha=0.05):
    """Build a split-conformal band across a complete exact-setting panel.

    Each independent calibration unit contributes one maximum absolute error
    per metric, maximized over every exact setting and replicate in its panel.
    Bonferroni allocation across metrics then controls the declared finite
    family, conditional on the caller's split and exchangeability assumptions.
    This deliberately does not extend to interpolated settings.
    """
    checked_plan, plan_error = _validate_window_precommit(
        precommit_plan, metrics, model_factors, active_metric_bounds)
    if plan_error:
        return {**plan_error, "calibration_unit_count": 0, "common_exact_settings": [],
                "metric_quantiles": {}, "precommit": None}

    group_errors = {}
    group_settings = {}
    group_setting_counts = {}
    group_strata = {}
    declared_strata = checked_plan["strata"]
    declared_stratum_keys = ({_precommit_stratum_key(category, declared_strata["fields"]): category
                              for category in declared_strata["categories"]}
                             if declared_strata else None)
    for row in calibration_rows:
        try:
            unit = _unit_key(_get_field(row, group_field))
            if declared_strata:
                stratum_key = _row_stratum_key(row, declared_strata["fields"])
                group_strata.setdefault(unit, set()).add(stratum_key)
            factors = row["factors"]
            setting = tuple(factors[name] for name in model_factors)
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
                   for value in setting):
                raise ValueError("non-numeric exact setting")
            observed = row["metrics"]
            group_errors.setdefault(unit, {metric: [] for metric in metrics})
            group_settings.setdefault(unit, set()).add(setting)
            setting_counts = group_setting_counts.setdefault(unit, {})
            setting_counts[setting] = setting_counts.get(setting, 0) + 1
            for metric in metrics:
                prediction = models[metric].predict(factors, fixed_effects)
                estimate = prediction.get("estimate")
                if not isinstance(estimate, (int, float)) or not isfinite(estimate):
                    raise ValueError(f"unavailable calibration prediction for {metric}")
                value = observed.get(metric)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
                    raise ValueError(f"missing or invalid calibration outcome for {metric}")
                group_errors[unit][metric].append(abs(float(value) - estimate))
        except (KeyError, TypeError, ValueError) as exc:
            if declared_strata and "predeclared stratum field" in str(exc):
                return {"status": "INVALID_CALIBRATION_STRATA", "reason": str(exc),
                        "calibration_unit_count": len(group_errors), "common_exact_settings": [],
                        "metric_quantiles": {}, "precommit": checked_plan["evidence"]}
            return {"status": "INCOMPLETE_CALIBRATION_PANEL", "reason": str(exc),
                    "calibration_unit_count": len(group_errors), "common_exact_settings": [],
                    "metric_quantiles": {}}
    if not group_errors:
        return {"status": "INSUFFICIENT_CALIBRATION_UNITS", "reason": "no calibration units were supplied",
                "calibration_unit_count": 0, "common_exact_settings": [], "metric_quantiles": {}}
    setting_sets = list(group_settings.values())
    if (any(settings != setting_sets[0] for settings in setting_sets[1:])
            or any(settings != checked_plan["keys"] for settings in setting_sets)):
        return {"status": "INCOMPLETE_CALIBRATION_PANEL",
                "reason": "every calibration unit must cover exactly the same complete panel declared in the precommit plan",
                "calibration_unit_count": len(group_errors), "common_exact_settings": [],
                "declared_exact_setting_count": len(checked_plan["keys"]),
                "observed_exact_setting_count": len(setting_sets[0]), "metric_quantiles": {},
                "precommit": checked_plan["evidence"]}
    expected_observations = checked_plan["observations_per_setting"]
    count_mismatches = [unit for unit, counts in group_setting_counts.items()
                        if any(counts.get(setting, 0) != expected_observations
                               for setting in checked_plan["keys"])]
    if count_mismatches:
        return {"status": "INCOMPLETE_CALIBRATION_PANEL",
                "reason": "every independent calibration unit must match the precommitted observation count at every exact setting",
                "calibration_unit_count": len(group_errors),
                "replicate_count_mismatch_unit_count": len(count_mismatches),
                "observations_per_setting": expected_observations,
                "declared_exact_setting_count": len(checked_plan["keys"]),
                "metric_quantiles": {}, "precommit": checked_plan["evidence"]}
    count = len(group_errors)
    per_metric_alpha = alpha / len(metrics)
    quantiles = {}
    stratum_quantiles = {}
    if declared_strata:
        expected_keys = set(declared_stratum_keys)
        if (any(len(group_strata.get(unit, set())) != 1 for unit in group_errors)
                or any(next(iter(group_strata[unit])) not in expected_keys for unit in group_errors)):
            return {"status": "INVALID_CALIBRATION_STRATA",
                    "reason": "each calibration unit must belong to exactly one caller-predeclared stratum",
                    "calibration_unit_count": count, "common_exact_settings": [],
                    "metric_quantiles": {}, "precommit": checked_plan["evidence"]}
        scores_by_stratum = {key: {metric: [] for metric in metrics} for key in expected_keys}
        for unit, values in group_errors.items():
            category_key = next(iter(group_strata[unit]))
            for metric in metrics:
                scores_by_stratum[category_key][metric].append(max(values[metric]))
        ranks = {key: ceil((len(scores[metrics[0]]) + 1) * (1.0 - per_metric_alpha))
                 for key, scores in scores_by_stratum.items()}
        if any(not scores_by_stratum[key][metrics[0]] or ranks[key] > len(scores_by_stratum[key][metrics[0]])
               for key in expected_keys):
            return {"status": "INSUFFICIENT_STRATUM_CALIBRATION_UNITS",
                    "reason": "every predeclared stratum needs enough independent units for the finite-sample metric-family rank",
                    "calibration_unit_count": count, "metric_count": len(metrics),
                    "familywise_alpha": alpha, "per_metric_alpha": per_metric_alpha,
                    "stratum_calibration_unit_counts": {
                        json.dumps(declared_stratum_keys[key], sort_keys=True): len(scores_by_stratum[key][metrics[0]])
                        for key in expected_keys},
                    "order_statistic_ranks": ranks, "common_exact_settings": [],
                    "metric_quantiles": {}, "precommit": checked_plan["evidence"]}
        for metric in metrics:
            records = []
            for key in sorted(expected_keys):
                scores = sorted(scores_by_stratum[key][metric])
                rank = ranks[key]
                records.append({"stratum": declared_stratum_keys[key],
                                "calibration_units": len(scores), "order_statistic_rank": rank,
                                "absolute_error_radius": scores[rank - 1]})
            stratum_quantiles[metric] = records
            quantiles[metric] = {"absolute_error_radius": max(item["absolute_error_radius"] for item in records),
                                 "calibration_units": count,
                                 "per_metric_marginal_level": 1.0 - per_metric_alpha,
                                 "stratum_quantiles": records}
        rank = max(ranks.values())
    else:
        rank = ceil((count + 1) * (1.0 - per_metric_alpha))
        if rank > count:
            return {"status": "INSUFFICIENT_CALIBRATION_UNITS",
                    "reason": "the finite-sample order-statistic rank exceeds the number of independent calibration units",
                    "calibration_unit_count": count, "metric_count": len(metrics),
                    "familywise_alpha": alpha, "per_metric_alpha": per_metric_alpha,
                    "order_statistic_rank": rank, "common_exact_settings": [],
                    "metric_quantiles": {}}
        for metric in metrics:
            scores = [max(values[metric]) for values in group_errors.values()]
            quantiles[metric] = {"absolute_error_radius": sorted(scores)[rank - 1],
                                 "order_statistic_rank": rank,
                                 "calibration_units": count,
                                 "per_metric_marginal_level": 1.0 - per_metric_alpha}
    ordered_settings = checked_plan["settings"]
    method = ("stratum-specific independent-unit split-conformal maximum scores with conservative worst-stratum radii over complete exact-setting panels and Bonferroni metric allocation"
              if declared_strata else
              "independent-unit split-conformal maximum score over complete exact-setting panels with Bonferroni metric allocation")
    assumption = (
        "Under within-stratum exchangeability of independent calibration and future units, identical complete setting panels, "
        "a model, declared strata, metric family, exact-setting panel, observations per setting, and thresholds fixed before calibration outcomes were inspected, "
        "the worst-stratum split-conformal radii target at least 95% marginal simultaneous predictive coverage for one future independent unit "
        "within each predeclared stratum, across this finite exact-setting panel and all declared constrained metrics. These assumptions, stratum semantics, "
        "and source split provenance are not verified here; this is not coverage for undeclared strata, interpolated regions, or a production population."
        if declared_strata else
        "Under exchangeability of independent calibration and future units, identical complete setting panels, "
        "a model, metric family, exact-setting panel, observations per setting, and thresholds fixed before calibration outcomes were inspected, the "
        "split-conformal maximum-score construction targets at least 95% marginal simultaneous predictive "
        "coverage for this finite exact-setting panel with the declared observation count at each setting. These assumptions and source split provenance are not "
        "verified here; this is not conditional, interpolated-region, or production-population coverage.")
    return {"status": "AVAILABLE", "method": method,
            "calibration_unit_count": count, "metric_count": len(metrics),
            "familywise_alpha": alpha, "per_metric_alpha": per_metric_alpha,
            "order_statistic_rank": rank,
            "metric_quantiles": quantiles,
            **({"stratum_metric_quantiles": stratum_quantiles,
                "strata": declared_strata,
                "stratum_calibration_unit_counts": {
                    json.dumps(declared_stratum_keys[key], sort_keys=True): len(scores_by_stratum[key][metrics[0]])
                    for key in sorted(declared_stratum_keys)}} if declared_strata else {}),
            "observations_per_setting": expected_observations,
            "common_exact_settings": ordered_settings,
            "precommit": checked_plan["evidence"],
            "scope": ("one future independent unit within any predeclared stratum, across the complete common exact-setting panel and all declared constrained metrics"
                      if declared_strata else
                      "one future independent unit across the complete common exact-setting panel and all declared constrained metrics"),
            "assumption_conditional_statement": assumption,
            "limitations": ["exact calibration-observed settings and precommitted observation counts only; no interpolation or extrapolation",
                           ("does not establish coverage conditional on settings, factors within a stratum, or other covariates; target-population exchangeability remains unverified"
                            if declared_strata else
                            "does not establish conditional coverage or target-population exchangeability"),
                           "caller-supplied split and precommit references are unauthenticated; the exact plan bytes are hash-recorded"]}


def _wilson_interval(successes, trials, z=1.959963984540054):
    """Descriptive binomial interval for independent held-out engineering units."""
    if trials <= 0:
        return None
    proportion = successes / trials
    denominator = 1 + z*z/trials
    center = (proportion + z*z/(2*trials)) / denominator
    half_width = z * sqrt((proportion*(1-proportion) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half_width), min(1.0, center+half_width)]


def _evaluation_panel_compatibility(rows, unit_field, model_factors, setting_panel, observations_per_setting):
    """Report whether held-out units match the declared exact-panel row structure."""
    if not rows:
        return {"status": "NOT_PROVIDED", "evaluation_unit_count": 0,
                "matching_units": None, "mismatched_units": None, "unassignable_units": None,
                "expected_observations_per_setting": observations_per_setting,
                "interpretation": "no independent evaluation panel was provided"}
    panel_keys = {tuple(setting[name] for name in model_factors) for setting in setting_panel}
    counts_by_unit = {}
    invalid_units = set()
    evaluation_units = set()
    outside_panel_rows = 0
    for row in rows:
        try:
            unit = _unit_key(_get_field(row, unit_field))
        except (KeyError, TypeError, ValueError):
            continue
        evaluation_units.add(unit)
        try:
            factors = row["factors"]
            setting = tuple(factors[name] for name in model_factors)
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
                   for value in setting):
                raise ValueError("non-numeric setting")
        except (KeyError, TypeError, ValueError):
            invalid_units.add(unit)
            continue
        if setting not in panel_keys:
            outside_panel_rows += 1
            continue
        counts = counts_by_unit.setdefault(unit, {})
        counts[setting] = counts.get(setting, 0) + 1
    unassignable_unit_keys = (evaluation_units - set(counts_by_unit)) | invalid_units
    unassignable_units = len(unassignable_unit_keys)
    matching_units = 0
    mismatched_units = 0
    for unit, counts in counts_by_unit.items():
        if unit in invalid_units:
            continue
        matches = (set(counts) == panel_keys
                   and all(counts.get(setting, 0) == observations_per_setting for setting in panel_keys))
        matching_units += int(matches)
        mismatched_units += int(not matches)
    status = ("OBSERVED_PANEL_STRUCTURE_MISMATCH" if mismatched_units or unassignable_units
              else "DESCRIPTIVE_PANEL_STRUCTURE_MATCH" if matching_units else "INSUFFICIENT_EXACT_PANEL_UNITS")
    return {"status": status, "evaluation_unit_count": len(evaluation_units),
            "matching_units": matching_units, "mismatched_units": mismatched_units,
            "unassignable_units": unassignable_units,
            "expected_observations_per_setting": observations_per_setting,
            "outside_panel_rows": outside_panel_rows,
            "interpretation": (
                "descriptive comparison of held-out row counts with the declared exact-setting panel; "
                "a match does not establish exchangeability or future observation structure")}


def _evaluate_calibration_band_transfer(rows, unit_field, models, model_factors,
                                        fixed_effects, calibration, cancel=None):
    """Describe exact-panel interval misses on untouched independent evaluation units.

    Evaluation rows never change model fitting, calibration radii, or candidate
    selection. The reported rate is descriptive post-selection counterevidence,
    not a coverage validation or future-population estimate.
    """
    if not rows:
        return {"status": "NOT_PROVIDED", "evaluation_units": 0,
                "complete_panel_units": 0, "mismatched_panel_units": 0,
                "unscored_units": 0, "missed_any_interval_units": None,
                "missed_any_interval_fraction": None, "wilson95_descriptive_interval": None}
    if calibration.get("status") != "AVAILABLE":
        return {"status": "NOT_AVAILABLE_BAND_UNAVAILABLE",
                "reason": "an independent exact-panel calibration band is required to score evaluation outcomes",
                "evaluation_units": len({_unit_key(_get_field(row, unit_field)) for row in rows}),
                "complete_panel_units": 0, "mismatched_panel_units": 0,
                "unscored_units": 0, "missed_any_interval_units": None,
                "missed_any_interval_fraction": None, "wilson95_descriptive_interval": None}

    panel = calibration.get("common_exact_settings", [])
    quantiles = calibration.get("metric_quantiles", {})
    expected_observations = calibration.get("observations_per_setting")
    if (not panel or not isinstance(expected_observations, int) or isinstance(expected_observations, bool)
            or expected_observations < 1 or not models or not quantiles):
        return {"status": "NOT_AVAILABLE_INVALID_CALIBRATION_RESULT",
                "reason": "calibration output does not contain a complete exact-setting panel, metric radii, and row count",
                "evaluation_units": len({_unit_key(_get_field(row, unit_field)) for row in rows}),
                "complete_panel_units": 0, "mismatched_panel_units": 0,
                "unscored_units": 0, "missed_any_interval_units": None,
                "missed_any_interval_fraction": None, "wilson95_descriptive_interval": None}
    panel_keys = set()
    try:
        for setting in panel:
            panel_keys.add(tuple(float(setting[name]) for name in model_factors))
    except (KeyError, TypeError, ValueError):
        return {"status": "NOT_AVAILABLE_INVALID_CALIBRATION_RESULT",
                "reason": "the calibrated setting panel cannot be mapped to model factors",
                "evaluation_units": len({_unit_key(_get_field(row, unit_field)) for row in rows}),
                "complete_panel_units": 0, "mismatched_panel_units": 0,
                "unscored_units": 0, "missed_any_interval_units": None,
                "missed_any_interval_fraction": None, "wilson95_descriptive_interval": None}

    grouped = {}
    invalid_units = set()
    for row in rows:
        _check_cancel(cancel)
        try:
            unit = _unit_key(_get_field(row, unit_field))
            raw_setting = tuple(row["factors"][name] for name in model_factors)
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
                   for value in raw_setting):
                raise ValueError("invalid setting value")
            setting = tuple(float(value) for value in raw_setting)
        except (KeyError, TypeError, ValueError):
            invalid_units.add(str(row.get("id", "UNASSIGNABLE")))
            continue
        record = grouped.setdefault(unit, {})
        record.setdefault(setting, []).append(row)

    complete_units = 0
    mismatched_units = 0
    unscored_units = len(invalid_units)
    union_misses = 0
    metric_misses = {metric: 0 for metric in models}
    for setting_rows in grouped.values():
        _check_cancel(cancel)
        if (set(setting_rows) != panel_keys
                or any(len(setting_rows.get(setting, [])) != expected_observations for setting in panel_keys)):
            mismatched_units += 1
            continue
        unit_scored = True
        unit_missed_metrics = set()
        for setting, observations in setting_rows.items():
            for row in observations:
                for metric, model in models.items():
                    radius_record = quantiles.get(metric)
                    radius = radius_record.get("absolute_error_radius") if isinstance(radius_record, dict) else None
                    value = row.get("metrics", {}).get(metric)
                    if (not isinstance(radius, (int, float)) or isinstance(radius, bool) or not isfinite(radius)
                            or isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)):
                        unit_scored = False
                        continue
                    prediction = model.predict(row["factors"], fixed_effects)
                    estimate = prediction.get("estimate")
                    if not isinstance(estimate, (int, float)) or not isfinite(estimate):
                        unit_scored = False
                        continue
                    if abs(float(value)-float(estimate)) > float(radius):
                        unit_missed_metrics.add(metric)
        if not unit_scored:
            unscored_units += 1
            continue
        complete_units += 1
        if unit_missed_metrics:
            union_misses += 1
            for metric in unit_missed_metrics:
                metric_misses[metric] += 1

    if complete_units:
        status = "DESCRIPTIVE_HELDOUT_BAND_EVALUATION"
        signal = "OBSERVED_CALIBRATION_BAND_MISSES" if union_misses else "NO_MISSES_OBSERVED_NOT_VALIDATION"
    else:
        status = "INSUFFICIENT_COMPLETE_EVALUATION_UNITS"
        signal = "NOT_ASSESSED"
    return {"status": status, "transfer_signal": signal,
            "evaluation_units": len(grouped) + len(invalid_units),
            "complete_panel_units": complete_units,
            "mismatched_panel_units": mismatched_units,
            "unscored_units": unscored_units,
            "missed_any_interval_units": union_misses if complete_units else None,
            "missed_any_interval_fraction": union_misses/complete_units if complete_units else None,
            "wilson95_descriptive_interval": _wilson_interval(union_misses, complete_units),
            "metric_missed_units": {metric: count for metric, count in metric_misses.items()},
            "method": "post-selection exact-setting panel comparison using each independent evaluation unit's maximum deviation across settings, replicates, and metrics",
            "interpretation": "observed held-out interval misses are transfer counterevidence; zero observed misses do not validate exchangeability, conditional coverage, or future-population coverage",
            "candidate_selection_influence": False,
            "coverage_guarantee": "none; descriptive held-out counterevidence only"}


def _calibration_transfer_assessment(calibration_status, evaluation_panel, composition,
                                     evaluation_provided, calibration_partition_name=None,
                                     evaluation_partition_name=None, band_evaluation=None,
                                     predeclared_evaluation_strata=None):
    """Describe held-out counterevidence to transferring exact-panel calibration.

    This is post-screening evidence. It cannot change model fitting, calibration
    radii, or select a favorable subset; identified transfer counterevidence can
    only withdraw the complete candidate set.
    """
    partition_summaries = composition.get("partitions", {})
    relevant_partitions = (calibration_partition_name, evaluation_partition_name)
    unassignable_strata_units = {
        name: partition_summaries.get(name, {}).get(
            "unassignable_units_missing_or_mixed_strata", 0)
        for name in relevant_partitions if name in partition_summaries
    }
    result = {
        "status": "NOT_EVALUATED" if not evaluation_provided else "NOT_ASSESSED",
        "observed_counterevidence": [],
        "evaluation_panel_status": evaluation_panel.get("status"),
        "unseen_evaluation_strata_count": composition.get("evaluation_strata_absent_from_calibration_count"),
        "unseen_evaluation_units": composition.get("evaluation_units_in_strata_absent_from_calibration"),
        "unassignable_strata_units": unassignable_strata_units,
        "calibration_to_evaluation_total_variation": None,
        "heldout_band_evaluation": band_evaluation or {"status": "NOT_ASSESSED"},
        "predeclared_strata_compatibility": predeclared_evaluation_strata or {"status": "NOT_DECLARED"},
    }
    if not evaluation_provided:
        result["interpretation"] = (
            "no independent evaluation data were supplied; transfer to a future population is unverified")
        return result
    if calibration_status != "AVAILABLE":
        result["status"] = "CALIBRATION_BAND_UNAVAILABLE"
        result["interpretation"] = (
            "the precommitted finite-panel band is unavailable, so transfer cannot be assessed")
        return result

    strata_status = (predeclared_evaluation_strata or {}).get("status")
    if strata_status == "UNPLANNED_CATEGORIES_OBSERVED":
        result["observed_counterevidence"].append("UNSEEN_PRECOMMITTED_EVALUATION_STRATA")
    elif strata_status == "UNASSIGNABLE_OR_MIXED_UNITS":
        result["observed_counterevidence"].append("UNASSIGNABLE_PRECOMMITTED_EVALUATION_STRATA")

    if evaluation_panel.get("status") == "OBSERVED_PANEL_STRUCTURE_MISMATCH":
        result["observed_counterevidence"].append("OBSERVED_PANEL_STRUCTURE_MISMATCH")
    elif evaluation_panel.get("status") != "DESCRIPTIVE_PANEL_STRUCTURE_MATCH":
        result["observed_counterevidence"].append("EVALUATION_PANEL_STRUCTURE_NOT_ESTABLISHED")

    if any(count > 0 for count in unassignable_strata_units.values()):
        result["observed_counterevidence"].append("INSUFFICIENT_ASSIGNABLE_STRATA")

    if composition.get("evaluation_partition_status") == "DESCRIPTIVE":
        comparison = next((item for item in composition.get("comparisons", [])
                           if item.get("from_partition") == calibration_partition_name
                           and item.get("to_partition") == evaluation_partition_name), None)
        distance = comparison.get("categorical_total_variation_distance") if comparison else None
        result["calibration_to_evaluation_total_variation"] = distance
        unseen_count = composition.get("evaluation_strata_absent_from_calibration_count")
        if isinstance(unseen_count, int) and unseen_count > 0:
            result["observed_counterevidence"].append("UNSEEN_EVALUATION_STRATA")
        elif distance is None:
            result["observed_counterevidence"].append("INSUFFICIENT_ASSIGNABLE_STRATA")
        elif distance > 0:
            result["observed_counterevidence"].append("DESCRIPTIVE_COMPOSITION_DIFFERENCE")
    elif composition.get("status") == "NOT_REQUESTED":
        result["observed_counterevidence"].append("POPULATION_STRATA_NOT_DECLARED")
    elif composition.get("evaluation_partition_status") == "INSUFFICIENT_ASSIGNABLE_UNITS":
        result["observed_counterevidence"].append("INSUFFICIENT_ASSIGNABLE_STRATA")
    else:
        result["observed_counterevidence"].append("EVALUATION_STRATA_NOT_ESTABLISHED")

    if ((band_evaluation or {}).get("transfer_signal") == "OBSERVED_CALIBRATION_BAND_MISSES"):
        result["observed_counterevidence"].append("OBSERVED_CALIBRATION_BAND_MISSES")

    evidence = result["observed_counterevidence"]
    if "OBSERVED_CALIBRATION_BAND_MISSES" in evidence:
        result["status"] = "COUNTEREVIDENCE_CALIBRATION_BAND_MISSES"
    elif "UNSEEN_EVALUATION_STRATA" in evidence or "UNSEEN_PRECOMMITTED_EVALUATION_STRATA" in evidence:
        result["status"] = "COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA"
    elif "UNASSIGNABLE_PRECOMMITTED_EVALUATION_STRATA" in evidence:
        result["status"] = "COUNTEREVIDENCE_UNASSIGNABLE_EVALUATION_STRATA"
    elif "OBSERVED_PANEL_STRUCTURE_MISMATCH" in evidence:
        result["status"] = "COUNTEREVIDENCE_PANEL_STRUCTURE_MISMATCH"
    elif "DESCRIPTIVE_COMPOSITION_DIFFERENCE" in evidence:
        result["status"] = "DESCRIPTIVE_COMPOSITION_DIFFERENCE_OBSERVED"
    elif "INSUFFICIENT_ASSIGNABLE_STRATA" in evidence or "EVALUATION_STRATA_NOT_ESTABLISHED" in evidence:
        result["status"] = "INSUFFICIENT_TRANSFER_DIAGNOSTICS"
    elif "POPULATION_STRATA_NOT_DECLARED" in evidence:
        result["status"] = "NOT_ASSESSED_NO_STRATA_DECLARED"
    elif "EVALUATION_PANEL_STRUCTURE_NOT_ESTABLISHED" in evidence:
        result["status"] = "INSUFFICIENT_TRANSFER_DIAGNOSTICS"
    else:
        result["status"] = "DESCRIPTIVE_MATCH_NO_TRANSFER_VALIDATION"
    if result["status"].startswith("COUNTEREVIDENCE"):
        result["interpretation"] = (
            "observed evaluation data provide counterevidence to transferring calibration across the declared strata or panel structure; "
            "candidate selection remains frozen, and this does not estimate future-population coverage")
    elif result["status"] == "DESCRIPTIVE_MATCH_NO_TRANSFER_VALIDATION":
        result["interpretation"] = (
            "no difference was detected by these descriptive checks; this is not validation of exchangeability or future-population coverage")
    else:
        result["interpretation"] = (
            "available evaluation data are insufficient to assess calibration transfer; no future-population coverage claim is made")
    return result


def _evaluate_selected_cells(candidates, evaluation_rows, selected, constrained, unit_field,
                             fixed_settings=None, strata_fields=()):
    """Evaluate only exact candidate settings on an untouched whole-unit partition.

    This is a descriptive engineering diagnostic. It cannot establish population,
    conditional, or simultaneous coverage and never changes candidate selection.
    """
    if not evaluation_rows:
        return {"status": "NOT_PROVIDED", "evaluated_candidate_count": 0,
                "unevaluated_candidate_count": len(candidates), "candidates": [],
                "candidate_selection_audit": {"status": "NOT_PROVIDED", "candidate_count": len(candidates),
                                               "complete_independent_units": 0,
                                               "observed_any_infeasible_units": None,
                                               "observed_any_infeasible_fraction": None,
                                               "wilson95_descriptive_interval": None},
                "method": "exact-setting independent-unit feasibility diagnostic; no population or simultaneous guarantee"}
    evaluated = []
    unevaluated = 0
    candidate_unit_outcomes = []
    strata_fields = list(strata_fields)
    fixed_conditions = {name: value for name, value in (fixed_settings or {}).items()
                        if name not in selected}
    for candidate in candidates:
        factors = candidate["factors"]
        selected_rows = [row for row in evaluation_rows
                         if all(row["factors"].get(name) == factors.get(name) for name in selected)]
        exact_rows = []
        population_incompatible_units = set()
        for row in selected_rows:
            unit = _unit_key(_get_field(row, unit_field))
            if any(row["factors"].get(name) != value for name, value in fixed_conditions.items()):
                population_incompatible_units.add(unit)
            else:
                exact_rows.append(row)
        by_unit = {}
        for row in exact_rows:
            unit = _unit_key(_get_field(row, unit_field))
            record = by_unit.setdefault(unit, {"observations": [], "missing_metric": False,
                                                "strata": {}, "missing_stratum": False})
            if strata_fields:
                try:
                    stratum_values = {field: _get_field(row, field) for field in strata_fields}
                    if any(not isinstance(value, (str, int, float, bool, type(None)))
                           or (isinstance(value, float) and not isfinite(value)) for value in stratum_values.values()):
                        record["missing_stratum"] = True
                    else:
                        stratum_key = tuple(_unit_key(stratum_values[field]) for field in strata_fields)
                        record["strata"][stratum_key] = stratum_values
                except (KeyError, ValueError):
                    record["missing_stratum"] = True
            observation = {}
            for metric in constrained:
                value = row.get("metrics", {}).get(metric)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                    observation[metric] = float(value)
                else:
                    record["missing_metric"] = True
            record["observations"].append(observation)
        unit_passes = []
        unit_outcomes = {}
        unscored_units = 0
        stratum_outcomes = {}
        unassignable_strata_units = 0
        for unit, values in by_unit.items():
            if values["missing_metric"] or any(
                    any(metric not in observation for metric in constrained)
                    for observation in values["observations"]):
                unscored_units += 1
                continue
            # Preserve the observation grain: a lot fails this diagnostic if any
            # measured outcome at the proposed setting crosses a supplied limit.
            passed = all(_metric_pass(observation[metric], definition)
                         for observation in values["observations"]
                         for metric, definition in constrained.items())
            unit_passes.append(passed)
            unit_outcomes[unit] = passed
            if strata_fields:
                if values["missing_stratum"] or len(values["strata"]) != 1:
                    unassignable_strata_units += 1
                else:
                    stratum_key, stratum_values = next(iter(values["strata"].items()))
                    bucket = stratum_outcomes.setdefault(stratum_key, {"values": stratum_values, "passes": []})
                    bucket["passes"].append(passed)
        if not unit_passes:
            unevaluated += 1
            candidate_unit_outcomes.append(unit_outcomes)
            evaluated.append({"factors": factors, "independent_units": 0,
                              "unscored_units_with_missing_outcomes": unscored_units,
                              "population_incompatible_units": len(population_incompatible_units),
                              "observed_infeasible_units": None,
                              "observed_infeasible_fraction": None,
                              "wilson95_descriptive_interval": None,
                              "stratified_evaluation": {"status": "NOT_ESTIMABLE", "fields": strata_fields,
                                                         "categories": [],
                                                         "units_with_missing_or_mixed_strata": 0},
                              "status": "NO_EXACT_SETTING_EVALUATION_DATA" if not exact_rows
                                        else "NO_SCORABLE_EXACT_SETTING_OUTCOMES"})
            continue
        candidate_unit_outcomes.append(unit_outcomes)
        violations = sum(not passed for passed in unit_passes)
        strata = {"status": "NOT_REQUESTED", "fields": [], "categories": [],
                  "units_with_missing_or_mixed_strata": 0}
        if strata_fields:
            categories = []
            for bucket in sorted(stratum_outcomes.values(), key=lambda item: tuple(str(item["values"][field]) for field in strata_fields)):
                failures = sum(not passed for passed in bucket["passes"])
                categories.append({"values": bucket["values"], "independent_units": len(bucket["passes"]),
                    "observed_infeasible_units": failures,
                    "observed_infeasible_fraction": failures/len(bucket["passes"]),
                    "wilson95_descriptive_interval": _wilson_interval(failures, len(bucket["passes"]))})
            strata = {"status": "DESCRIPTIVE", "fields": strata_fields, "categories": categories,
                      "units_with_missing_or_mixed_strata": unassignable_strata_units,
                      "method": "exact-setting held-out unit outcomes grouped by caller-declared strata; descriptive only"}
        evaluated.append({"factors": factors, "independent_units": len(unit_passes),
                          "unscored_units_with_missing_outcomes": unscored_units,
                          "population_incompatible_units": len(population_incompatible_units),
                          "observed_infeasible_units": violations,
                          "observed_infeasible_fraction": violations / len(unit_passes),
                          "wilson95_descriptive_interval": _wilson_interval(violations, len(unit_passes)),
                          "stratified_evaluation": strata,
                          "status": "DESCRIPTIVE_HELDOUT_DIAGNOSTIC"})
    scored = len(evaluated) - unevaluated
    complete_units = (set.intersection(*(set(outcomes) for outcomes in candidate_unit_outcomes))
                      if candidate_unit_outcomes and candidates else set())
    any_infeasible = sum(any(not outcomes[unit] for outcomes in candidate_unit_outcomes)
                         for unit in complete_units)
    selection_audit = {"status": "DESCRIPTIVE_SETWISE_DIAGNOSTIC" if complete_units
                       else "INSUFFICIENT_COMPLETE_SET_EVALUATION",
                       "candidate_count": len(candidates),
                       "complete_independent_units": len(complete_units),
                       "observed_any_infeasible_units": any_infeasible if complete_units else None,
                       "observed_any_infeasible_fraction": any_infeasible/len(complete_units) if complete_units else None,
                       "wilson95_descriptive_interval": _wilson_interval(any_infeasible, len(complete_units)),
                       "method": "fraction of independent held-out units infeasible at one or more selected candidate settings; exact outcomes at every selected setting required",
                       "guarantee": "none; descriptive only and not a multiplicity-adjusted or population guarantee"}
    return {"status": "DESCRIPTIVE" if scored else "INSUFFICIENT_EXACT_SETTING_DATA",
            "evaluated_candidate_count": scored, "unevaluated_candidate_count": unevaluated,
            "evaluation_unit_count": len({_unit_key(_get_field(row, unit_field)) for row in evaluation_rows}),
            "candidates": evaluated, "candidate_selection_audit": selection_audit,
            "method": "exact-setting independent-unit diagnostic; a unit is infeasible if any observed row violates a supplied limit; missing-outcome units are unscored; Wilson intervals are descriptive and do not establish population, conditional, or simultaneous coverage"}


def _partition_composition_diagnostic(partitions, unit_field, strata_fields,
                                     calibration_partition_name=None, evaluation_partition_name=None):
    """Describe declared population-stratum support across fitting/calibration/evaluation units.

    This is an overlap diagnostic, not a statistical test or an exchangeability certificate.
    It uses one category per independent unit and marks units with missing or changing
    strata as unassignable instead of counting their rows as independent evidence.
    """
    if not strata_fields:
        return {"status": "NOT_REQUESTED", "fields": [], "partitions": {}, "comparisons": [],
                "evaluation_partition_status": "NOT_REQUESTED",
                "evaluation_strata_absent_from_calibration_count": None,
                "evaluation_units_in_strata_absent_from_calibration": None,
                "unseen_evaluation_strata": None,
                "unseen_evaluation_strata_truncated": None,
                "interpretation": "no population strata were declared"}

    summaries = {}
    category_counts = {}
    for partition_name, rows in partitions.items():
        by_unit = {}
        for row in rows:
            try:
                unit = _unit_key(_get_field(row, unit_field))
            except (KeyError, ValueError):
                # The main split validator normally catches this. Retain a fail-closed
                # diagnostic if a future caller bypasses it.
                continue
            item = by_unit.setdefault(unit, {"signatures": {}, "invalid": False})
            values = {}
            valid = True
            for field in strata_fields:
                try:
                    value = _get_field(row, field)
                except (KeyError, ValueError):
                    valid = False
                    break
                if (not isinstance(value, (str, int, float, bool)) or value is None
                        or (isinstance(value, float) and not isfinite(value))):
                    valid = False
                    break
                values[field] = value
            if not valid:
                item["invalid"] = True
                continue
            signature = tuple(_unit_key(values[field]) for field in strata_fields)
            item["signatures"].setdefault(signature, values)

        counts = {}
        unassignable = 0
        for item in by_unit.values():
            if item["invalid"] or len(item["signatures"]) != 1:
                unassignable += 1
                continue
            signature, values = next(iter(item["signatures"].items()))
            counts.setdefault(signature, {"values": values, "independent_units": 0})["independent_units"] += 1
        assigned = sum(item["independent_units"] for item in counts.values())
        categories = [
            {"values": item["values"], "independent_units": item["independent_units"],
             "fraction_of_assignable_units": item["independent_units"] / assigned if assigned else None}
            for _, item in sorted(counts.items())
        ]
        summaries[partition_name] = {
            "independent_units": len(by_unit), "assignable_units": assigned,
            "unassignable_units_missing_or_mixed_strata": unassignable,
            "stratum_count": len(counts), "categories": categories[:100],
            "categories_truncated": len(categories) > 100,
        }
        category_counts[partition_name] = counts

    comparisons = []
    names = list(partitions)
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1:]:
            left = category_counts.get(left_name, {})
            right = category_counts.get(right_name, {})
            left_n = sum(item["independent_units"] for item in left.values())
            right_n = sum(item["independent_units"] for item in right.values())
            if not left_n or not right_n:
                distance = None
            else:
                keys = set(left) | set(right)
                distance = 0.5 * sum(abs(left.get(key, {}).get("independent_units", 0) / left_n
                                         - right.get(key, {}).get("independent_units", 0) / right_n)
                                     for key in keys)
            comparisons.append({"from_partition": left_name, "to_partition": right_name,
                                "categorical_total_variation_distance": distance,
                                "status": "DESCRIPTIVE" if distance is not None else "INSUFFICIENT_ASSIGNABLE_UNITS"})

    unseen = None
    unseen_units = None
    unseen_stratum_count = None
    evaluation_partition_status = "NOT_PROVIDED"
    if evaluation_partition_name and calibration_partition_name:
        calibration = category_counts.get(calibration_partition_name, {})
        evaluation = category_counts.get(evaluation_partition_name, {})
        calibration_n = sum(item["independent_units"] for item in calibration.values())
        evaluation_n = sum(item["independent_units"] for item in evaluation.values())
        if calibration_n and evaluation_n:
            evaluation_partition_status = "DESCRIPTIVE"
            unseen_items = [(key, item) for key, item in sorted(evaluation.items()) if key not in calibration]
            unseen_stratum_count = len(unseen_items)
            unseen_units = sum(item["independent_units"] for _, item in unseen_items)
            unseen = [{"values": item["values"], "independent_units": item["independent_units"]}
                      for _, item in unseen_items[:100]]
        else:
            evaluation_partition_status = "INSUFFICIENT_ASSIGNABLE_UNITS"
    status = "INCOMPLETE" if any(summary["unassignable_units_missing_or_mixed_strata"] > 0
                                  for summary in summaries.values()) else "DESCRIPTIVE"
    return {"status": status, "fields": list(strata_fields), "partitions": summaries,
            "comparisons": comparisons,
            "evaluation_partition_status": evaluation_partition_status,
            "evaluation_strata_absent_from_calibration_count": unseen_stratum_count,
            "evaluation_units_in_strata_absent_from_calibration": unseen_units,
            "unseen_evaluation_strata": unseen,
            "unseen_evaluation_strata_truncated": len(unseen) > 100 if unseen is not None else None,
            "interpretation": (
                "Per-unit categorical composition and total-variation distances are descriptive only, not a test of exchangeability. "
                "Evaluation strata absent from calibration are counterevidence to transferring calibration results to those strata; "
                "matching observed strata does not establish future-population exchangeability.")}


def _inside_forbidden(factors, regions):
    """Fail closed on malformed exclusions; bounds are inclusive."""
    if not isinstance(regions, list):
        raise WindowError("forbidden_regions must be a list")
    for region in regions:
        if not isinstance(region, dict) or not region:
            raise WindowError("each forbidden region must be a nonempty factor-to-range map")
        matches = True
        for name, bound in region.items():
            if name not in factors:
                raise WindowError(f"unknown factor in forbidden region: {name}")
            limits = bound if isinstance(bound, (list, tuple)) and len(bound) == 2 else [bound, bound]
            if (any(not isinstance(v, (int, float)) or isinstance(v, bool) or not isfinite(v) for v in limits)
                    or limits[0] > limits[1]):
                raise WindowError("forbidden-region bounds must be finite and ordered")
            matches = matches and limits[0] <= factors[name] <= limits[1]
        if matches:
            return True
    return False


def explore_window(rows, factor_defs, metric_defs, data, cancel=None):
    """Map only bounded, sufficiently supported candidate regions.

    One- and two-dimensional grids are classified as observed, interpolated,
    extrapolated, unsupported, or forbidden. Only observed/interpolated cells
    whose local, grouped-holdout empirical intervals satisfy every specification
    limit can be proposed as supported candidates. A finite 95% order-statistic
    rank is not a conditional-coverage guarantee or recipe approval.
    """
    spec = data.get("window_exploration", {})
    if not isinstance(spec, dict):
        raise WindowError("window_exploration must be an object")
    controllable = [name for name, definition in factor_defs.items()
                    if definition.get("role", "controllable") == "controllable"]
    selected = spec.get("factors", controllable if len(controllable) <= 2 else [])
    if not isinstance(selected, list) or not 1 <= len(selected) <= 2 or len(set(selected)) != len(selected):
        return {"status": "UNSUPPORTED_DIMENSION", "reason": "supported response-surface exploration currently requires one or two explicitly selected continuous factors",
                "grid": [], "candidate_cells": []}
    if any(not isinstance(name, str) or name not in controllable for name in selected):
        raise WindowError("window factors must be approved controllable factor definitions")
    bounds = {}
    for name in selected:
        bounds[name] = factor_defs[name].get("bounds")
        if (factor_defs[name].get("approved") is not True or not isinstance(bounds[name], (list, tuple))
                or len(bounds[name]) != 2 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not isfinite(v) for v in bounds[name])
                or bounds[name][0] >= bounds[name][1]):
            return {"status": "REFUSED", "reason": f"explicit approved bounds are required for {name}",
                    "grid": [], "candidate_cells": []}
        bounds[name] = [float(v) for v in bounds[name]]

    configured_settings = spec.get("fixed_settings", {})
    if not isinstance(configured_settings, dict):
        raise WindowError("fixed_settings must be an object")
    fixed_settings = dict(configured_settings)
    for name in controllable:
        if name in selected:
            continue
        value = fixed_settings.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return {"status": "REFUSED", "reason": f"explicit fixed setting is required for non-explored factor {name}",
                    "grid": [], "candidate_cells": []}
        approved = factor_defs[name].get("bounds")
        if (factor_defs[name].get("approved") is not True or not isinstance(approved, (list, tuple))
                or len(approved) != 2 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not isfinite(v) for v in approved)
                or not isfinite(value) or not approved[0] <= value <= approved[1]):
            return {"status": "REFUSED", "reason": f"fixed setting for {name} is outside its approved bounds", "grid": [], "candidate_cells": []}
        fixed_settings[name] = float(value)

    options = data.get("model", {})
    if not isinstance(options, dict):
        raise WindowError("model must be an object")
    fixed_effects = spec.get("fixed_effects", {})
    if not isinstance(fixed_effects, dict):
        raise WindowError("fixed_effects must be an object")
    model_factors = options.get("factor_fields", [name for name, f in factor_defs.items()
                                                   if f.get("role", "controllable") in ("controllable", "measured")])
    if not isinstance(model_factors, list) or any(not isinstance(name, str) or name not in factor_defs for name in model_factors):
        raise WindowError("model.factor_fields must name defined factors")
    if any(name not in model_factors for name in selected):
        return {"status": "INCONCLUSIVE", "reason": "selected window factors are absent from the response model",
                "grid": [], "candidate_cells": []}
    for name in model_factors:
        if name not in selected and name not in fixed_settings:
            values = {row["factors"][name] for row in rows}
            if len(values) != 1:
                return {"status": "REFUSED", "reason": f"numeric covariate {name} must be fixed explicitly for window exploration",
                        "grid": [], "candidate_cells": []}
            fixed_settings[name] = next(iter(values))
    category_fields = options.get("fixed_effect_fields", [])
    if not isinstance(category_fields, list) or any(not isinstance(field, str) or not field for field in category_fields):
        raise WindowError("model.fixed_effect_fields must be a list of field paths")
    for field in category_fields:
        if field not in fixed_effects:
            return {"status": "REFUSED", "reason": f"fixed effect level for {field} must be selected explicitly",
                    "grid": [], "candidate_cells": []}

    unit_field = spec.get("independent_unit_field") or options.get("cluster_field") or data.get("robustness", {}).get("independent_unit_field")
    if not isinstance(unit_field, str) or not unit_field:
        return {"status": "INCONCLUSIVE", "reason": "an independent-unit field is required to assess local support",
                "grid": [], "candidate_cells": []}
    minimum_units = spec.get("min_independent_units", 30)
    if not isinstance(minimum_units, int) or isinstance(minimum_units, bool) or minimum_units < 3:
        raise WindowError("min_independent_units must be an integer of at least 3")
    resolution = spec.get("grid_points", 21)
    if not isinstance(resolution, int) or isinstance(resolution, bool) or not 5 <= resolution <= 41:
        raise WindowError("grid_points must be an integer from 5 to 41")
    min_support_points = spec.get("min_support_points", 3)
    radius = spec.get("max_support_radius", 0.65)
    if not isinstance(min_support_points, int) or isinstance(min_support_points, bool) or min_support_points < 2:
        raise WindowError("min_support_points must be an integer of at least 2")
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or not 0 < radius <= 2:
        raise WindowError("max_support_radius must be in (0, 2]")
    calibration_config = spec.get("calibration")
    if not isinstance(calibration_config, dict):
        return {"status": "INCONCLUSIVE", "reason": "a grouped held-out calibration split is required for D02 uncertainty",
                "grid": [], "candidate_cells": []}
    minimum_calibration_units = calibration_config.get("minimum_calibration_units", 19)
    if (not isinstance(minimum_calibration_units, int) or isinstance(minimum_calibration_units, bool)
            or minimum_calibration_units < 19):
        raise WindowError("minimum_calibration_units must be at least 19 for a finite 95% order-statistic rank")
    evaluation_strata = spec.get("evaluation_strata", [])
    if not isinstance(evaluation_strata, list) or any(not isinstance(field, str) or not field for field in evaluation_strata):
        raise WindowError("evaluation_strata must be a unique list of explicit source field names")
    if len(evaluation_strata) != len(set(evaluation_strata)):
        raise WindowError("evaluation_strata must be a unique list of explicit source field names")
    if len(evaluation_strata) > 5:
        raise WindowError("evaluation_strata may declare at most five fields to keep population diagnostics bounded")

    # Any controllable omitted from the response model must be held exactly at
    # its declared setting; otherwise its uncontrolled effect could be
    # mistaken for the explored response surface.
    omitted_controls = [name for name in controllable if name not in model_factors and name not in selected]
    eligible_rows = []
    for row in rows:
        _check_cancel(cancel)
        try:
            if (all(_get_field(row, field) == fixed_effects[field] for field in category_fields)
                    and all(row["factors"].get(name) == fixed_settings[name] for name in omitted_controls)):
                _ = _get_field(row, unit_field)
                eligible_rows.append(row)
        except (KeyError, ValueError):
            continue
    matching_rows, calibration_rows, calibration_report, evaluation_rows = _split_calibration(
        eligible_rows, unit_field, calibration_config, minimum_calibration_units)
    if matching_rows is None:
        return {"status": "INCONCLUSIVE", "reason": calibration_rows, "grid": [], "candidate_cells": []}
    training_unit_count = len({_unit_key(_get_field(row, unit_field)) for row in matching_rows})
    if training_unit_count < minimum_units:
        return {"status": "INCONCLUSIVE", "reason": "the selected population has fewer than the required independent units",
                "independent_unit_field": unit_field, "independent_units": training_unit_count,
                "minimum_independent_units": minimum_units, "grid": [], "candidate_cells": []}

    unit_values = [_unit_key(_get_field(row, unit_field)) for row in matching_rows]
    repeated_units = len(set(unit_values)) < len(unit_values)
    covariance_type = options.get("covariance", "HC3")
    cluster_field = options.get("cluster_field")
    if repeated_units and (covariance_type != "cluster" or cluster_field != unit_field):
        return {"status": "INCONCLUSIVE",
                "reason": "repeated independent units require cluster-robust uncertainty clustered on the same declared unit",
                "independent_unit_field": unit_field, "model_covariance": covariance_type,
                "model_cluster_field": cluster_field, "grid": [], "candidate_cells": []}

    unique_settings = {tuple(row["factors"][name] for name in selected) for row in matching_rows}
    if len(unique_settings) < (3 if len(selected) == 2 else 3):
        return {"status": "INCONCLUSIVE", "reason": "at least three distinct observed settings are required to establish interpolation support",
                "distinct_settings": len(unique_settings), "grid": [], "candidate_cells": []}
    target_ranges = {name: [min(v[i] for v in unique_settings), max(v[i] for v in unique_settings)]
                     for i, name in enumerate(selected)}
    extrapolation_present = any(bounds[name][0] < target_ranges[name][0] or bounds[name][1] > target_ranges[name][1] for name in selected)
    normalized_settings = [tuple((setting[i]-target_ranges[name][0])/(target_ranges[name][1]-target_ranges[name][0])
                                 for i, name in enumerate(selected)) for setting in unique_settings]
    hull = _hull(normalized_settings) if len(selected) == 2 else []
    if len(selected) == 2 and len(hull) < 3:
        return {"status": "INCONCLUSIVE", "reason": "observed settings do not span a two-dimensional supported region",
                "distinct_settings": len(unique_settings), "grid": [], "candidate_cells": []}

    constrained = {name: definition for name, definition in metric_defs.items()
                   if definition.get("min") is not None or definition.get("max") is not None}
    if not constrained:
        return {"status": "REFUSED", "reason": "at least one metric specification bound is required",
                "grid": [], "candidate_cells": []}
    fitted = {}
    fit_reports = {}
    calibration_scores = {}
    calibration_report["minimum_local_calibration_units"] = minimum_calibration_units
    for metric in constrained:
        _check_cancel(cancel)
        # Estimate the surface in the exact selected fixed-effect population.
        # This avoids borrowing slope information from unrelated products or
        # chambers unless the engineer explicitly defines a broader analysis.
        fit_reports[metric], fitted[metric], calibration_scores[metric] = _fit_grouped_calibration(
            matching_rows, calibration_rows, factor_defs, metric, options, fixed_effects, unit_field, cancel)
        if fitted[metric] is None or fit_reports[metric].get("status") != "VALID":
            return {"status": "INCONCLUSIVE", "reason": f"uncertainty for constrained metric {metric} is not estimable",
                    "model_diagnostics": fit_reports, "grid": [], "candidate_cells": []}

    simultaneous_calibration = _simultaneous_exact_setting_calibration(
        calibration_rows, list(constrained), fitted, model_factors, fixed_effects, unit_field,
        calibration_config.get("precommit"),
        {name: {"min": definition.get("min"), "max": definition.get("max")}
         for name, definition in constrained.items()})
    declared_strata, _strata_error = _normalize_precommit_strata(
        calibration_config.get("precommit", {}).get("strata")
        if isinstance(calibration_config.get("precommit"), dict) else None)
    calibration_population_strata = _predeclared_strata_compatibility(
        matching_rows + calibration_rows, unit_field, declared_strata)
    evaluation_predeclared_strata = _predeclared_strata_compatibility(
        evaluation_rows, unit_field, declared_strata)
    if (declared_strata and simultaneous_calibration.get("status") == "AVAILABLE"
            and calibration_population_strata.get("status") != "MATCHED_PREDECLARED_CATEGORIES"):
        simultaneous_calibration = {
            **simultaneous_calibration,
            "status": "INVALID_CALIBRATION_STRATA",
            "reason": "training and calibration units must all belong to one predeclared stratum before a stratified band can be used",
            "calibration_population_strata_compatibility": calibration_population_strata,
            "common_exact_settings": [], "metric_quantiles": {},
        }
    simultaneous_setting_keys = {
        tuple(setting[name] for name in model_factors)
        for setting in simultaneous_calibration.get("common_exact_settings", [])
    }

    axes = [[float(bounds[name][0]) + i*(bounds[name][1]-bounds[name][0])/(resolution-1)
             for i in range(resolution)] for name in selected]
    grid = []
    candidates = []
    forbidden = data.get("forbidden_regions", [])
    unit_values_by_setting = {}
    support_ranges = {name: [min(row["factors"][name] for row in matching_rows),
                             max(row["factors"][name] for row in matching_rows)]
                      for name in model_factors}
    def normalized_model_point(factor_values):
        point = []
        for name in model_factors:
            lo, hi = support_ranges[name]
            point.append((factor_values[name]-lo)/(hi-lo) if hi > lo else 0.0)
        return tuple(point)
    for row in matching_rows:
        setting = tuple(row["factors"][name] for name in selected)
        unit_values_by_setting.setdefault(setting, set()).add(str(_get_field(row, unit_field)))
    norm_rows = []
    for row in matching_rows:
        norm_rows.append((row, normalized_model_point(row["factors"])))
    norm_calibration_rows = [(row, normalized_model_point(row["factors"])) for row in calibration_rows]
    for values in product(*axes):
        _check_cancel(cancel)
        settings = dict(fixed_settings)
        settings.update(dict(zip(selected, values)))
        target = normalized_model_point(settings)
        target_projection = tuple((values[i]-target_ranges[name][0])/(target_ranges[name][1]-target_ranges[name][0])
                                  for i, name in enumerate(selected))
        exact_settings = tuple(values)
        exact_rows = [row for row in matching_rows
                      if tuple(row["factors"][name] for name in selected) == exact_settings
                      and all(row["factors"].get(name) == fixed_settings.get(name, row["factors"].get(name))
                              for name in model_factors if name not in selected)]
        is_supported_hull = (target_ranges[selected[0]][0] <= values[0] <= target_ranges[selected[0]][1]
                             and (len(selected) == 1 or _inside_polygon(target_projection, hull)))
        distances = sorted(((sqrt(sum((a-b)**2 for a, b in zip(target, observed))), index, row)
                            for index, (row, observed) in enumerate(norm_rows)), key=lambda item: (item[0], item[1]))
        nearest = distances[0][0] if distances else None
        near_rows = [row for distance, _index, row in distances if distance <= radius]
        near_settings = {tuple(row["factors"][name] for name in selected) for row in near_rows}
        local_units = {_unit_key(_get_field(row, unit_field)) for row in near_rows}
        near_calibration_rows = [row for row, point in norm_calibration_rows
                                 if sqrt(sum((a-b)**2 for a, b in zip(target, point))) <= radius]
        near_calibration_settings = {tuple(row["factors"][name] for name in selected)
                                     for row in near_calibration_rows}
        local_calibration_units = {_unit_key(_get_field(row, unit_field)) for row in near_calibration_rows}
        if exact_rows:
            region_class = "observed"
        elif not is_supported_hull:
            region_class = "extrapolated"
        elif len(near_settings) < min_support_points or len(local_units) < minimum_units:
            region_class = "unsupported"
        else:
            region_class = "interpolated"
        pseudo = {"factors": settings}
        if region_class != "forbidden" and _inside_forbidden(settings, forbidden):
            region_class = "forbidden"

        predictions = {}
        metric_passes = []
        simultaneous_metric_passes = []
        exact_model_setting = tuple(settings.get(name) for name in model_factors)
        has_simultaneous_exact_setting = (
            simultaneous_calibration.get("status") == "AVAILABLE"
            and region_class == "observed"
            and exact_model_setting in simultaneous_setting_keys
        )
        for metric, definition in constrained.items():
            if region_class in ("observed", "interpolated", "extrapolated"):
                prediction = fitted[metric].predict(settings, fixed_effects)
                estimate = prediction.get("estimate")
                local_scores = []
                for group, heldout_rows in calibration_scores[metric].items():
                    group_errors = [item["absolute_error"] for item in heldout_rows
                                    if sqrt(sum((a-b)**2 for a, b in zip(
                                        target, normalized_model_point(item["row"]["factors"])))) <= radius]
                    if group_errors:
                        local_scores.append(max(group_errors))
                quantile = (_finite_rank_quantile(local_scores)
                            if len(local_scores) >= minimum_calibration_units else None)
                if isinstance(estimate, (int, float)) and isfinite(estimate) and quantile is not None:
                    prediction["model_predictive_interval95"] = prediction.get("predictive_interval95")
                    prediction["predictive_interval95"] = [estimate-quantile, estimate+quantile]
                    prediction["calibration_status"] = "LOCAL_GROUP_HOLDOUT_EMPIRICAL"
                    prediction["calibration_method"] = (
                        "local group-maximum absolute holdout error; 95% order-statistic rank; "
                        "no distribution-free conditional coverage guarantee")
                    prediction["calibration_units"] = len(local_scores)
                    prediction["calibration_quantile95_absolute_error"] = quantile
                else:
                    prediction["predictive_interval95"] = None
                    prediction["calibration_status"] = "INSUFFICIENT_LOCAL_HOLDOUT_SUPPORT"
                    prediction["calibration_units"] = len(local_scores)
                if has_simultaneous_exact_setting:
                    radius95 = simultaneous_calibration["metric_quantiles"][metric]["absolute_error_radius"]
                    if isinstance(estimate, (int, float)) and isfinite(estimate):
                        prediction["simultaneous_group_interval95"] = [estimate-radius95, estimate+radius95]
                        prediction["simultaneous_group_calibration_status"] = "AVAILABLE_UNDER_UNVERIFIED_EXCHANGEABILITY_ASSUMPTIONS"
                        prediction["simultaneous_group_error_radius"] = radius95
                        simultaneous_metric_passes.append(
                            _metric_pass_interval({"predictive_interval95": prediction["simultaneous_group_interval95"]}, definition))
                    else:
                        prediction["simultaneous_group_interval95"] = None
                        prediction["simultaneous_group_calibration_status"] = "PREDICTION_UNAVAILABLE"
                        simultaneous_metric_passes.append(False)
                else:
                    prediction["simultaneous_group_interval95"] = None
                    prediction["simultaneous_group_calibration_status"] = (
                        simultaneous_calibration.get("status") if simultaneous_calibration.get("status") != "AVAILABLE"
                        else "NOT_IN_COMPLETE_EXACT_SETTING_PANEL")
            else:
                prediction = {"status": "NOT_PREDICTED"}
                prediction["simultaneous_group_interval95"] = None
                prediction["simultaneous_group_calibration_status"] = "NOT_PREDICTED_OUTSIDE_SUPPORTED_REGION"
            predictions[metric] = prediction
            safe = _metric_pass_interval(prediction, definition)
            if safe is not None:
                metric_passes.append(safe)
        conservative_feasible = bool(metric_passes) and len(metric_passes) == len(constrained) and all(metric_passes)
        observed_replicates_pass = bool(exact_rows) and all(
            _metric_pass(row["metrics"][metric], definition)
            for row in exact_rows for metric, definition in constrained.items())
        candidate = (region_class in ("observed", "interpolated") and conservative_feasible
                     and (region_class != "observed" or observed_replicates_pass))
        simultaneous_candidate = (
            has_simultaneous_exact_setting
            and len(simultaneous_metric_passes) == len(constrained)
            and all(simultaneous_metric_passes)
            and observed_replicates_pass
        )
        cell = {"factors": settings, "region_class": region_class,
                "support": {"nearest_normalized_distance": nearest, "nearby_distinct_settings": len(near_settings),
                            "nearby_independent_units": len(local_units), "independent_unit_field": unit_field,
                            "nearby_calibration_settings": len(near_calibration_settings),
                            "nearby_calibration_units": len(local_calibration_units),
                            "minimum_calibration_units": minimum_calibration_units},
                "predictions": predictions, "conservative_feasible": conservative_feasible,
                "screened_candidate": candidate,
                "candidate_screening_status": "AVAILABLE_ADVISORY_SCREENING" if candidate else "NOT_SCREENED_CANDIDATE",
                "supported_candidate": candidate,
                "simultaneous_supported_candidate": simultaneous_candidate}
        grid.append(cell)
        if candidate:
            candidates.append(cell)
    counts = {name: sum(cell["region_class"] == name for cell in grid)
              for name in ("observed", "interpolated", "extrapolated", "unsupported", "forbidden")}
    evaluation = _evaluate_selected_cells(candidates, evaluation_rows, selected, constrained, unit_field,
                                          fixed_settings, evaluation_strata)
    evaluation_by_setting = {
        tuple(float(item["factors"][name]) for name in selected): item
        for item in evaluation.get("candidates", [])
    }
    screened_candidates = candidates
    selection_audit = evaluation.get("candidate_selection_audit", {})
    complete_evaluation_units = selection_audit.get("complete_independent_units", 0)
    setwise_failures = selection_audit.get("observed_any_infeasible_units")
    observed_failed_cells = [item for item in evaluation.get("candidates", [])
                             if item.get("independent_units", 0) > 0
                             and item.get("observed_infeasible_units", 0) > 0]
    candidate_counterevidence = {
        "status": "INSUFFICIENT_COMPLETE_SET_EVALUATION" if not observed_failed_cells
                  and not complete_evaluation_units else "NO_OBSERVED_SETWISE_FAILURES",
        "complete_independent_units": complete_evaluation_units,
        "observed_any_infeasible_units": setwise_failures,
        "observed_any_infeasible_fraction": selection_audit.get("observed_any_infeasible_fraction"),
        "observed_failed_candidate_count": len(observed_failed_cells),
        "observed_failed_candidate_factors": [item["factors"] for item in observed_failed_cells],
        "guarantee": "none; descriptive observed counterevidence only",
    }
    if observed_failed_cells:
        # Do not use the untouched evaluation partition to choose which
        # candidate survives. A failure at any exact screened setting withholds
        # the entire recommendation set while preserving the pre-veto grid for
        # audit and experiment planning.
        candidate_counterevidence["status"] = (
            "WITHHELD_COMPLETE_SET_INFEASIBILITY" if complete_evaluation_units and setwise_failures
            else "WITHHELD_BY_OBSERVED_CANDIDATE_FAILURE")
        for cell in grid:
            if cell["screened_candidate"]:
                cell["supported_candidate"] = False
                cell["simultaneous_supported_candidate"] = False
                cell["candidate_screening_status"] = "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE"
        candidates = []
        candidate_screening_status = "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE"
    else:
        candidate_screening_status = "AVAILABLE_ADVISORY_SCREENING" if screened_candidates else "NO_POINTWISE_CANDIDATES"
    for cell in grid:
        setting_key = tuple(float(cell["factors"][name]) for name in selected)
        evaluated = evaluation_by_setting.get(setting_key)
        if evaluated is None:
            evaluation_status = ("NOT_PROVIDED" if evaluation.get("status") == "NOT_PROVIDED"
                                 else "NO_EXACT_SETTING_EVALUATION_DATA")
            evaluated_units = 0
            observed_failures = None
        else:
            evaluation_status = evaluated.get("status", "UNAVAILABLE")
            evaluated_units = evaluated.get("independent_units", 0)
            observed_failures = evaluated.get("observed_infeasible_units")
            if observed_failures:
                evaluation_status = "OBSERVED_INDEPENDENT_INFEASIBILITY"
            elif evaluated_units:
                evaluation_status = "NO_INFEASIBILITY_OBSERVED_NOT_VALIDATION"

        cell["independent_evaluation"] = {
            "status": evaluation_status,
            "independent_units": evaluated_units,
            "observed_infeasible_units": observed_failures,
            "interpretation": "descriptive exact-setting outcomes only; no population or future-performance guarantee",
        }
        if cell["screened_candidate"] and candidate_screening_status == "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE":
            cell["candidate_review_status"] = "WITHHELD_COMPLETE_SET_BY_INDEPENDENT_COUNTEREVIDENCE"
            cell["required_engineer_action"] = "DO_NOT_ADVANCE; REVIEW_COUNTEREVIDENCE_AND_PLAN_A_NEW_EXPERIMENT"
        elif cell["screened_candidate"] and cell["region_class"] == "interpolated":
            cell["candidate_review_status"] = "MODEL_INTERPOLATION_ADVISORY_REQUIRES_EXACT_CONFIRMATION"
            cell["required_engineer_action"] = "PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS"
        elif cell["screened_candidate"]:
            cell["candidate_review_status"] = "OBSERVED_SETTING_ADVISORY_REQUIRES_ENGINEER_REVIEW"
            cell["required_engineer_action"] = "REVIEW_OBSERVED_POPULATION_AND_CONFIRM_REPEATABILITY"
        else:
            cell["candidate_review_status"] = "NOT_A_SCREENED_CANDIDATE"
            cell["required_engineer_action"] = "NO_CANDIDATE_ACTION"
    partitions = {calibration_report["training_value"]: matching_rows,
                  calibration_report["calibration_value"]: calibration_rows}
    if calibration_report.get("evaluation_value") is not None:
        partitions[calibration_report["evaluation_value"]] = evaluation_rows
    evaluation["partition_composition_diagnostic"] = _partition_composition_diagnostic(
        partitions, unit_field, evaluation_strata,
        calibration_report["calibration_value"], calibration_report.get("evaluation_value"))
    composition_diagnostic = evaluation["partition_composition_diagnostic"]
    simultaneous_summary = dict(simultaneous_calibration)
    simultaneous_summary["calibration_population_strata_compatibility"] = calibration_population_strata
    if simultaneous_calibration.get("status") == "AVAILABLE":
        simultaneous_summary["independent_evaluation_panel_compatibility"] = _evaluation_panel_compatibility(
            evaluation_rows, unit_field, model_factors,
            simultaneous_calibration["common_exact_settings"],
            simultaneous_calibration["observations_per_setting"])
    else:
        simultaneous_summary["independent_evaluation_panel_compatibility"] = {
            "status": "NOT_AVAILABLE",
            "reason": simultaneous_calibration.get("reason", "the finite exact-setting calibration band is unavailable"),
            "interpretation": "evaluation panel structure cannot be compared with an unavailable precommitted band"}
    heldout_band_evaluation = _evaluate_calibration_band_transfer(
        evaluation_rows, unit_field, fitted, model_factors, fixed_effects,
        simultaneous_calibration, cancel)
    transfer_assessment = _calibration_transfer_assessment(
        simultaneous_calibration.get("status"),
        simultaneous_summary["independent_evaluation_panel_compatibility"],
        composition_diagnostic,
        calibration_report.get("evaluation_value") is not None,
        calibration_report.get("calibration_value"),
        calibration_report.get("evaluation_value"), heldout_band_evaluation,
        evaluation_predeclared_strata)
    simultaneous_summary["calibration_transfer_assessment"] = transfer_assessment
    # Evaluation outcomes never change the fitted model, calibration radius,
    # or select a favorable candidate subset. Exact infeasibility and explicit
    # transfer counterevidence can only withdraw the complete set; the original
    # screen remains auditable.
    transfer_counterevidence = transfer_assessment["status"].startswith("COUNTEREVIDENCE")
    if transfer_counterevidence:
        candidate_counterevidence["status"] = "WITHHELD_BY_CALIBRATION_TRANSFER_COUNTEREVIDENCE"
        candidate_counterevidence["transfer_status"] = transfer_assessment["status"]
        candidate_counterevidence["observed_transfer_counterevidence"] = list(
            transfer_assessment["observed_counterevidence"])
        for cell in grid:
            cell["simultaneous_supported_candidate"] = False
            if cell["screened_candidate"]:
                cell["supported_candidate"] = False
                cell["candidate_screening_status"] = "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE"
        candidates = []
        candidate_screening_status = "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE"
    for cell in grid:
        cell["evaluation_transfer_status"] = transfer_assessment["status"]
    for cell in candidates:
        cell["evaluation_transfer_status"] = transfer_assessment["status"]
    simultaneous_candidates = [cell for cell in grid if cell["simultaneous_supported_candidate"]]
    simultaneous_summary["simultaneous_supported_candidate_count"] = len(simultaneous_candidates)
    simultaneous_summary["pointwise_supported_candidate_count"] = len(candidates)
    simultaneous_summary["pointwise_screened_candidate_count"] = len(screened_candidates)
    screened_candidate_counts_by_region = {
        name: sum(cell["screened_candidate"] and cell["region_class"] == name for cell in grid)
        for name in ("observed", "interpolated", "extrapolated", "unsupported", "forbidden")
    }
    candidate_counts_by_region = {
        name: sum(cell["supported_candidate"] and cell["region_class"] == name for cell in grid)
        for name in ("observed", "interpolated", "extrapolated", "unsupported", "forbidden")
    }
    simultaneous_summary["status_scope"] = (
        ("ASSUMPTION_CONDITIONAL_PREDECLARED_STRATA_AND_EXACT_SETTING_PANEL"
         if simultaneous_calibration.get("status") == "AVAILABLE" and declared_strata else
         "ASSUMPTION_CONDITIONAL_EXACT_SETTING_PANEL_ONLY"
         if simultaneous_calibration.get("status") == "AVAILABLE" else "NOT_AVAILABLE"))
    return {"status": "VALID" if candidates else "INCONCLUSIVE",
            "reason": ("independent evaluation observed infeasible outcomes at one or more screened settings; the entire candidate set is withheld"
                       if observed_failed_cells else
                       "independent evaluation found calibration-transfer counterevidence; the entire candidate set is withheld"
                       if transfer_counterevidence else None),
            "method": "supported_grid_response_surface_with_local_grouped_holdout_calibration",
            "explored_factors": selected, "approved_factor_bounds": bounds,
            "fixed_settings": fixed_settings, "fixed_effects": fixed_effects,
            "independent_unit_field": unit_field, "minimum_independent_units": minimum_units,
            "omitted_controls_held_at_fixed_setting": omitted_controls,
            "repeated_unit_handling": "clustered on declared independent unit" if repeated_units else "one row per independent unit",
            "calibration": calibration_report,
            "data_roles": {
                "model_fitting": calibration_report["training_value"],
                "model_selection": "NOT_PERFORMED_BY_ENGINE; caller supplies the model-selection reference, which is not authenticated",
                "threshold_selection": "NOT_PERFORMED_BY_ENGINE; caller supplies the threshold-selection reference, which is not authenticated",
                "selection_plan_status": (simultaneous_calibration.get("precommit") or {}).get(
                    "status", simultaneous_calibration.get("status")),
                "uncertainty_calibration": calibration_report["calibration_value"],
                "independent_evaluation": calibration_report["evaluation_value"] or "NOT_PROVIDED",
            },
            "uncertainty_scope": {
                "method": "local group-maximum absolute holdout error",
                "rank": "ceil((n_independent_calibration_units + 1) * 0.95)",
                "formal_coverage_claim": "NONE_ESTABLISHED",
                "conditional_coverage": "NOT_ESTABLISHED",
                "simultaneous_coverage_over_searched_grid": "NOT_ESTABLISHED",
                "interpretation": "empirical local uncertainty diagnostic; candidate selection across grid may increase false-feasible findings",
                "conditions_for_a_future_formal_claim": [
                    "independent exchangeable engineering units matching the stated target population",
                    "model-selection, threshold-selection, metric-family, and exact-setting panel references fixed before calibration outcomes are inspected",
                    "a calibration design whose score matches the exact prediction target and selection scope",
                    "identical complete calibration panels matching the explicit precommit panel",
                    "prespecified metric limits and no outcome-driven threshold tuning",
                ],
            },
            "simultaneous_exact_setting_screen": simultaneous_summary,
            "independent_candidate_evaluation": evaluation,
            "candidate_screening_status": candidate_screening_status,
            "screened_candidate_count": len(screened_candidates),
            "candidate_counterevidence": candidate_counterevidence,
            "grid_shape": [len(axis) for axis in axes], "region_counts": counts,
            "model_diagnostics": fit_reports, "convex_hull_normalized": hull,
            "extrapolation_within_approved_bounds_present": extrapolation_present,
            "candidate_count": len(candidates), "candidate_cells": candidates,
            "candidate_counts_by_region": candidate_counts_by_region,
            "screened_candidate_counts_by_region": screened_candidate_counts_by_region,
            "candidate_count_semantics": (
                "model-screened advisory hypotheses; a local grouped calibration interval does not validate model form, "
                "interpolation, conditional coverage, or future process performance"),
            "candidate_scope": "MODEL_BASED_ADVISORY_SCREENING_ONLY",
            "candidate_review_rule": (
                "interpolated cells remain model-based hypotheses and require exact-setting confirmation on independent lots; "
                "observed evaluation outcomes are descriptive only; exact infeasibility, a calibration-band miss, unseen declared "
                "evaluation strata, or a precommitted-panel mismatch withholds the complete screened set"),
            "simultaneous_candidate_count": len(simultaneous_candidates),
            "joint_validation_status": "NOT_ESTABLISHED",
            "selection_warning": (
                "Candidates are screened over a searched grid using local grouped calibration. "
                "Selection among cells can inflate false-feasible findings; these intervals do not "
                "establish simultaneous or conditional coverage. A separate maximum-score band is "
                "available only when an explicit precommit record declares the model, threshold, metric "
                "family, and exact-setting panel and every calibration unit matches that panel. The "
                "record's references and timing remain unauthenticated. Any observed infeasible "
                "outcome at an exact screened setting, a calibration-band miss, unseen declared "
                "evaluation strata, or a precommitted-panel mismatch in the independent evaluation "
                "partition withholds the entire candidate set; evaluation is never used to retain a "
                "favorable subset. A known mix difference alone remains a descriptive warning. Validate "
                "a preselected exact setting on independent engineering units before any process decision."),
            "grid": grid,
            "uncertainty_rule": (
                "all local group-held-out empirical intervals using a 95% order-statistic rank "
                "must satisfy every explicit metric limit; this does not guarantee conditional coverage"),
            "qualification": "supported statistical exploration only; candidates are not recipes or production approval"}
