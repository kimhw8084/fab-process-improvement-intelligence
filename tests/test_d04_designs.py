"""Fixed and independent qualification of non-factorial D04 plans."""
import math
import random
import unittest

from products.p4.design import assign_blocks, propose_design


class DesignQualification(unittest.TestCase):
    def setUp(self):
        self.controls = ["a", "b", "c", "d"]
        self.bounds = {name: [0.0, 1.0] for name in self.controls}

    def test_fractional_factorial_has_resolution_four_and_reproducible_alias_description(self):
        spec = {"run_budget": 8, "seed": 12, "blocks": 2}
        one = propose_design("fractional_factorial", self.controls, self.bounds, spec, [])
        two = propose_design("fractional_factorial", self.controls, self.bounds, spec, [])
        self.assertEqual(one, two)
        self.assertEqual(one["run_count"], 8)
        self.assertEqual(one["resolution"], 4)
        self.assertFalse(one["executed"])
        self.assertEqual(len({tuple(run[k] for k in self.controls) for run in one["runs"]}), 8)
        for i, left in enumerate(self.controls):
            for right in self.controls[i+1:]:
                product_sum = sum((2*run[left]-1)*(2*run[right]-1) for run in one["runs"])
                self.assertEqual(product_sum, 0)
        self.assertEqual(one["blocking"]["block_sizes"], [4, 4])
        self.assertEqual(set(one["blocking"]["factor_level_count_max_difference"].values()), {0})
        self.assertIn("record the assigned block", one["blocking"]["analysis_requirement"])

    def test_fractional_factorial_refuses_low_resolution_and_underbudget(self):
        with self.assertRaises(ValueError):
            propose_design("fractional_factorial", self.controls[:3], self.bounds, {"run_budget": 4}, [])
        with self.assertRaises(ValueError):
            propose_design("fractional_factorial", self.controls, self.bounds, {"run_budget": 7}, [])
        with self.assertRaisesRegex(ValueError, "forbidden regions remove runs"):
            propose_design("fractional_factorial", self.controls, self.bounds, {"run_budget": 8},
                           [{"a": [-2.0, 2.0]}])

    def test_block_assignment_is_cancellable_and_level_balanced(self):
        runs = [{name: index % 2 for name in self.controls} for index in range(12)]
        with self.assertRaises(InterruptedError):
            assign_blocks(runs, self.controls, 3, 7, cancel=lambda: True)
        blocking = assign_blocks(runs, self.controls, 3, 7)
        self.assertEqual(blocking["block_sizes"], [4, 4, 4])
        self.assertTrue(all(value == 0 for value in blocking["factor_level_count_max_difference"].values()))

    def test_latin_hypercube_is_seeded_and_stratified_on_each_margin(self):
        spec = {"run_budget": 12, "seed": 991, "blocks": 3}
        first = propose_design("latin_hypercube", self.controls, self.bounds, spec, [])
        second = propose_design("latin_hypercube", self.controls, self.bounds, spec, [])
        self.assertEqual(first, second)
        for name in self.controls:
            counts = [sum((i/12) <= run[name] < ((i+1)/12) for run in first["runs"]) for i in range(12)]
            self.assertEqual(counts, [1]*12)
        self.assertEqual(first["blocking"]["block_sizes"], [4, 4, 4])
        self.assertEqual(set(first["blocking"]["factor_level_count_max_difference"].values()), {1})
        self.assertFalse(first["executed"])

    def test_d_optimal_design_is_full_rank_and_beats_seeded_random_design(self):
        controls = ["a", "b"]
        bounds = {name: [-1.0, 1.0] for name in controls}
        result = propose_design("d_optimal", controls, bounds,
                               {"run_budget": 6, "candidate_levels": 3, "seed": 41, "blocks": 1}, [])
        def determinant(points):
            rows = [[1.0, point["a"], point["b"]] for point in points]
            info = [[sum(r[i]*r[j] for r in rows) for j in range(3)] for i in range(3)]
            a = [row[:] for row in info]
            det = 1.0
            for col in range(3):
                pivot = max(range(col, 3), key=lambda i: abs(a[i][col]))
                if abs(a[pivot][col]) < 1e-12:
                    return 0.0
                a[col], a[pivot] = a[pivot], a[col]
                det *= a[col][col]
                for i in range(col+1, 3):
                    scale = a[i][col]/a[col][col]
                    for j in range(col+1, 3):
                        a[i][j] -= scale*a[col][j]
            return abs(det)
        grid = [{"a": a, "b": b} for a in (-1.0, 0.0, 1.0) for b in (-1.0, 0.0, 1.0)]
        rng = random.Random(8)
        random_scores = [determinant(rng.sample(grid, 6)) for _ in range(100)]
        self.assertGreater(determinant(result["runs"]), sum(random_scores)/len(random_scores))
        self.assertEqual(result["model_terms"], ["intercept", "a", "b"])

    def _sequential_rows(self):
        rng = random.Random(77)
        rows = []
        for lot in range(36):
            shift = 0.04*math.sin(lot)
            for x in (0.0, 1.0, 2.0):
                for y in (0.0, 1.0, 2.0):
                    metric = 10 - (x-1)**2 - 1.5*(y-1)**2 + shift + rng.uniform(-0.02, 0.02)
                    rows.append({"factors": {"a": x, "b": y}, "metrics": {"quality": metric}, "lot_id": f"L{lot}"})
        return rows

    def test_next_best_selects_one_supported_unobserved_point_with_uncertainty(self):
        rows = self._sequential_rows()
        factors = ["a", "b"]
        bounds = {name: [0, 2] for name in factors}
        spec = {"run_budget": 1, "seed": 12, "blocks": 1, "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        result = propose_design("next_best", factors, bounds, spec, [], rows,
                                {"quality": {"direction": "maximize"}}, model)
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["run_count"], 1)
        self.assertFalse(result["executed"])
        self.assertGreater(result["expected_improvement"], 0)
        self.assertIn("mean_standard_error", result["prediction"])
        self.assertTrue(0 <= result["runs"][0]["a"] <= 2)
        self.assertTrue(0 <= result["runs"][0]["b"] <= 2)
        self.assertNotIn((result["runs"][0]["a"], result["runs"][0]["b"]),
                         {(row["factors"]["a"], row["factors"]["b"]) for row in rows})
        means = {}
        for row in rows:
            setting = (row["factors"]["a"], row["factors"]["b"])
            means.setdefault(setting, []).append(row["metrics"]["quality"])
        expected_incumbent = max(sum(values)/len(values) for values in means.values())
        self.assertAlmostEqual(result["observed_incumbent"]["mean"], expected_incumbent)
        self.assertLess(result["observed_incumbent"]["mean"], max(row["metrics"]["quality"] for row in rows))
        self.assertLessEqual(result["grouped_surface_validation"]["quadratic_rmse"], 0.2)

    def test_next_best_rejects_repeated_units_without_cluster_robust_uncertainty(self):
        rows = self._sequential_rows()
        spec = {"run_budget": 1, "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        with self.assertRaisesRegex(ValueError, "repeated independent units require cluster-robust"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}}, {"covariance": "HC3"})

    def test_next_best_requires_and_enforces_engineer_prediction_tolerance(self):
        rows = self._sequential_rows()
        spec = {"run_budget": 1, "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        with self.assertRaisesRegex(ValueError, "engineer-specified positive maximum_grouped_validation_rmse"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}}, model)
        spec["maximum_grouped_validation_rmse"] = 1e-8
        with self.assertRaisesRegex(ValueError, "exceeds maximum_grouped_validation_rmse"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}}, model)

    def test_next_best_refuses_without_independent_unit_support(self):
        spec = {"run_budget": 1, "target_metric": "quality"}
        with self.assertRaises(ValueError):
            propose_design("next_best", ["a"], {"a": [0, 1]}, spec, [], [],
                           {"quality": {"direction": "maximize"}}, {})


if __name__ == "__main__":
    unittest.main()
