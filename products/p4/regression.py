"""Dependency-free linear response models with robust covariance diagnostics.

This module estimates observational associations. Cluster sandwich covariance
allows arbitrary within-cluster dependence when there are enough independent
clusters; it does not make the fitted model causal or remove omitted-variable
bias. statsmodels is used only by qualification/reference scripts.
"""
from __future__ import annotations

from itertools import combinations
from math import copysign, isfinite, sqrt
from statistics import mean
import json


class ModelError(ValueError):
    pass


class RegressionCancelled(Exception):
    pass


def _check_cancel(cancel):
    if cancel and cancel():
        raise RegressionCancelled("regression cancelled")


def _get_field(row, path):
    value = row
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ModelError(f"model field is missing: {path}")
        value = value[part]
    return value


def _key(value):
    return json.dumps({"type": type(value).__name__, "value": value}, sort_keys=True, separators=(",", ":"))


def _label(value):
    text = str(value)
    return text if len(text) <= 48 else text[:45] + "..."


def critical_t_975(df):
    """Two-sided 95% Student-t critical value, with a Cornish-Fisher tail."""
    if not isinstance(df, (int, float)) or df < 1:
        raise ValueError("degrees of freedom must be at least one")
    table = [12.7062047364, 4.30265272975, 3.18244630528, 2.7764451052,
             2.57058183564, 2.44691184879, 2.36462425101, 2.3060041352,
             2.26215716285, 2.22813885196, 2.20098516008, 2.17881282966,
             2.16036865646, 2.14478668792, 2.13144954556, 2.11990529922,
             2.10981557783, 2.10092204024, 2.09302405441, 2.08596344727,
             2.07961384473, 2.0738730679, 2.06865761042, 2.06389856163,
             2.05953855275, 2.05552943864, 2.05183051648, 2.0484071418,
             2.04522964213, 2.0422724563]
    if int(df) == df and 1 <= int(df) <= len(table):
        return table[int(df) - 1]
    v = float(df)
    z = 1.959963984540054
    z2 = z * z
    return (z + (z**3 + z) / (4*v)
            + (5*z**5 + 16*z**3 + 3*z) / (96*v**2)
            + (3*z**7 + 19*z**5 + 17*z**3 - 15*z) / (384*v**3))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _matvec(a, x):
    return [_dot(row, x) for row in a]


def _transpose(a):
    return [list(col) for col in zip(*a)]


def _qr_solve_and_bread(x, y, tol=1e-11):
    """Column-pivoted Householder QR; returns beta, (X'X)^-1, rank metadata."""
    n = len(x)
    p = len(x[0]) if x else 0
    if n < p or p == 0:
        return None, None, {"rank": min(n, p), "condition_proxy": None}
    a = [list(row) for row in x]
    qty = list(y)
    permutation = list(range(p))
    first_diagonal = None
    diagonals = []
    for k in range(p):
        pivot = max(range(k, p), key=lambda j: sum(a[i][j]**2 for i in range(k, n)))
        if pivot != k:
            for row in a:
                row[k], row[pivot] = row[pivot], row[k]
            permutation[k], permutation[pivot] = permutation[pivot], permutation[k]
        norm = sqrt(sum(a[i][k]**2 for i in range(k, n)))
        if k == 0:
            first_diagonal = norm
        if not isfinite(norm) or norm <= tol * max(first_diagonal or 1.0, 1.0):
            return None, None, {"rank": k, "condition_proxy": None, "permutation": permutation}
        alpha = -copysign(norm, a[k][k] if a[k][k] else 1.0)
        v = [a[i][k] for i in range(k, n)]
        v[0] -= alpha
        vnorm2 = _dot(v, v)
        if vnorm2 <= 0 or not isfinite(vnorm2):
            return None, None, {"rank": k, "condition_proxy": None, "permutation": permutation}
        scale = 2.0 / vnorm2
        for j in range(k, p):
            projection = scale * sum(v[t] * a[k+t][j] for t in range(len(v)))
            for t, value in enumerate(v):
                a[k+t][j] -= projection * value
        projection_y = scale * sum(v[t] * qty[k+t] for t in range(len(v)))
        for t, value in enumerate(v):
            qty[k+t] -= projection_y * value
        a[k][k] = alpha
        for i in range(k+1, n):
            a[i][k] = 0.0
        diagonals.append(abs(alpha))

    # Solve the upper-triangular system R beta_pivoted = Q'y.
    beta_p = [0.0] * p
    for i in range(p-1, -1, -1):
        beta_p[i] = (qty[i] - sum(a[i][j] * beta_p[j] for j in range(i+1, p))) / a[i][i]

    # Invert R by triangular solves, then compute (R'R)^-1 = R^-1 R^-T.
    rinv = [[0.0] * p for _ in range(p)]
    for col in range(p):
        for i in range(p-1, -1, -1):
            rhs = 1.0 if i == col else 0.0
            rinv[i][col] = (rhs - sum(a[i][j] * rinv[j][col] for j in range(i+1, p))) / a[i][i]
    bread_p = [[sum(rinv[i][k] * rinv[j][k] for k in range(p)) for j in range(p)] for i in range(p)]
    beta = [0.0] * p
    bread = [[0.0] * p for _ in range(p)]
    for i, old_i in enumerate(permutation):
        beta[old_i] = beta_p[i]
        for j, old_j in enumerate(permutation):
            bread[old_i][old_j] = bread_p[i][j]
    condition_proxy = (max(diagonals) / min(diagonals))**2 if diagonals and min(diagonals) else None
    return beta, bread, {"rank": p, "condition_proxy": condition_proxy, "permutation": permutation}


