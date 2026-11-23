"""Supported one- and two-factor response-surface exploration for D02."""
from __future__ import annotations

from itertools import product
from math import isfinite, sqrt

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
    whose full 95% predictive intervals satisfy every specification limit can
    be proposed as supported candidates. This is still not recipe approval.
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

    # Any controllable omitted from the response model must be held exactly at
    # its declared setting; otherwise its uncontrolled effect could be
    # mistaken for the explored response surface.
    omitted_controls = [name for name in controllable if name not in model_factors and name not in selected]
    matching_rows = []
    for row in rows:
        _check_cancel(cancel)
        try:
            if (all(_get_field(row, field) == fixed_effects[field] for field in category_fields)
                    and all(row["factors"].get(name) == fixed_settings[name] for name in omitted_controls)):
                _ = _get_field(row, unit_field)
                matching_rows.append(row)
        except (KeyError, ValueError):
            continue
    if len({str(_get_field(row, unit_field)) for row in matching_rows}) < minimum_units:
        return {"status": "INCONCLUSIVE", "reason": "the selected population has fewer than the required independent units",
                "independent_unit_field": unit_field, "independent_units": len({str(_get_field(row, unit_field)) for row in matching_rows}),
                "minimum_independent_units": minimum_units, "grid": [], "candidate_cells": []}

    unit_values = [str(_get_field(row, unit_field)) for row in matching_rows]
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
    for metric in constrained:
        _check_cancel(cancel)
        # Estimate the surface in the exact selected fixed-effect population.
        # This avoids borrowing slope information from unrelated products or
        # chambers unless the engineer explicitly defines a broader analysis.
        fit_reports[metric], fitted[metric] = fit_linear_model(matching_rows, factor_defs, metric, options, cancel=cancel)
        if fitted[metric] is None or fit_reports[metric].get("status") != "VALID":
            return {"status": "INCONCLUSIVE", "reason": f"uncertainty for constrained metric {metric} is not estimable",
                    "model_diagnostics": fit_reports, "grid": [], "candidate_cells": []}

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
        local_units = {str(_get_field(row, unit_field)) for row in near_rows}
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
        for metric, definition in constrained.items():
            if region_class in ("observed", "interpolated", "extrapolated"):
                prediction = fitted[metric].predict(settings, fixed_effects)
            else:
                prediction = {"status": "NOT_PREDICTED"}
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
        cell = {"factors": settings, "region_class": region_class,
                "support": {"nearest_normalized_distance": nearest, "nearby_distinct_settings": len(near_settings),
                            "nearby_independent_units": len(local_units), "independent_unit_field": unit_field},
                "predictions": predictions, "conservative_feasible": conservative_feasible,
                "supported_candidate": candidate}
        grid.append(cell)
        if candidate:
            candidates.append(cell)
    counts = {name: sum(cell["region_class"] == name for cell in grid)
              for name in ("observed", "interpolated", "extrapolated", "unsupported", "forbidden")}
    return {"status": "VALID" if candidates else "INCONCLUSIVE",
            "method": "supported_grid_response_surface_with_cluster_or_HC3_uncertainty",
            "explored_factors": selected, "approved_factor_bounds": bounds,
            "fixed_settings": fixed_settings, "fixed_effects": fixed_effects,
            "independent_unit_field": unit_field, "minimum_independent_units": minimum_units,
            "omitted_controls_held_at_fixed_setting": omitted_controls,
            "repeated_unit_handling": "clustered on declared independent unit" if repeated_units else "one row per independent unit",
            "grid_shape": [len(axis) for axis in axes], "region_counts": counts,
            "model_diagnostics": fit_reports, "convex_hull_normalized": hull,
            "extrapolation_within_approved_bounds_present": extrapolation_present,
            "candidate_count": len(candidates), "candidate_cells": candidates,
            "grid": grid,
            "uncertainty_rule": "all two-sided 95% predictive intervals must satisfy every explicit metric limit",
            "qualification": "supported statistical exploration only; candidates are not recipes or production approval"}
