"""Independent adversarial checks for robust modeling and D02 support rules."""
from __future__ import annotations

import math
import random
import unittest

from products.p4.regression import fit_linear_model
from products.p4.window import explore_window


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
        small, _ = fit_linear_model(rows[:80], {"x": {"role": "controllable", "unit": "u"}}, "y", options)
        self.assertEqual(small["status"], "INCONCLUSIVE")
        self.assertIsNone(small["terms"]["x"]["ci95"])

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
        for lot in range(36):
            lot_shift = 0.025 * (-1 if lot % 2 else 1) + 0.005*math.sin(lot)
            for x in levels:
                for y in levels:
                    response = 0.12+(x-1)**2*0.12+(y-1)**2*0.12+lot_shift+rng.uniform(-0.018, 0.018)
                    rows.append(row(len(rows), x, y, response, lot_id=f"LOT-{lot:02d}"))
        factors = {name: dict(value) for name, value in FACTOR.items()}
        if bounds is not None:
            for name in ("pressure", "power"):
                factors[name]["bounds"] = list(bounds)
        data = {"model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                          "quadratic": True, "interactions": True},
                "window_exploration": {"factors": ["pressure", "power"], "independent_unit_field": "lot_id",
                                       "min_independent_units": 30, "grid_points": resolution,
                                       "min_support_points": min_points, "max_support_radius": radius},
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
        for lot in range(36):
            lot_shift = 0.01 * math.sin(lot)
            for pressure in (0.0, 1.0, 2.0):
                for power in (0.0, 1.0, 2.0):
                    y = 0.12 + 0.08*pressure + 0.15*power + lot_shift + 0.005*math.sin(lot+pressure+power)
                    rows.append({"id": f"ROW-{len(rows)}", "factors": {"pressure": pressure, "power": power},
                                 "metrics": {"quality": y}, "lot_id": f"LOT-{lot}"})
        factors = {name: dict(value) for name, value in FACTOR.items()}
        data = {"model": {"factor_fields": ["pressure"], "covariance": "cluster", "cluster_field": "lot_id",
                          "minimum_clusters": 30},
                "window_exploration": {"factors": ["pressure"], "fixed_settings": {"power": 1.0},
                                       "independent_unit_field": "lot_id", "min_independent_units": 30,
                                       "grid_points": 5, "min_support_points": 2, "max_support_radius": 0.65}}
        result = explore_window(rows, factors, METRIC, data)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["model_diagnostics"]["quality"]["n"], 36*3)
        self.assertEqual(result["omitted_controls_held_at_fixed_setting"], ["power"])
        self.assertTrue(all(cell["factors"]["power"] == 1.0 for cell in result["grid"]))


if __name__ == "__main__":
    unittest.main()