def _sandwich(bread, meat):
    p = len(bread)
    left = [[sum(bread[i][k] * meat[k][j] for k in range(p)) for j in range(p)] for i in range(p)]
    return [[sum(left[i][k] * bread[j][k] for k in range(p)) for j in range(p)] for i in range(p)]


class FittedLinearModel:
    def __init__(self, *, factor_names, centers, scales, category_levels, term_specs, labels,
                 beta, covariance, residual_variance, df, covariance_type, report):
        self.factor_names = factor_names
        self.centers = centers
        self.scales = scales
        self.category_levels = category_levels
        self.term_specs = term_specs
        self.labels = labels
        self.beta = beta
        self.covariance = covariance
        self.residual_variance = residual_variance
        self.df = df
        self.covariance_type = covariance_type
        self.report = report

    def vector(self, factors, fixed_effects=None):
        fixed_effects = fixed_effects or {}
        standardized = {name: (float(factors[name]) - self.centers[name]) / self.scales[name]
                        for name in self.factor_names}
        out = []
        for kind, args in self.term_specs:
            if kind == "intercept":
                out.append(1.0)
            elif kind == "linear":
                out.append(standardized[args[0]])
            elif kind == "interaction":
                out.append(standardized[args[0]] * standardized[args[1]])
            elif kind == "quadratic":
                out.append(standardized[args[0]]**2)
            elif kind == "category":
                field, level_key = args
                if field not in fixed_effects:
                    raise ModelError(f"fixed effect value is required for {field}")
                observed = _key(fixed_effects[field])
                if observed not in self.category_levels[field]:
                    raise ModelError(f"unsupported fixed effect level for {field}")
                out.append(1.0 if observed == level_key else 0.0)
            elif kind == "category_interaction":
                field, level_key, factor = args
                if field not in fixed_effects:
                    raise ModelError(f"fixed effect value is required for {field}")
                observed = _key(fixed_effects[field])
                if observed not in self.category_levels[field]:
                    raise ModelError(f"unsupported fixed effect level for {field}")
                out.append((1.0 if observed == level_key else 0.0) * standardized[factor])
            else:
                raise ModelError("unknown design term")
        return out

    def predict(self, factors, fixed_effects=None):
        x = self.vector(factors, fixed_effects)
        estimate = _dot(x, self.beta)
        if self.covariance is None or not self.df:
            return {"status": "UNCERTAINTY_UNAVAILABLE", "estimate": estimate}
        var_mean = _dot(x, _matvec(self.covariance, x))
        if not isfinite(var_mean) or var_mean < -1e-8:
            return {"status": "UNCERTAINTY_UNAVAILABLE", "estimate": estimate}
        var_mean = max(0.0, var_mean)
        critical = critical_t_975(self.df)
        mean_se = sqrt(var_mean)
        predictive_se = sqrt(var_mean + max(0.0, self.residual_variance))
        return {"status": "ESTIMATED", "estimate": estimate, "mean_standard_error": mean_se,
                "mean_ci95": [estimate-critical*mean_se, estimate+critical*mean_se],
                "predictive_interval95": [estimate-critical*predictive_se, estimate+critical*predictive_se],
                "degrees_of_freedom": self.df}


