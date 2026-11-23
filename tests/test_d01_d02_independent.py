"""Independent adversarial checks for robust modeling and D02 support rules."""
from __future__ import annotations

import math
import random
import unittest

from products.p4.regression import fit_linear_model
from products.p4.engine import _model_specification_sensitivity
from products.p4.window import explore_window, _finite_rank_quantile


FACTOR = {"pressure": {"role": "controllable", "unit": "kPa", "bounds": [0, 2], "approved": True},
          "power": {"role": "controllable", "unit": "W", "bounds": [0, 2], "approved": True}}
METRIC = {"quality": {"unit": "score", "direction": "maximize", "min": 0.0, "max": 0.5}}


def row(i, x, y, outcome, **metadata):
    return {"id": f"SYN-{i:04d}", "factors": {"pressure": float(x), "power": float(y)},
            "metrics": {"quality": float(outcome)}, **metadata}


class RobustRegressionQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy  # noqa: F401
            import statsmodels.api  # noqa: F401
        except ImportError:
            cls.reference_available = False
        else:
            cls.reference_available = True

    def test_hc3_matches_independent_statsmodels_reference(self):
        if not self.reference_available:
            self.skipTest("optional independent statsmodels reference is unavailable")
        import numpy as np
        import statsmodels.api as sm

        rows = []
        xs, ys = [], []
        for x in range(7):
            for j in range(12):
                noise = (0.04 + 0.04*x) * math.sin((x+1)*(j+2))
                y = 2.5 + 0.8*x + noise
                rows.append({"id": f"SYN-{len(rows)}", "factors": {"x": x}, "metrics": {"y": y}})
                xs.append(x); ys.append(y)
        report, _ = fit_linear_model(rows, {"x": {"role": "controllable", "unit": "u"}}, "y")
        reference = sm.OLS(ys, sm.add_constant(xs)).fit(cov_type="HC3", use_t=True)
        self.assertEqual(report["status"], "VALID")
        centered_reference = sm.OLS(ys, sm.add_constant(np.asarray(xs)-np.mean(xs))).fit(cov_type="HC3", use_t=True)
        self.assertAlmostEqual(report["terms"]["intercept_at_factor_centers"]["estimate"], centered_reference.params[0], places=9)
        self.assertAlmostEqual(report["terms"]["x"]["estimate"], reference.params[1], places=9)
        self.assertAlmostEqual(report["terms"]["x"]["standard_error"], reference.bse[1], places=8)

    def test_cluster_sandwich_matches_reference_and_withholds_small_cluster_intervals(self):
        if not self.reference_available:
            self.skipTest("optional independent statsmodels reference is unavailable")
        import statsmodels.api as sm

        rows, xs, ys, groups = [], [], [], []
        for cluster in range(40):
            cluster_shift = 0.5 * math.sin(cluster * 0.7)
            for j, x in enumerate((0, 1, 2, 3)):
                y = 4 + 1.4*x + cluster_shift + 0.08*math.sin(cluster*1.3+j*2.1)
                rows.append({"id": f"SYN-{len(rows)}", "factors": {"x": x}, "metrics": {"y": y}, "lot_id": f"L{cluster}"})
                xs.append(x); ys.append(y); groups.append(cluster)
        options = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30}
        report, _ = fit_linear_model(rows, {"x": {"role": "controllable", "unit": "u"}}, "y", options)
        reference = sm.OLS(ys, sm.add_constant(xs)).fit(cov_type="cluster", cov_kwds={"groups": groups, "use_correction": True, "df_correction": True}, use_t=True)
        self.assertAlmostEqual(report["terms"]["x"]["estimate"], reference.params[1], places=9)
        self.assertAlmostEqual(report["terms"]["x"]["standard_error"], reference.bse[1], places=8)
        self.assertEqual(report["inference"]["independent_cluster_count"], 40)
        auto_options = {"independent_unit_field": "lot_id", "minimum_clusters": 30}
        auto, _ = fit_linear_model(rows, {"x": {"role": "controllable", "unit": "u"}}, "y", auto_options)
        self.assertEqual(auto["inference"]["covariance"], "cluster")
        self.assertEqual(auto["inference"]["independent_cluster_field"], "lot_id")
        self.assertTrue(auto["inference"]["covariance_auto_selected_for_repeated_units"])
        self.assertAlmostEqual(auto["terms"]["x"]["standard_error"], reference.bse[1], places=8)
        self.assertTrue(any("cluster-robust uncertainty" in warning
                            for warning in auto["diagnostic_warnings"]))
        small, _ = fit_linear_model(rows[:80], {"x": {"role": "controllable", "unit": "u"}}, "y", options)
        self.assertEqual(small["status"], "INCONCLUSIVE")
        self.assertIsNone(small["terms"]["x"]["ci95"])
        small_auto, _ = fit_linear_model(rows[:80], {"x": {"role": "controllable", "unit": "u"}}, "y", auto_options)
        self.assertEqual(small_auto["status"], "INCONCLUSIVE")

    def test_cluster_field_must_not_split_a_declared_independent_unit(self):
        rows = []
        for lot in range(40):
            for repeat in range(2):
                rows.append({"id": f"SYN-NEST-{lot}-{repeat}",
                             "factors": {"x": float(lot % 2)},
                             "metrics": {"y": float(lot % 2) + 0.1 * repeat},
                             "lot_id": f"L{lot}", "chamber": f"C{repeat}-{lot // 2}"})
        report, model = fit_linear_model(
            rows, {"x": {"role": "controllable", "unit": "u"}}, "y",
            {"covariance": "cluster", "cluster_field": "chamber",
             "independent_unit_field": "lot_id", "minimum_clusters": 10})
        self.assertEqual(report["status"], "INCONCLUSIVE")
        self.assertIsNone(model)
        self.assertEqual(report["terms"], {})
        self.assertEqual(report["inference"]["cluster_nesting"]["status"],
                         "INDEPENDENT_UNIT_SPLIT_ACROSS_CLUSTERS")

    def test_cluster_field_may_be_a_valid_coarser_grouping(self):
        rows = []
        for lot in range(40):
            for repeat in range(2):
                x = float(lot % 2)
                rows.append({"id": f"SYN-NEST-OK-{lot}-{repeat}",
                             "factors": {"x": x}, "metrics": {"y": x + 0.01 * (lot % 3) + repeat * 0.02},
                             "lot_id": f"L{lot}", "chamber": f"C{lot // 2}"})
        report, _ = fit_linear_model(
            rows, {"x": {"role": "controllable", "unit": "u"}}, "y",
            {"covariance": "cluster", "cluster_field": "chamber",
             "independent_unit_field": "lot_id", "minimum_clusters": 10})
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["inference"]["cluster_nesting"]["status"], "NESTED")

    def test_fixed_effects_remove_chamber_level_confounding(self):
        rows = []
        for chamber, xs, offset in (("A", (0, 1, 2), 20), ("B", (3, 4, 5), -20)):
            for x in xs:
                for repeat in range(8):
                    noise = 0.03*math.sin(x*7+repeat)
                    rows.append({"factors": {"x": x}, "metrics": {"y": offset+2*x+noise}, "chamber": chamber})
        defs = {"x": {"role": "controllable", "unit": "mm"}}
        pooled, _ = fit_linear_model(rows, defs, "y")
        adjusted, _ = fit_linear_model(rows, defs, "y", {"fixed_effect_fields": ["chamber"]})
        self.assertGreater(abs(pooled["terms"]["x"]["estimate"]-2), 1.0)
        self.assertAlmostEqual(adjusted["terms"]["x"]["estimate"], 2.0, delta=0.02)
        self.assertEqual(adjusted["model_specification"]["fixed_effect_fields"], ["chamber"])

    def test_formula_sensitivity_flags_sign_reversal_when_chamber_effects_are_omitted(self):
        rows = []
        cells = (("A", 0, 40, 10.0), ("A", 1, 2, 8.0),
                 ("B", 0, 2, 20.0), ("B", 1, 40, 18.0))
        index = 0
        for chamber, x, count, center in cells:
            for _repeat in range(count):
                rows.append({"id": f"SYN-FORMULA-{index}", "factors": {"x": float(x)},
                             "metrics": {"y": center+0.02*math.sin(index*1.7)},
                             "chamber": chamber, "lot_id": f"SYN-LOT-{index}"})
                index += 1
        definitions = {"x": {"role": "controllable", "unit": "unit"}}
        options = {"fixed_effect_fields": ["chamber"], "independent_unit_field": "lot_id",
                   "covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30}
        base, _ = fit_linear_model(rows, definitions, "y", options)
        self.assertEqual(base["status"], "VALID")
        self.assertAlmostEqual(base["terms"]["x"]["estimate"], -2.0, delta=0.01)
        sensitivity = _model_specification_sensitivity(rows, definitions, "y", options, base)
        self.assertEqual(sensitivity["status"], "COMPLETED_DIAGNOSTIC")
        self.assertTrue(sensitivity["factor_stability"]["x"]["sign_reversal_observed"])
        no_fixed = next(item for item in sensitivity["variants"] if item["formula"] == "without_declared_fixed_effects")
        self.assertGreater(no_fixed["factor_terms"]["x"]["estimate"], 0)
        self.assertEqual(sensitivity["model_selection"],
                         "none; the caller formula is retained and no variant is chosen by these diagnostics")

    def test_formula_sensitivity_retains_a_quadratic_alternative_without_selecting_it(self):
        rows = []
        for lot in range(40):
            shift = 0.03*math.sin(lot)
            for x in (-2.0, -1.0, 0.0, 1.0, 2.0):
                rows.append({"id": f"SYN-QUAD-{lot}-{x}", "factors": {"x": x},
                             "metrics": {"y": 4.0+1.5*x+0.8*x*x+shift+0.02*math.sin(lot+x)},
                             "lot_id": f"SYN-LOT-{lot}"})
        definitions = {"x": {"role": "controllable", "unit": "unit"}}
        options = {"independent_unit_field": "lot_id", "covariance": "cluster",
                   "cluster_field": "lot_id", "minimum_clusters": 30}
        base, _ = fit_linear_model(rows, definitions, "y", options)
        sensitivity = _model_specification_sensitivity(rows, definitions, "y", options, base)
        quadratic = next(item for item in sensitivity["variants"] if item["formula"] == "quadratic_additive")
        self.assertEqual(quadratic["status"], "VALID")
        self.assertEqual(sensitivity["model_selection"].split(";")[0], "none")

    def test_chamber_specific_slopes_are_estimable_when_requested(self):
        rows = []
        for chamber, slope in (("A", 1.0), ("B", 5.0)):
            for x in range(6):
                for repeat in range(12):
                    noise = 0.01 * math.sin(x * 5 + repeat)
                    rows.append({"factors": {"x": float(x)}, "metrics": {"y": 3 + slope*x + noise},
                                 "chamber": chamber})
        report, model = fit_linear_model(
            rows, {"x": {"role": "controllable", "unit": "mm"}}, "y",
            {"fixed_effect_fields": ["chamber"], "fixed_effect_interactions": [["chamber", "x"]]})
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["model_specification"]["fixed_effect_interactions"], [["chamber", "x"]])
        pred_a0 = model.predict({"x": 0.0}, {"chamber": "A"})["estimate"]
        pred_a5 = model.predict({"x": 5.0}, {"chamber": "A"})["estimate"]
        pred_b0 = model.predict({"x": 0.0}, {"chamber": "B"})["estimate"]
        pred_b5 = model.predict({"x": 5.0}, {"chamber": "B"})["estimate"]
        self.assertAlmostEqual((pred_a5-pred_a0)/5.0, 1.0, delta=0.02)
        self.assertAlmostEqual((pred_b5-pred_b0)/5.0, 5.0, delta=0.02)

    def test_quadratic_model_recovers_held_out_nonlinear_response(self):
        rows = []
        for x in range(-5, 6):
            for j in range(5):
                noise = 0.02*math.sin(x*3+j)
                rows.append({"factors": {"x": x}, "metrics": {"y": 1+1.5*x+0.7*x*x+noise}})
        defs = {"x": {"role": "controllable", "unit": "u"}}
        linear, linear_model = fit_linear_model(rows, defs, "y")
        quadratic, quadratic_model = fit_linear_model(rows, defs, "y", {"quadratic": True})
        heldout_x = 5.5
        truth = 1+1.5*heldout_x+0.7*heldout_x**2
        linear_error = abs(linear_model.predict({"x": heldout_x})["estimate"]-truth)
        quadratic_error = abs(quadratic_model.predict({"x": heldout_x})["estimate"]-truth)
        self.assertLess(quadratic_error, linear_error/10)
        self.assertEqual(quadratic["model_specification"]["quadratic"], ["x"])

    def test_identifiability_and_degenerate_residuals_withhold_inference(self):
        rows = [{"factors": {"a": x, "b": 2*x}, "metrics": {"y": 4*x}} for x in range(1, 8)]
        report, model = fit_linear_model(rows, {"a": {"role": "controllable", "unit": "u"},
                                                "b": {"role": "controllable", "unit": "u"}}, "y")
        self.assertEqual(report["status"], "INCONCLUSIVE")
        self.assertIsNone(model)
        exact, fitted = fit_linear_model([{"factors": {"x": x}, "metrics": {"y": 3+2*x}} for x in range(8)],
                                         {"x": {"role": "controllable", "unit": "u"}}, "y")
        self.assertTrue(exact["diagnostics"]["degenerate_residual_variation"])
        self.assertIsNone(exact["terms"]["x"]["ci95"])
        self.assertEqual(fitted.predict({"x": 4})["status"], "UNCERTAINTY_UNAVAILABLE")

    def test_influence_diagnostics_flag_high_leverage_and_outlier(self):
        high_rows = [{"id": f"SYN-{i}", "factors": {"x": x}, "metrics": {"y": 1+2*x}}
                     for i, x in enumerate([0, 1, 2, 3, 4, 25, 6, 7, 8, 9])]
        high, _ = fit_linear_model(high_rows, {"x": {"role": "controllable", "unit": "u"}}, "y")
        self.assertIn("SYN-5", high["diagnostics"]["high_leverage_observation_ids"])
        outlier_rows = [{"id": f"OUT-{i}", "factors": {"x": i % 6},
                         "metrics": {"y": 1+2*(i % 6) + (100 if i == 13 else 0)}} for i in range(36)]
        outlier, _ = fit_linear_model(outlier_rows, {"x": {"role": "controllable", "unit": "u"}}, "y")
        self.assertIn("OUT-13", outlier["diagnostics"]["internally_studentized_residual_outlier_ids"])