def fit_linear_model(rows, factor_defs, metric, options=None, cancel=None):
    options = options or {}
    if not rows:
        raise ModelError("at least one row is required")
    if any(isinstance(row, dict) and "measurement_uncertainty" in row for row in rows):
        raise ModelError("measurement_uncertainty was supplied but is not propagated by this model; sensitivity inference is refused")
    all_numeric = [name for name, definition in factor_defs.items()
                   if definition.get("role", "controllable") in ("controllable", "measured")]
    factor_names = options.get("factor_fields", all_numeric)
    if not isinstance(factor_names, list) or not factor_names or len(set(factor_names)) != len(factor_names):
        raise ModelError("factor_fields must be a nonempty list of unique factor names")
    if any(name not in factor_defs or name not in all_numeric for name in factor_names):
        raise ModelError("models may use only defined controllable or measured numeric factors")
    fixed_fields = options.get("fixed_effect_fields", [])
    if not isinstance(fixed_fields, list) or len(set(fixed_fields)) != len(fixed_fields):
        raise ModelError("fixed_effect_fields must be a list of unique row field paths")
    max_levels = options.get("max_fixed_effect_levels", 24)
    if not isinstance(max_levels, int) or isinstance(max_levels, bool) or not 2 <= max_levels <= 100:
        raise ModelError("max_fixed_effect_levels must be between 2 and 100")

    independent_unit_field = options.get("independent_unit_field")
    independent_unit_count = None
    auto_clustered = False
    cluster_nesting = None
    if independent_unit_field is not None:
        if not isinstance(independent_unit_field, str) or not independent_unit_field:
            raise ModelError("independent_unit_field must be a nonempty row field path")
        try:
            values = [_get_field(row, independent_unit_field) for row in rows]
            if any(value is None or value == "" for value in values):
                raise ModelError("declared independent unit is empty")
            independent_keys = [_key(value) for value in values]
        except ModelError:
            return {"status": "INCONCLUSIVE",
                    "reason": "the declared independent-unit field is missing or empty; sensitivity uncertainty is withheld",
                    "n": len(rows), "terms": {}, "diagnostic_warnings": [],
                    "inference": {"declared_independent_unit_field": independent_unit_field}}, None
        independent_unit_count = len(set(independent_keys))
        covariance = options.get("covariance", "HC3")
        if covariance not in ("HC3", "cluster", "classical"):
            raise ModelError("covariance must be HC3, cluster, or classical")
        if covariance == "cluster":
            cluster_field = options.get("cluster_field")
            if not isinstance(cluster_field, str) or not cluster_field:
                raise ModelError("cluster covariance requires an explicit cluster_field")
            try:
                cluster_values = [_get_field(row, cluster_field) for row in rows]
                if any(value is None or value == "" for value in cluster_values):
                    raise ModelError("declared cluster field is empty")
                cluster_keys = [_key(value) for value in cluster_values]
            except ModelError:
                return {"status": "INCONCLUSIVE",
                        "reason": "the declared cluster field is missing; sensitivity uncertainty is withheld",
                        "n": len(rows), "terms": {}, "diagnostic_warnings": [],
                        "inference": {"declared_independent_unit_field": independent_unit_field,
                                      "cluster_field": cluster_field}}, None
            unit_clusters = {}
            for unit_key, cluster_key in zip(independent_keys, cluster_keys):
                unit_clusters.setdefault(unit_key, set()).add(cluster_key)
            split_units = [unit for unit, clusters in unit_clusters.items() if len(clusters) != 1]
            cluster_nesting = {"status": "NESTED" if not split_units else "INDEPENDENT_UNIT_SPLIT_ACROSS_CLUSTERS",
                               "declared_independent_unit_field": independent_unit_field,
                               "cluster_field": cluster_field,
                               "independent_units": independent_unit_count,
                               "clusters": len(set(cluster_keys)),
                               "split_independent_unit_count": len(split_units)}
            if split_units:
                return {"status": "INCONCLUSIVE",
                        "reason": "the declared cluster field splits repeated independent units across clusters; cluster-robust uncertainty is withheld",
                        "n": len(rows), "terms": {}, "diagnostic_warnings": [],
                        "inference": {"declared_independent_unit_field": independent_unit_field,
                                      "cluster_field": cluster_field,
                                      "declared_independent_unit_count": independent_unit_count,
                                      "cluster_nesting": cluster_nesting}}, None
        if independent_unit_count < len(independent_keys) and covariance != "cluster":
            # A declared sampling unit makes row-independent HC3/classical
            # inference inappropriate when multiple rows belong to that unit.
            options = {**options, "covariance": "cluster", "cluster_field": independent_unit_field}
            auto_clustered = True

    factor_values = {name: [float(row["factors"][name]) for row in rows] for name in factor_names}
    centers = {name: mean(values) for name, values in factor_values.items()}
    scales = {name: sqrt(sum((v-centers[name])**2 for v in values)/len(values)) for name, values in factor_values.items()}
    scales = {name: scale if scale > 0 else 1.0 for name, scale in scales.items()}

    category_levels = {}
    raw_levels = {}
    for field in fixed_fields:
        _check_cancel(cancel)
        pairs = [(_key(_get_field(row, field)), _get_field(row, field)) for row in rows]
        raw_levels[field] = {}
        for key, value in pairs:
            raw_levels[field][key] = value
        if len(raw_levels[field]) > max_levels:
            raise ModelError(f"fixed effect {field} has more than the configured {max_levels} levels")
        category_levels[field] = sorted(raw_levels[field])

    term_specs = [("intercept", ())]
    labels = ["intercept_at_factor_centers"]
    for name in factor_names:
        term_specs.append(("linear", (name,)))
        labels.append(name)
    interactions = options.get("interactions", False)
    if interactions is True:
        interaction_pairs = list(combinations(factor_names, 2))
    elif interactions is False or interactions is None:
        interaction_pairs = []
    elif isinstance(interactions, list):
        interaction_pairs = []
        for pair in interactions:
            if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1] or any(n not in factor_names for n in pair):
                raise ModelError("interactions must be true or a list of two-factor name pairs")
            interaction_pairs.append(tuple(pair))
    else:
        raise ModelError("interactions must be boolean or a list of factor pairs")
    for a, b in interaction_pairs:
        term_specs.append(("interaction", (a, b)))
        labels.append(f"{a}:{b}")
    quadratic = options.get("quadratic", False)
    if quadratic is True:
        quadratic_fields = factor_names
    elif quadratic is False or quadratic is None:
        quadratic_fields = []
    elif isinstance(quadratic, list) and all(name in factor_names for name in quadratic):
        quadratic_fields = quadratic
    else:
        raise ModelError("quadratic must be boolean or a list of factor names")
    for name in quadratic_fields:
        term_specs.append(("quadratic", (name,)))
        labels.append(f"{name}^2")
    for field in fixed_fields:
        for key in category_levels[field][1:]:
            term_specs.append(("category", (field, key)))
            labels.append(f"{field}[{_label(raw_levels[field][key])}]")
    categorical_interactions = options.get("fixed_effect_interactions", [])
    if not isinstance(categorical_interactions, list):
        raise ModelError("fixed_effect_interactions must be a list of [field, factor] pairs")
    normalized_categorical_interactions = []
    for pair in categorical_interactions:
        if (not isinstance(pair, list) or len(pair) != 2 or pair[0] not in fixed_fields
                or pair[1] not in factor_names or pair[0] == pair[1]):
            raise ModelError("fixed_effect_interactions must pair a declared fixed effect with a modeled factor")
        normalized_categorical_interactions.append(tuple(pair))
    if len(set(normalized_categorical_interactions)) != len(normalized_categorical_interactions):
        raise ModelError("fixed_effect_interactions pairs must be unique")
    for field, factor in normalized_categorical_interactions:
        for key in category_levels[field][1:]:
            term_specs.append(("category_interaction", (field, key, factor)))
            labels.append(f"{field}[{_label(raw_levels[field][key])}]:{factor}")
    if len(labels) > 128:
        raise ModelError("model exceeds the 128-term product limit")

    encoder = FittedLinearModel(factor_names=factor_names, centers=centers, scales=scales,
        category_levels=category_levels, term_specs=term_specs, labels=labels, beta=[], covariance=None,
        residual_variance=0.0, df=0, covariance_type="", report={})
    x = []
    for row in rows:
        _check_cancel(cancel)
        x.append(encoder.vector(row["factors"], {field: _get_field(row, field) for field in fixed_fields}))
    y = [float(row["metrics"][metric]) for row in rows]
    n, p = len(rows), len(labels)
    if n <= p:
        return {"status": "INCONCLUSIVE", "reason": "insufficient residual degrees of freedom", "n": n,
                "term_count": p, "terms": labels}, None
    y_mean = mean(y)
    beta, bread, rank_info = _qr_solve_and_bread(x, [value-y_mean for value in y])
    if beta is None:
        return {"status": "INCONCLUSIVE", "reason": "rank-deficient design; separate sensitivities are not identifiable",
                "n": n, "terms": labels, "rank_deficient": True, "rank": rank_info.get("rank"),
                "term_count": p, "condition_proxy": rank_info.get("condition_proxy")}, None
    beta[0] += y_mean
    residuals = [y[i] - _dot(x[i], beta) for i in range(n)]
    df = n - p
    residual_variance = sum(value*value for value in residuals)/df
    covariance_type = options.get("covariance", "HC3")
    if covariance_type not in ("HC3", "cluster", "classical"):
        raise ModelError("covariance must be HC3, cluster, or classical")
    warnings = []
    if auto_clustered:
        warnings.append(
            f"repeated rows were detected within declared independent units; cluster-robust uncertainty on {independent_unit_field} replaced row-independent covariance")
    leverage = [_dot(x[i], _matvec(bread, x[i])) for i in range(n)]
    max_leverage = max(leverage, default=0.0)
    high_leverage = [rows[i].get("id") for i, h in enumerate(leverage) if h > 2*p/n]
    if high_leverage:
        warnings.append("one or more observations exceed the descriptive 2p/n leverage flag")
    outliers = [rows[i].get("id") for i, value in enumerate(residuals)
                if residual_variance > 0 and abs(value)/(sqrt(residual_variance)*sqrt(max(1e-9, 1.0-leverage[i]))) > 3.0]
    if outliers:
        warnings.append("one or more internally studentized residuals exceed 3 in magnitude")
    covariance = None
    inferential_df = df
    cluster_count = None
    sst = sum((value-y_mean)**2 for value in y)
    residual_norm = sqrt(sum(value*value for value in residuals))
    response_norm = sqrt(sst)
    degenerate_residuals = residual_norm <= 1e-12 * max(1.0, response_norm)
    grouped_clusters = None
    minimum_clusters = options.get("minimum_clusters", 30)
    if covariance_type == "cluster":
        cluster_field = options.get("cluster_field")
        if not isinstance(cluster_field, str) or not cluster_field:
            raise ModelError("cluster covariance requires an explicit cluster_field")
        if not isinstance(minimum_clusters, int) or isinstance(minimum_clusters, bool) or minimum_clusters < 10:
            raise ModelError("minimum_clusters must be an integer of at least 10")
        grouped_clusters = {}
        for i, row in enumerate(rows):
            _check_cancel(cancel)
            key = _key(_get_field(row, cluster_field))
            grouped_clusters.setdefault(key, [0.0]*p)
            for j in range(p):
                grouped_clusters[key][j] += x[i][j]*residuals[i]
        cluster_count = len(grouped_clusters)
        inferential_df = cluster_count-1
    if degenerate_residuals:
        warnings.append("residual variation is numerically degenerate; inferential intervals withheld")
    elif covariance_type == "classical":
        covariance = [[residual_variance*bread[i][j] for j in range(p)] for i in range(p)]
    elif covariance_type == "HC3":
        meat = [[0.0]*p for _ in range(p)]
        for i in range(n):
            _check_cancel(cancel)
            denom = max(1e-9, 1.0-leverage[i])
            score = [x[i][j] * residuals[i] / denom for j in range(p)]
            for a in range(p):
                for b in range(p):
                    meat[a][b] += score[a]*score[b]
        covariance = _sandwich(bread, meat)
    else:
        grouped = grouped_clusters
        if cluster_count < minimum_clusters:
            warnings.append(f"cluster-robust intervals withheld: {cluster_count} clusters is below minimum_clusters={minimum_clusters}")
        else:
            meat = [[0.0]*p for _ in range(p)]
            for score in grouped.values():
                for a in range(p):
                    for b in range(p):
                        meat[a][b] += score[a]*score[b]
            correction = (cluster_count/(cluster_count-1)) * ((n-1)/(n-p))
            covariance = _sandwich(bread, meat)
            covariance = [[value*correction for value in row] for row in covariance]
    point_terms = {}
    scale_factor = {}
    for j, (kind, args) in enumerate(term_specs):
        if kind == "linear":
            scale_factor[j] = scales[args[0]]
        elif kind == "interaction":
            scale_factor[j] = scales[args[0]]*scales[args[1]]
        elif kind == "category_interaction":
            scale_factor[j] = scales[args[2]]
        elif kind == "quadratic":
            scale_factor[j] = scales[args[0]]**2
        else:
            scale_factor[j] = 1.0
        point_terms[labels[j]] = beta[j] / scale_factor[j]
    term_results = {}
    if covariance is not None:
        for j, label in enumerate(labels):
            divisor = scale_factor[j]
            estimate = point_terms[label]
            se = sqrt(max(0.0, covariance[j][j])) / divisor
            crit = critical_t_975(inferential_df)
            term_results[label] = {"estimate": estimate, "standard_error": se,
                                   "ci95": [estimate-crit*se, estimate+crit*se]}
    else:
        term_results = {label: {"estimate": point_terms[label], "standard_error": None, "ci95": None}
                        for label in labels}
    r2 = 1.0 - sum(value*value for value in residuals)/sst if sst else None
    factor_support = {name: {"n": n, "unique_levels": len(set(factor_values[name])),
                             "observed_range": [min(factor_values[name]), max(factor_values[name])],
                             "center": centers[name], "scale": scales[name]}
                      for name in factor_names}
    report = {"status": "VALID" if covariance is not None else "INCONCLUSIVE",
              "reason": None if covariance is not None else "point estimates are identified but robust uncertainty is unavailable",
              "n": n, "residual_df": df, "metric": metric, "term_count": p,
              "terms": term_results, "point_estimates": point_terms,
              "r_squared": r2, "residual_sd": sqrt(max(0.0, residual_variance)),
              "factor_support": factor_support,
              "fixed_effects": {field: {"reference_level": raw_levels[field][category_levels[field][0]],
                                         "levels": [raw_levels[field][k] for k in category_levels[field]]}
                                    for field in fixed_fields},
              "inference": {"covariance": covariance_type, "independent_cluster_field": options.get("cluster_field") if covariance_type == "cluster" else None,
                            "independent_cluster_count": cluster_count, "inference_df": inferential_df if covariance is not None else None,
                            "confidence_level": 0.95, "minimum_clusters": minimum_clusters if covariance_type == "cluster" else None,
                            "declared_independent_unit_field": independent_unit_field,
                            "declared_independent_unit_count": independent_unit_count,
                            "cluster_nesting": cluster_nesting,
                            "covariance_auto_selected_for_repeated_units": auto_clustered},
              "diagnostics": {"rank": rank_info["rank"], "condition_proxy": rank_info.get("condition_proxy"),
                              "maximum_leverage": max_leverage, "high_leverage_observation_ids": high_leverage,
                              "internally_studentized_residual_outlier_ids": outliers,
                              "degenerate_residual_variation": degenerate_residuals},
              "diagnostic_warnings": warnings,
              "model_specification": {"factors": factor_names, "factor_centers": centers,
                                      "interactions": [list(pair) for pair in interaction_pairs],
                                      "fixed_effect_interactions": [list(pair) for pair in normalized_categorical_interactions],
                                      "quadratic": list(quadratic_fields), "fixed_effect_fields": fixed_fields},
              "model_selection_scope": "formula is caller-supplied; whether selected before outcome inspection is not verified",
              "assumptions": ["observational conditional mean is represented by the selected linear/quadratic terms",
                              "HC3 handles heteroskedasticity but assumes independent observations",
                              "cluster covariance allows within-cluster dependence and relies on independent clusters",
                              "classical covariance additionally assumes homoskedastic errors",
                              "measurement uncertainty was not supplied or propagated",
                              "fixed effects adjust only for the explicitly selected fields"],
              "interpretation": "observational association; coefficients do not estimate intervention response"}
    encoder.beta = beta
    encoder.covariance = covariance
    encoder.residual_variance = residual_variance
    encoder.df = inferential_df if covariance is not None else 0
    encoder.covariance_type = covariance_type
    encoder.report = report
    return report, encoder