class SupportedWindowQualification(unittest.TestCase):
    def _dataset(self, levels=(0, 1, 2), resolution=5, bounds=None, forbidden=None, radius=0.65, min_points=3):
        rng = random.Random(431)
        rows = []
        for lot in range(50):
            lot_shift = 0.025 * (-1 if lot % 2 else 1) + 0.005*math.sin(lot)
            for x in levels:
                for y in levels:
                    response = 0.12+(x-1)**2*0.12+(y-1)**2*0.12+lot_shift+rng.uniform(-0.018, 0.018)
                    rows.append(row(len(rows), x, y, response, lot_id=f"LOT-{lot:02d}",
                                    analysis_partition="CALIBRATION" if lot % 5 < 2 else "TRAIN"))
        factors = {name: dict(value) for name, value in FACTOR.items()}
        if bounds is not None:
            for name in ("pressure", "power"):
                factors[name]["bounds"] = list(bounds)
        data = {"model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                          "quadratic": True, "interactions": True},
                "window_exploration": {"factors": ["pressure", "power"], "independent_unit_field": "lot_id",
                                       "min_independent_units": 30, "grid_points": resolution,
                                       "min_support_points": min_points, "max_support_radius": radius,
                                       "calibration": {"group_field": "lot_id", "partition_field": "analysis_partition",
                                                       "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                                                       "minimum_calibration_units": 19,
                                                       "split_reference": "SYN-DO02-INTERLEAVED-001",
                                                       "precommit": {"plan_reference": "SYN-PRECOMMIT-PLAN-001",
                                                                     "model_selection_reference": "SYN-PRECOMMIT-MODEL-001",
                                                                     "threshold_selection_reference": "SYN-PRECOMMIT-THRESHOLDS-001",
                                                                     "metric_family": ["quality"],
                                                                     "exact_setting_panel": [
                                                                         {"pressure": float(x), "power": float(y)}
                                                                         for x in levels for y in levels]}}},
                "forbidden_regions": forbidden or []}
        return rows, factors, data

    def test_supported_surface_marks_observed_interpolated_and_conservative_candidates(self):
        rows, factors, data = self._dataset()
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "VALID")
        self.assertGreater(result["region_counts"]["interpolated"], 0)
        self.assertGreater(result["candidate_count"], 0)
        center = next(cell for cell in result["grid"] if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        self.assertEqual(center["region_class"], "observed")
        self.assertTrue(center["supported_candidate"])
        self.assertIn("predictive_interval95", center["predictions"]["quality"])
        self.assertEqual(center["predictions"]["quality"]["calibration_status"], "LOCAL_GROUP_HOLDOUT_EMPIRICAL")
        self.assertEqual(center["predictions"]["quality"]["calibration_units"], 20)
        self.assertEqual(result["calibration"]["training_unit_count"], 30)
        self.assertEqual(result["calibration"]["calibration_unit_count"], 20)
        self.assertEqual(result["candidate_scope"], "ADVISORY_POINTWISE_SCREENING_ONLY")
        self.assertEqual(result["joint_validation_status"], "NOT_ESTABLISHED")
        self.assertIn("Selection among cells can inflate false-feasible findings", result["selection_warning"])
        self.assertEqual(result["independent_candidate_evaluation"]["status"], "NOT_PROVIDED")

    def test_untouched_lot_evaluation_is_separate_from_candidate_selection(self):
        rows, factors, data = self._dataset()
        for item in rows:
            lot = int(item["lot_id"].split("-")[1])
            item["analysis_partition"] = (
                "TRAIN" if lot < 20 else "CALIBRATION" if lot < 40 else "EVALUATION")
        data["model"]["minimum_clusters"] = 20
        data["window_exploration"]["min_independent_units"] = 20
        calibration = data["window_exploration"]["calibration"]
        calibration["evaluation_value"] = "EVALUATION"
        calibration["split_reference"] = "SYN-PRECOMMITTED-TRAIN-CAL-EVAL-001"

        baseline = explore_window(rows, factors, METRIC, data)
        self.assertEqual(baseline["calibration"]["evaluation_unit_count"], 10)
        heldout = baseline["independent_candidate_evaluation"]
        self.assertEqual(heldout["status"], "DESCRIPTIVE")
        self.assertGreater(heldout["evaluated_candidate_count"], 0)
        self.assertIn("do not establish population", heldout["method"])

        shifted = [dict(item, metrics=dict(item["metrics"])) for item in rows]
        for item in shifted:
            if item["analysis_partition"] == "EVALUATION":
                item["metrics"]["quality"] += 1.0
        challenged = explore_window(shifted, factors, METRIC, data)
        self.assertEqual([cell["factors"] for cell in baseline["candidate_cells"]],
                         [cell["factors"] for cell in challenged["candidate_cells"]])
        self.assertEqual(challenged["independent_candidate_evaluation"]["status"], "DESCRIPTIVE")
        scored = [cell for cell in challenged["independent_candidate_evaluation"]["candidates"]
                  if cell["status"] == "DESCRIPTIVE_HELDOUT_DIAGNOSTIC"]
        self.assertGreater(len(scored), 0)
        self.assertTrue(all(cell["observed_infeasible_fraction"] == 1.0 for cell in scored))

    def test_simultaneous_exact_setting_band_rejects_a_pointwise_false_feasible_after_grid_selection(self):
        rows, factors, data = self._dataset()
        # One calibration lot has a hidden corner failure. Local intervals at
        # the center do not see it, but a max score over the complete 3x3 panel
        # must account for selecting among all exact settings after calibration.
        for item in rows:
            if (item["lot_id"] == "LOT-00" and item["analysis_partition"] == "CALIBRATION"
                    and item["factors"] == {"pressure": 0.0, "power": 0.0}):
                item["metrics"]["quality"] += 0.6
                break
        result = explore_window(rows, factors, METRIC, data)
        screen = result["simultaneous_exact_setting_screen"]
        self.assertEqual(screen["status"], "AVAILABLE")
        self.assertEqual(screen["calibration_unit_count"], 20)
        self.assertEqual(len(screen["common_exact_settings"]), 9)
        self.assertIn("Under exchangeability", screen["assumption_conditional_statement"])
        center = next(cell for cell in result["grid"] if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        self.assertTrue(center["supported_candidate"])
        self.assertFalse(center["simultaneous_supported_candidate"])
        self.assertGreater(
            center["predictions"]["quality"]["simultaneous_group_error_radius"],
            center["predictions"]["quality"]["calibration_quantile95_absolute_error"])
        self.assertEqual(result["joint_validation_status"], "NOT_ESTABLISHED")
        self.assertEqual(screen["precommit"]["status"], "CALLER_SUPPLIED_NOT_AUTHENTICATED")
        self.assertEqual(len(screen["precommit"]["plan_sha256"]), 64)

    def test_simultaneous_metric_multiplicity_abstains_when_finite_rank_is_unavailable(self):
        rows, factors, data = self._dataset()
        for item in rows:
            lot = int(item["lot_id"].split("-")[1])
            pressure = item["factors"]["pressure"]
            power = item["factors"]["power"]
            item["metrics"]["defect"] = (0.1 + 0.01*pressure + 0.002*math.sin(lot)
                                           + 0.001*math.sin(power*2 + pressure))
        metric_defs = {**METRIC, "defect": {"unit": "%", "direction": "minimize", "max": 0.2}}
        data["window_exploration"]["calibration"]["precommit"]["metric_family"] = ["quality", "defect"]
        result = explore_window(rows, factors, metric_defs, data)
        screen = result["simultaneous_exact_setting_screen"]
        self.assertEqual(screen["status"], "INSUFFICIENT_CALIBRATION_UNITS")
        self.assertEqual(screen["order_statistic_rank"], 21)
        self.assertEqual(result["simultaneous_candidate_count"], 0)
        self.assertTrue(all(cell["predictions"]["quality"]["simultaneous_group_interval95"] is None
                            for cell in result["grid"]))

    def test_simultaneous_band_requires_identical_calibration_setting_panels(self):
        rows, factors, data = self._dataset()
        rows.remove(next(item for item in rows if item["lot_id"] == "LOT-00"
                         and item["analysis_partition"] == "CALIBRATION"
                         and item["factors"] == {"pressure": 0.0, "power": 0.0}))
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["simultaneous_exact_setting_screen"]["status"], "INCOMPLETE_CALIBRATION_PANEL")
        self.assertEqual(result["simultaneous_candidate_count"], 0)

    def test_simultaneous_band_requires_a_precommitted_complete_panel(self):
        rows, factors, data = self._dataset()
        data["window_exploration"]["calibration"].pop("precommit")
        result = explore_window(rows, factors, METRIC, data)
        screen = result["simultaneous_exact_setting_screen"]
        self.assertEqual(screen["status"], "PRECOMMIT_NOT_PROVIDED")
        self.assertEqual(result["simultaneous_candidate_count"], 0)
        self.assertGreater(result["candidate_count"], 0)

    def test_simultaneous_band_withholds_if_declared_panel_differs_from_calibration(self):
        rows, factors, data = self._dataset()
        data["window_exploration"]["calibration"]["precommit"]["exact_setting_panel"].pop()
        result = explore_window(rows, factors, METRIC, data)
        screen = result["simultaneous_exact_setting_screen"]
        self.assertEqual(screen["status"], "INCOMPLETE_CALIBRATION_PANEL")
        self.assertEqual(screen["declared_exact_setting_count"], 8)
        self.assertEqual(screen["observed_exact_setting_count"], 9)
        self.assertEqual(result["simultaneous_candidate_count"], 0)

    def test_simultaneous_band_requires_reference_to_preselected_metric_family(self):
        rows, factors, data = self._dataset()
        data["window_exploration"]["calibration"]["precommit"]["metric_family"] = ["unconstrained_quality"]
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["simultaneous_exact_setting_screen"]["status"], "PRECOMMIT_METRIC_FAMILY_MISMATCH")
        self.assertEqual(result["simultaneous_candidate_count"], 0)

    def test_independent_unit_cannot_cross_evaluation_and_calibration(self):
        rows, factors, data = self._dataset()
        for item in rows:
            lot = int(item["lot_id"].split("-")[1])
            item["analysis_partition"] = (
                "TRAIN" if lot < 20 else "CALIBRATION" if lot < 40 else "EVALUATION")
        data["model"]["minimum_clusters"] = 20
        data["window_exploration"]["min_independent_units"] = 20
        calibration = data["window_exploration"]["calibration"]
        calibration["evaluation_value"] = "EVALUATION"
        calibration["split_reference"] = "SYN-PRECOMMITTED-TRAIN-CAL-EVAL-002"
        next(row for row in rows if row["analysis_partition"] == "TRAIN")["analysis_partition"] = "EVALUATION"
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("crosses the training and calibration", result["reason"])

    def test_unseen_nonlinear_interaction_creates_false_feasible_interpolated_cell(self):
        """An untouched nonlinear mechanism can defeat local calibration between tested settings."""
        rng = random.Random(90210)
        rows = []
        observed_levels = (0.0, 1.0, 2.0)
        grid_levels = (0.0, 0.5, 1.0, 1.5, 2.0)
        for lot in range(70):
            if lot < 30:
                partition, levels = "TRAIN", observed_levels
            elif lot < 50:
                partition, levels = "CALIBRATION", observed_levels
            else:
                partition, levels = "EVALUATION", grid_levels
            lot_offset = 0.003 * math.sin(lot * 0.71)
            for x in levels:
                for y in levels:
                    smooth_surface = 0.10 + 0.02*((x-1)**2 + (y-1)**2)
                    # This response is zero at all integer training/calibration settings,
                    # but nonzero between them; the independent evaluator observes it.
                    unseen_interaction = 0.12 * math.sin(math.pi*x) * math.sin(math.pi*y)
                    rows.append({"id": f"SYN-SEL-{lot}-{x}-{y}",
                                 "factors": {"pressure": x, "power": y},
                                 "metrics": {"quality": smooth_surface + unseen_interaction
                                             + lot_offset + rng.gauss(0, 0.0015)},
                                 "lot_id": f"LOT-{lot:02d}", "analysis_partition": partition})
        factors = {name: dict(value) for name, value in FACTOR.items()}
        metric = {"quality": {"unit": "score", "direction": "minimize", "max": 0.20}}
        data = {"model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                          "quadratic": True, "interactions": True},
                "window_exploration": {"factors": ["pressure", "power"], "independent_unit_field": "lot_id",
                                       "min_independent_units": 30, "grid_points": 5,
                                       "min_support_points": 3, "max_support_radius": 0.65,
                                       "calibration": {"group_field": "lot_id", "partition_field": "analysis_partition",
                                                       "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                                                       "evaluation_value": "EVALUATION",
                                                       "minimum_calibration_units": 19,
                                                       "split_reference": "SYN-PRECOMMITTED-HIDDEN-INTERACTION-001"}}}

        result = explore_window(rows, factors, metric, data)
        self.assertGreater(result["candidate_count"], 1,
                           "the adversarial region was selected from multiple simultaneously screened cells")
        hidden_cell = next(cell for cell in result["candidate_cells"]
                           if cell["factors"] == {"pressure": 0.5, "power": 0.5})
        self.assertEqual(hidden_cell["region_class"], "interpolated")
        self.assertLess(hidden_cell["predictions"]["quality"]["predictive_interval95"][1], 0.20)
        evaluation = next(cell for cell in result["independent_candidate_evaluation"]["candidates"]
                          if cell["factors"] == hidden_cell["factors"])
        self.assertEqual(evaluation["independent_units"], 20)
        self.assertEqual(evaluation["observed_infeasible_fraction"], 1.0)
        self.assertEqual(result["joint_validation_status"], "NOT_ESTABLISHED")
        selection_audit = result["independent_candidate_evaluation"]["candidate_selection_audit"]
        self.assertEqual(selection_audit["status"], "DESCRIPTIVE_SETWISE_DIAGNOSTIC")
        self.assertEqual(selection_audit["candidate_count"], result["candidate_count"])
        self.assertEqual(selection_audit["complete_independent_units"], 20)
        self.assertEqual(selection_audit["observed_any_infeasible_units"], 20)
        self.assertEqual(selection_audit["observed_any_infeasible_fraction"], 1.0)
        self.assertEqual(selection_audit["guarantee"], "none; descriptive only and not a multiplicity-adjusted or population guarantee")

    def test_heldout_tool_and_future_period_effects_are_cross_classified(self):
        rows, factors, data = self._dataset()
        for item in rows:
            item["tool_id"] = "TOOL-A" if int(item["lot_id"].split("-")[1]) % 2 == 0 else "TOOL-B"
            item["event_year"] = 2026
        combinations = (("TOOL-A", 2026, 0.0), ("TOOL-UNSEEN", 2026, 1.0),
                        ("TOOL-A", 2027, 1.0), ("TOOL-UNSEEN", 2027, 2.0))
        for lot in range(50, 70):
            tool_id, event_year, shift = combinations[(lot-50)//5]
            for x in (0, 1, 2):
                for y in (0, 1, 2):
                    value = 0.12+(x-1)**2*0.12+(y-1)**2*0.12+shift+0.002*math.sin(lot+x+y)
                    rows.append(row(len(rows), x, y, value, lot_id=f"LOT-{lot:02d}",
                                    analysis_partition="EVALUATION", tool_id=tool_id, event_year=event_year))
        data["window_exploration"]["min_independent_units"] = 30
        data["window_exploration"]["evaluation_strata"] = ["tool_id", "event_year"]
        data["window_exploration"]["calibration"]["evaluation_value"] = "EVALUATION"
        data["window_exploration"]["calibration"]["split_reference"] = "SYN-PRECOMMITTED-UNSEEN-TOOL-FUTURE-001"

        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["calibration"]["evaluation_unit_count"], 20)
        evaluated = next(candidate for candidate in result["independent_candidate_evaluation"]["candidates"]
                         if candidate["factors"] == {"pressure": 1.0, "power": 1.0})
        self.assertEqual(evaluated["observed_infeasible_fraction"], 0.75)
        stratified = evaluated["stratified_evaluation"]
        self.assertEqual(stratified["status"], "DESCRIPTIVE")
        self.assertEqual(stratified["fields"], ["tool_id", "event_year"])
        self.assertEqual(len(stratified["categories"]), 4)
        by_stratum = {(item["values"]["tool_id"], item["values"]["event_year"]): item
                      for item in stratified["categories"]}
        self.assertEqual(by_stratum[("TOOL-A", 2026)]["observed_infeasible_units"], 0)
        for key in (("TOOL-UNSEEN", 2026), ("TOOL-A", 2027), ("TOOL-UNSEEN", 2027)):
            self.assertEqual(by_stratum[key]["independent_units"], 5)
            self.assertEqual(by_stratum[key]["observed_infeasible_units"], 5)
            self.assertAlmostEqual(by_stratum[key]["wilson95_descriptive_interval"][0], 0.5655, places=3)
            self.assertEqual(by_stratum[key]["wilson95_descriptive_interval"][1], 1.0)

    def test_evaluation_requires_exact_fixed_modeled_controls(self):
        rows, factors, data = self._dataset()
        factors["humidity"] = {"role": "measured", "unit": "%"}
        data["model"]["factor_fields"] = ["pressure", "power", "humidity"]
        data["window_exploration"]["fixed_settings"] = {"humidity": 50.0}
        for item in rows:
            lot = int(item["lot_id"].split("-")[1])
            item["analysis_partition"] = "TRAIN" if lot < 20 else "CALIBRATION" if lot < 40 else "EVALUATION"
            item["factors"]["humidity"] = 40.0 + 5.0 * (lot % 5)
            item["metrics"]["quality"] += 0.002 * (item["factors"]["humidity"] - 50.0)
        for item in rows:
            if item["analysis_partition"] == "EVALUATION":
                item["factors"]["humidity"] = 90.0
        data["model"]["minimum_clusters"] = 20
        data["window_exploration"]["min_independent_units"] = 20
        data["window_exploration"]["calibration"]["evaluation_value"] = "EVALUATION"
        data["window_exploration"]["calibration"]["split_reference"] = "SYN-PRECOMMITTED-FIXED-CONTROL-001"

        result = explore_window(rows, factors, METRIC, data)
        evaluated = next(candidate for candidate in result["independent_candidate_evaluation"]["candidates"]
                         if candidate["factors"]["pressure"] == 1.0 and candidate["factors"]["power"] == 1.0)
        self.assertEqual(evaluated["independent_units"], 0)
        self.assertEqual(evaluated["population_incompatible_units"], 10)
        self.assertEqual(evaluated["status"], "NO_EXACT_SETTING_EVALUATION_DATA")

    def test_d02_requires_independent_group_holdout_and_finite_95_percent_rank(self):
        rows, factors, data = self._dataset()
        data["window_exploration"].pop("calibration")
        refused = explore_window(rows, factors, METRIC, data)
        self.assertEqual(refused["status"], "INCONCLUSIVE")
        self.assertEqual(refused["candidate_cells"], [])
        self.assertIsNone(_finite_rank_quantile(list(range(1, 19))))
        self.assertEqual(_finite_rank_quantile(list(range(1, 20))), 19)

    def test_d02_rejects_an_independent_unit_split_across_training_and_calibration(self):
        rows, factors, data = self._dataset()
        next(row for row in rows if row["analysis_partition"] == "TRAIN")["analysis_partition"] = "CALIBRATION"
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("crosses the training and calibration", result["reason"])

    def test_calibration_outcomes_change_uncertainty_without_leaking_into_model_fit(self):
        rows, factors, data = self._dataset()
        baseline = explore_window(rows, factors, METRIC, data)
        changed = [dict(item, metrics=dict(item["metrics"])) for item in rows]
        for item in changed:
            if item["analysis_partition"] == "CALIBRATION":
                item["metrics"]["quality"] += 10.0
        recalibrated = explore_window(changed, factors, METRIC, data)
        center = lambda result: next(cell for cell in result["grid"]
                                     if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        before = center(baseline)["predictions"]["quality"]
        after = center(recalibrated)["predictions"]["quality"]
        self.assertAlmostEqual(before["estimate"], after["estimate"], places=12)
        self.assertGreater(after["calibration_quantile95_absolute_error"],
                           before["calibration_quantile95_absolute_error"] + 9.0)
        self.assertEqual(recalibrated["candidate_count"], 0)

    def test_new_tool_shift_in_heldout_groups_withholds_candidate_window(self):
        rows, factors, data = self._dataset()
        for item in rows:
            item["tool_id"] = item["lot_id"]
            if item["analysis_partition"] == "CALIBRATION":
                item["metrics"]["quality"] += 1.0
        data["model"]["cluster_field"] = "tool_id"
        data["window_exploration"]["independent_unit_field"] = "tool_id"
        data["window_exploration"]["calibration"]["group_field"] = "tool_id"
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["candidate_count"], 0)
        calibrated = [cell["predictions"]["quality"] for cell in result["grid"]
                      if cell["predictions"]["quality"].get("calibration_status") == "LOCAL_GROUP_HOLDOUT_EMPIRICAL"]
        self.assertTrue(calibrated)
        self.assertTrue(all(item["calibration_quantile95_absolute_error"] > 0.9 for item in calibrated))

    def test_local_group_calibration_covers_separately_heldout_nonlinear_lots(self):
        rows = []
        for lot in range(50):
            partition = "CALIBRATION" if lot % 5 < 2 else "TRAIN"
            lot_shift = 0.03 * math.sin(lot * 0.7)
            for pressure in (0.0, 1.0, 2.0):
                for power in (0.0, 1.0, 2.0):
                    noise = 0.01 * math.sin(lot * 1.7 + pressure * 1.1 + power * 0.9)
                    quality = 0.15 + 0.12 * (pressure-1)**2 + 0.12 * (power-1)**2 + lot_shift + noise
                    rows.append({"id": f"FIT-{lot}-{pressure}-{power}", "factors": {"pressure": pressure, "power": power},
                                 "metrics": {"quality": quality}, "lot_id": f"FIT-LOT-{lot}",
                                 "analysis_partition": partition})
        data = {"model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                          "quadratic": True, "interactions": True},
                "window_exploration": {"factors": ["pressure", "power"], "independent_unit_field": "lot_id",
                                       "min_independent_units": 30, "grid_points": 5, "min_support_points": 3,
                                       "max_support_radius": 0.65,
                                       "calibration": {"group_field": "lot_id", "partition_field": "analysis_partition",
                                                       "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                                                       "minimum_calibration_units": 19,
                                                       "split_reference": "SYN-INTERLEAVED-HOLDOUT-001"}}}
        result = explore_window(rows, FACTOR, METRIC, data)
        center = next(cell for cell in result["grid"]
                      if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        lower, upper = center["predictions"]["quality"]["predictive_interval95"]
        eval_groups = 100
        covered_groups = 0
        for lot in range(50, 50 + eval_groups):
            noise = 0.01 * math.sin(lot * 1.7 + 1.1 + 0.9)
            outcome = 0.15 + 0.03 * math.sin(lot * 0.7) + noise
            covered_groups += int(lower <= outcome <= upper)
        self.assertEqual(center["predictions"]["quality"]["calibration_status"], "LOCAL_GROUP_HOLDOUT_EMPIRICAL")
        self.assertIn("no distribution-free conditional coverage guarantee",
                      center["predictions"]["quality"]["calibration_method"])
        self.assertGreaterEqual(covered_groups / eval_groups, 0.95)

    def test_outside_observed_hull_is_extrapolated_and_never_a_candidate(self):
        rows, factors, data = self._dataset(bounds=(-0.5, 2.5))
        result = explore_window(rows, factors, METRIC, data)
        self.assertGreater(result["region_counts"]["extrapolated"], 0)
        self.assertTrue(all(not cell["supported_candidate"] for cell in result["grid"] if cell["region_class"] == "extrapolated"))

    def test_sparse_local_support_is_unsupported_even_inside_convex_hull(self):
        rows, factors, data = self._dataset(levels=(0, 2), radius=0.2, min_points=3)
        data["model"]["quadratic"] = False
        data["model"]["interactions"] = False
        result = explore_window(rows, factors, METRIC, data)
        center = next(cell for cell in result["grid"] if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        self.assertEqual(center["region_class"], "unsupported")
        self.assertFalse(center["supported_candidate"])

    def test_forbidden_region_overrides_support_and_candidate_status(self):
        rows, factors, data = self._dataset(forbidden=[{"pressure": [0.9, 1.1], "power": [0.9, 1.1]}])
        result = explore_window(rows, factors, METRIC, data)
        center = next(cell for cell in result["grid"] if cell["factors"] == {"pressure": 1.0, "power": 1.0})
        self.assertEqual(center["region_class"], "forbidden")
        self.assertFalse(center["supported_candidate"])

    def test_invalid_forbidden_region_fails_closed(self):
        rows, factors, data = self._dataset(forbidden=[{"secret_factor": [0, 1]}])
        with self.assertRaises(ValueError):
            explore_window(rows, factors, METRIC, data)

    def test_repeated_units_without_matching_cluster_covariance_withhold_window(self):
        rows, factors, data = self._dataset()
        data["model"]["covariance"] = "HC3"
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("repeated independent units require cluster-robust", result["reason"])

    def test_omitted_control_is_fixed_in_the_fitted_population(self):
        rows = []
        for lot in range(50):
            lot_shift = 0.01 * math.sin(lot)
            for pressure in (0.0, 1.0, 2.0):
                for power in (0.0, 1.0, 2.0):
                    y = 0.12 + 0.08*pressure + 0.15*power + lot_shift + 0.005*math.sin(lot+pressure+power)
                    rows.append({"id": f"ROW-{len(rows)}", "factors": {"pressure": pressure, "power": power},
                                 "metrics": {"quality": y}, "lot_id": f"LOT-{lot}",
                                 "analysis_partition": "CALIBRATION" if lot % 5 < 2 else "TRAIN"})
        factors = {name: dict(value) for name, value in FACTOR.items()}
        data = {"model": {"factor_fields": ["pressure"], "covariance": "cluster", "cluster_field": "lot_id",
                          "minimum_clusters": 30},
                "window_exploration": {"factors": ["pressure"], "fixed_settings": {"power": 1.0},
                                       "independent_unit_field": "lot_id", "min_independent_units": 30,
                                       "grid_points": 5, "min_support_points": 2, "max_support_radius": 0.65,
                                       "calibration": {"group_field": "lot_id", "partition_field": "analysis_partition",
                                                       "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                                                       "minimum_calibration_units": 19,
                                                       "split_reference": "SYN-DO02-INTERLEAVED-001"}}}
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["model_diagnostics"]["quality"]["n"], 30*3)
        self.assertEqual(result["omitted_controls_held_at_fixed_setting"], ["power"])
        self.assertTrue(all(cell["factors"]["power"] == 1.0 for cell in result["grid"]))


if __name__ == "__main__":
    unittest.main()
