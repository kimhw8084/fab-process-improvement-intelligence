"""Fixed and independent qualification of non-factorial D04 plans."""
import math
import random
import unittest
from datetime import datetime, timedelta, timezone

from qualification.benchmark_d04_aliasing import run_benchmark as run_aliasing_benchmark
from products.p4.design import (assign_blocks, propose_design, propose_multiobjective_next_best,
                                propose_window_confirmation)


class DesignQualification(unittest.TestCase):
    def setUp(self):
        self.controls = ["a", "b", "c", "d"]
        self.bounds = {name: [0.0, 1.0] for name in self.controls}

    def test_off_grid_aliasing_challenge_distinguishes_existing_design_geometries(self):
        result = run_aliasing_benchmark(trials=1, seed=20261124)
        self.assertEqual(result["schema"], "p4-d04-design-aliasing-benchmark/v2")
        self.assertEqual(result["status"], "PASS_GEOMETRY_CHALLENGE")
        for name in ("full_factorial", "central_composite", "d_optimal"):
            self.assertEqual(result["strategies"][name]["trials_with_signal_over_epsilon"], 0)
        self.assertEqual(result["strategies"]["latin_hypercube"]["trials_with_signal_over_epsilon"], 1)
        for name in ("fractional_factorial", "full_factorial", "central_composite", "d_optimal"):
            self.assertEqual(result["four_factor_strategies"][name]["trials_with_signal_over_epsilon"], 0)
        self.assertEqual(result["four_factor_strategies"]["latin_hypercube"]["trials_with_signal_over_epsilon"], 1)
        self.assertFalse(result["statistical_power_evaluated"])

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

    def test_face_centered_central_composite_recovers_full_quadratic_geometry_within_bounds(self):
        controls = ["a", "b"]
        bounds = {"a": [-2.0, 2.0], "b": [10.0, 20.0]}
        result = propose_design("central_composite", controls, bounds,
                                {"run_budget": 10, "blocks": 2, "seed": 42}, [])
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["run_count"], 10)
        self.assertEqual(result["factorial_runs"], 4)
        self.assertEqual(result["axial_runs"], 4)
        self.assertEqual(result["center_replicates"], 2)
        self.assertEqual(result["quadratic_model_matrix_rank"], 6)
        self.assertEqual(result["model_terms"], ["intercept", "a", "b", "a^2", "b^2", "a:b"])
        self.assertFalse(result["executed"])
        observed = set()
        for run in result["runs"]:
            self.assertGreaterEqual(bounds["a"][1], run["a"])
            self.assertLessEqual(bounds["a"][0], run["a"])
            self.assertGreaterEqual(bounds["b"][1], run["b"])
            self.assertLessEqual(bounds["b"][0], run["b"])
            observed.add((round(run["a"]/2.0-0.0, 8), round((run["b"]-15.0)/5.0, 8)))
        expected = {(-1.0, -1.0), (-1.0, 0.0), (-1.0, 1.0), (0.0, -1.0),
                    (0.0, 0.0), (0.0, 1.0), (1.0, -1.0), (1.0, 0.0), (1.0, 1.0)}
        self.assertEqual(observed, expected)

    def test_central_composite_refuses_forbidden_deletion_and_underbudget(self):
        with self.assertRaisesRegex(ValueError, "requires 10 runs"):
            propose_design("central_composite", ["a", "b"], {"a": [0, 1], "b": [0, 1]},
                           {"run_budget": 9}, [])
        with self.assertRaisesRegex(ValueError, "forbidden region intersects"):
            propose_design("central_composite", ["a", "b"], {"a": [0, 1], "b": [0, 1]},
                           {"run_budget": 10}, [{"a": [0.49, 0.51], "b": [0.49, 0.51]}])

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

    def _timed_sequential_rows(self, late_shift=0.0):
        rows = self._sequential_rows()
        for row in rows:
            lot = int(row["lot_id"][1:])
            timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(days=lot)
            row["event_ts"] = timestamp.isoformat().replace("+00:00", "Z")
            if lot >= 30:
                row["metrics"]["quality"] += late_shift
        return rows

    @staticmethod
    def _time_split_spec():
        return {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "validation_time_split": {
                    "timestamp_field": "event_ts", "training_end": "2026-01-30T00:00:00Z",
                    "evaluation_start": "2026-01-31T00:00:00Z", "split_reference": "SYN-D04-TIME-SPLIT"},
                "maximum_grouped_validation_rmse": 0.2}

    def test_next_best_supports_predeclared_time_ordered_independent_unit_holdout(self):
        result = propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                                self._time_split_spec(), [], self._timed_sequential_rows(),
                                {"quality": {"direction": "maximize"}},
                                {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                                 "quadratic": True, "interactions": True})
        validation = result["grouped_surface_validation"]
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(validation["development_group_count"], 30)
        self.assertEqual(validation["evaluation_group_count"], 6)
        self.assertEqual(validation["validation_split"]["type"],
                         "PREDECLARED_TIME_ORDERED_INDEPENDENT_UNIT_HOLDOUT")
        self.assertEqual(validation["validation_split"]["split_reference_status"],
                         "CALLER_SUPPLIED_NOT_AUTHENTICATED")
        self.assertIsNone(validation["validation_seed"])
        self.assertEqual(validation["development_cv_seed"], 13)
        self.assertIn("chronological", validation["method"])
        self.assertFalse(result["executed"])

    def test_next_best_temporal_shift_fails_engineer_rmse_gate(self):
        rows = self._timed_sequential_rows(late_shift=0.5)
        random_spec = self._time_split_spec()
        random_spec.pop("validation_time_split")
        random_result = propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                                       random_spec, [], rows,
                                       {"quality": {"direction": "maximize"}},
                                       {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                                        "quadratic": True, "interactions": True})
        self.assertLessEqual(random_result["grouped_surface_validation"]["independent_evaluation"]["rmse"], 0.2)
        with self.assertRaisesRegex(ValueError, "untouched grouped evaluation error .* exceeds maximum_grouped_validation_rmse") as caught:
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                           self._time_split_spec(), [], rows,
                           {"quality": {"direction": "maximize"}},
                           {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                            "quadratic": True, "interactions": True})
        self.assertIn("PREDECLARED_TIME_ORDERED_INDEPENDENT_UNIT_HOLDOUT", str(caught.exception))
        self.assertIn("0.2", str(caught.exception))

    def test_next_best_refuses_time_split_group_leakage_and_gap_rows(self):
        for mutate, message in (
                (lambda rows: rows[0].update(event_ts="2026-01-31T00:00:00Z"),
                 "independent unit crosses the time-ordered"),
                (lambda rows: rows[0].update(event_ts="2026-01-30T12:00:00Z"),
                 "buffer-gap rows are not silently dropped")):
            rows = self._timed_sequential_rows()
            mutate(rows)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                               self._time_split_spec(), [], rows,
                               {"quality": {"direction": "maximize"}},
                               {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                                "quadratic": True, "interactions": True})

    def _constrained_sequential_rows(self):
        rng = random.Random(413)
        rows = []
        for lot in range(36):
            shift = 0.03*math.sin(lot*1.3)
            for a in (0.0, 1.0, 2.0):
                for b in (0.0, 1.0, 2.0):
                    quality = 10-(a-1.8)**2-1.2*(b-1.0)**2+shift+rng.uniform(-0.004, 0.004)
                    defect = 0.5+a+0.04*(b-1.0)**2+0.02*math.sin(lot*0.7)
                    rows.append({"factors": {"a": a, "b": b},
                                 "metrics": {"quality": quality, "defect": defect},
                                 "lot_id": f"SYN-LOT-{lot}"})
        return rows

    def test_next_best_selects_one_supported_unobserved_point_with_uncertainty(self):
        rows = self._sequential_rows()
        factors = ["a", "b"]
        bounds = {name: [0, 2] for name in factors}
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1, "target_metric": "quality", "candidate_levels": 9,
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
        groups = sorted({row["lot_id"] for row in rows})
        random.Random(12).shuffle(groups)
        holdout_count = min(round(len(groups)*0.2), len(groups)-30)
        development_groups = set(groups[holdout_count:])
        means = {}
        for row in rows:
            if row["lot_id"] not in development_groups:
                continue
            setting = (row["factors"]["a"], row["factors"]["b"])
            means.setdefault(setting, []).append(row["metrics"]["quality"])
        expected_incumbent = max(sum(values)/len(values) for values in means.values())
        self.assertAlmostEqual(result["observed_incumbent"]["mean"], expected_incumbent)
        self.assertLess(result["observed_incumbent"]["mean"], max(row["metrics"]["quality"] for row in rows))
        validation = result["grouped_surface_validation"]
        self.assertGreaterEqual(validation["development_group_count"], 30)
        self.assertGreaterEqual(validation["evaluation_group_count"], 3)
        self.assertEqual(validation["model_selection"]["method"], "5-fold grouped CV on development units")
        self.assertLessEqual(validation["independent_evaluation"]["rmse"], 0.2)
        self.assertEqual(result["model_selection"]["data_used_for_candidate_selection"],
                         "development independent units only")

    def test_multiobjective_next_best_returns_separate_supported_options_without_scalar_choice(self):
        controls = ["a", "b"]
        rows = self._constrained_sequential_rows()
        for row in rows:
            lot = int(row["lot_id"].rsplit("-", 1)[1])
            row["metrics"]["safety"] = 0.1+0.01*row["factors"]["a"]+0.005*math.sin(lot)
        spec = {"run_budget": 1, "blocks": 1, "seed": 12, "validation_seed": 12,
                "candidate_levels": 9, "independent_unit_field": "lot_id",
                "min_independent_units": 30, "maximum_grouped_validation_rmse": 0.2,
                "constraint_metrics": ["safety"],
                "maximum_grouped_validation_rmse_by_metric": {"safety": 0.2}}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        plan = propose_multiobjective_next_best(
            controls, {name: [0, 2] for name in controls}, spec, [], rows,
            [{"metric": "quality", "direction": "maximize"},
             {"metric": "defect", "direction": "minimize"}],
            {"quality": {"unit": "score", "direction": "maximize"},
             "defect": {"unit": "rate", "direction": "minimize"},
             "safety": {"unit": "rate", "max": 0.5}}, model)
        self.assertEqual(plan["status"], "PROPOSED")
        self.assertEqual(plan["run_count"], 0)
        self.assertEqual(plan["runs"], [])
        self.assertEqual(plan["alternative_count"], 2)
        self.assertEqual([item["objective_metric"] for item in plan["run_options"]],
                         ["quality", "defect"])
        self.assertEqual({item["grouped_surface_validation"]["validation_split"]["validation_seed"]
                          for item in plan["run_options"]}, {12})
        self.assertTrue(all(item["prediction"]["status"] == "ESTIMATED"
                            and item["grouped_surface_validation"]["independent_evaluation"]["status"] == "COMPLETED_DIAGNOSTIC"
                            for item in plan["run_options"]))
        self.assertTrue(all(item["constraint_predictions"]["safety"]["status"] == "MODEL_INTERVAL_WITHIN_SUPPLIED_BOUNDS"
                            for item in plan["run_options"]))
        self.assertIn("no combined score", plan["selection_policy"])
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["actuation"], "none")

    def test_multiobjective_next_best_withholds_incomplete_objective_slate(self):
        controls = ["a", "b"]
        rows = self._constrained_sequential_rows()
        for row in rows:
            row["metrics"]["flat"] = 7.0
        spec = {"run_budget": 1, "blocks": 1, "seed": 12, "validation_seed": 12,
                "candidate_levels": 9, "independent_unit_field": "lot_id",
                "min_independent_units": 30, "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        with self.assertRaisesRegex(ValueError, "no unobserved candidate|estimable"):
            propose_multiobjective_next_best(
                controls, {name: [0, 2] for name in controls}, spec, [], rows,
                [{"metric": "quality", "direction": "maximize"},
                 {"metric": "flat", "direction": "maximize"}],
                {"quality": {"unit": "score"}, "flat": {"unit": "score"}}, model)

    def test_multiobjective_next_best_requires_single_run_budget_and_unique_metrics(self):
        controls = ["a", "b"]
        rows = self._constrained_sequential_rows()
        definitions = {"quality": {"unit": "score"}, "defect": {"unit": "rate"}}
        objectives = [{"metric": "quality", "direction": "maximize"},
                      {"metric": "defect", "direction": "minimize"}]
        with self.assertRaisesRegex(ValueError, "run_budget and blocks must both be 1"):
            propose_multiobjective_next_best(controls, {name: [0, 2] for name in controls},
                                             {"run_budget": 2, "blocks": 1}, [], rows,
                                             objectives, definitions, {})
        with self.assertRaisesRegex(ValueError, "must be unique"):
            propose_multiobjective_next_best(controls, {name: [0, 2] for name in controls},
                                             {"run_budget": 1, "blocks": 1}, [], rows,
                                             [objectives[0], objectives[0]], definitions, {})
        with self.assertRaisesRegex(ValueError, "replicates must be 1"):
            propose_multiobjective_next_best(controls, {name: [0, 2] for name in controls},
                                             {"run_budget": 1, "blocks": 1, "replicates": 2}, [], rows,
                                             objectives, definitions, {})
        with self.assertRaisesRegex(ValueError, "conflicts with the defined direction"):
            propose_multiobjective_next_best(controls, {name: [0, 2] for name in controls},
                                             {"run_budget": 1, "blocks": 1}, [], rows,
                                             [{"metric": "quality", "direction": "minimize"}, objectives[1]],
                                             {**definitions, "quality": {"direction": "maximize"}}, {})

    def test_next_best_keeps_numeric_and_string_unit_ids_separate(self):
        rows = self._sequential_rows()
        for row in rows:
            original = int(row["lot_id"][1:])
            row["lot_id"] = original if original < 18 else str(original - 18)
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        result = propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                                spec, [], rows, {"quality": {"direction": "maximize"}}, model)
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["grouped_surface_validation"]["independent_group_count"], 36)
        self.assertEqual(result["observed_incumbent"]["independent_units"], 30)

    def test_next_best_rejects_missing_or_non_scalar_unit_ids(self):
        rows = self._sequential_rows()
        rows[0]["lot_id"] = {"untrusted": "nested identity"}
        spec = {"run_budget": 1, "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        with self.assertRaisesRegex(ValueError, "nonempty strings or integers"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]},
                           spec, [], rows, {"quality": {"direction": "maximize"}}, model)

    def test_next_best_excludes_forbidden_candidate_before_acquisition_ranking(self):
        rows = self._sequential_rows()
        controls = ["a", "b"]
        bounds = {name: [0, 2] for name in controls}
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        forbidden = [{"a": [1.2, 1.3], "b": [0.9, 1.1]}]
        result = propose_design("next_best", controls, bounds, spec, forbidden, rows,
                                {"quality": {"direction": "maximize"}}, model)
        run = result["runs"][0]
        self.assertFalse(1.2 <= run["a"] <= 1.3 and 0.9 <= run["b"] <= 1.1)
        self.assertGreater(result["support"]["forbidden_candidates_excluded"], 0)

    def test_next_best_screens_competing_metric_with_grouped_validation_and_predictive_bounds(self):
        rows = self._constrained_sequential_rows()
        controls = ["a", "b"]
        bounds = {name: [0, 2] for name in controls}
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2,
                "constraint_metrics": ["defect"],
                "maximum_grouped_validation_rmse_by_metric": {"defect": 0.2}}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        metrics = {"quality": {"direction": "maximize"},
                   "defect": {"direction": "minimize", "max": 1.9, "unit": "synthetic count"}}
        unconstrained_spec = {key: value for key, value in spec.items()
                              if key not in ("constraint_metrics", "maximum_grouped_validation_rmse_by_metric")}
        unconstrained = propose_design("next_best", controls, bounds, unconstrained_spec, [], rows,
                                       metrics, model)
        self.assertGreater(unconstrained["runs"][0]["a"], 1.25)
        result = propose_design("next_best", controls, bounds, spec, [], rows, metrics, model)
        proposal = result["runs"][0]
        screened = result["constraint_evaluation"]
        self.assertEqual(screened["status"], "MODEL_BASED_INTERVAL_SCREEN_ONLY")
        self.assertLessEqual(proposal["a"], 1.25)
        self.assertEqual(screened["selected_candidate"]["defect"]["status"],
                         "MODEL_INTERVAL_WITHIN_SUPPLIED_BOUNDS")
        self.assertLessEqual(screened["selected_candidate"]["defect"]["predictive_interval95"][1], 1.9)
        self.assertGreater(screened["rejected_candidate_count"], 0)
        self.assertEqual(screened["validation_by_metric"]["defect"]["independent_evaluation"]["status"],
                         "COMPLETED_DIAGNOSTIC")

    def test_next_best_requires_explicit_bounds_and_validation_error_for_constraint_metrics(self):
        rows = self._constrained_sequential_rows()
        spec = {"run_budget": 1, "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2, "constraint_metrics": ["defect"]}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        with self.assertRaisesRegex(ValueError, "needs an explicit engineering min or max bound"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}, "defect": {"direction": "minimize"}}, model)
        with self.assertRaisesRegex(ValueError, "needs its own positive grouped validation RMSE limit"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}, "defect": {"direction": "minimize", "max": 1.9}}, model)

    def test_next_best_selection_and_candidate_are_isolated_from_evaluation_groups(self):
        rows = self._sequential_rows()
        controls = ["a", "b"]
        bounds = {name: [0, 2] for name in controls}
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        baseline = propose_design("next_best", controls, bounds, spec, [], rows,
                                  {"quality": {"direction": "maximize"}}, model)
        groups = sorted({row["lot_id"] for row in rows})
        random.Random(12).shuffle(groups)
        holdout_count = min(round(len(groups)*0.2), len(groups)-30)
        evaluation_groups = set(groups[:holdout_count])
        shifted = [dict(row, metrics=dict(row["metrics"])) for row in rows]
        for row in shifted:
            if row["lot_id"] in evaluation_groups:
                row["metrics"]["quality"] += 0.1
        shifted_result = propose_design("next_best", controls, bounds, spec, [], shifted,
                                        {"quality": {"direction": "maximize"}}, model)
        self.assertEqual(baseline["runs"], shifted_result["runs"])
        self.assertEqual(baseline["expected_improvement"], shifted_result["expected_improvement"])
        self.assertEqual(baseline["grouped_surface_validation"]["model_selection"],
                         shifted_result["grouped_surface_validation"]["model_selection"])
        self.assertAlmostEqual(shifted_result["grouped_surface_validation"]["independent_evaluation"]["bias"],
                               baseline["grouped_surface_validation"]["independent_evaluation"]["bias"] - 0.1,
                               places=10)
        self.assertGreater(shifted_result["grouped_surface_validation"]["independent_evaluation"]["rmse"],
                           baseline["grouped_surface_validation"]["independent_evaluation"]["rmse"])

    def test_next_best_refuses_when_untouched_evaluation_groups_exceed_tolerance(self):
        rows = self._sequential_rows()
        groups = sorted({row["lot_id"] for row in rows})
        random.Random(12).shuffle(groups)
        holdout_count = min(round(len(groups)*0.2), len(groups)-30)
        evaluation_groups = set(groups[:holdout_count])
        for row in rows:
            if row["lot_id"] in evaluation_groups:
                row["metrics"]["quality"] += 0.5
        spec = {"run_budget": 1, "seed": 12, "validation_seed": 12, "blocks": 1,
                "target_metric": "quality", "candidate_levels": 9,
                "independent_unit_field": "lot_id", "min_independent_units": 30,
                "maximum_grouped_validation_rmse": 0.2}
        model = {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
                 "quadratic": True, "interactions": True}
        with self.assertRaisesRegex(ValueError, "untouched grouped evaluation error .* exceeds"):
            propose_design("next_best", ["a", "b"], {"a": [0, 2], "b": [0, 2]}, spec, [], rows,
                           {"quality": {"direction": "maximize"}}, model)

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

    def test_next_best_refuses_unqualified_joint_support_above_two_dimensions(self):
        rows = [{"factors": {"a": 0, "b": 0, "c": 0}, "metrics": {"quality": 1}, "lot_id": "L1"}]
        with self.assertRaisesRegex(ValueError, "no qualified joint-support geometry above two dimensions"):
            propose_design("next_best", ["a", "b", "c"],
                           {name: [0, 1] for name in ("a", "b", "c")},
                           {"run_budget": 1, "target_metric": "quality"}, [], rows,
                           {"quality": {"direction": "maximize"}}, {})


class WindowConfirmationQualification(unittest.TestCase):
    def setUp(self):
        self.controls = ["a", "b"]
        self.bounds = {"a": [0.0, 1.0], "b": [0.0, 1.0]}
        self.cell = {"factors": {"a": 0.5, "b": 0.5}, "region_class": "interpolated",
                     "supported_candidate": True, "simultaneous_supported_candidate": False,
                     "predictions": {"quality": {"predictive_interval95": [2.0, 2.6],
                                                    "simultaneous_group_interval95": None}}}
        self.window = {"status": "VALID", "candidate_cells": [self.cell],
                       "simultaneous_exact_setting_screen": {"status_scope": "NOT_AVAILABLE"}}
        self.metrics = {"quality": {"unit": "nm", "direction": "minimize", "max": 3.0}}
        self.spec = {"run_budget": 72, "seed": 12, "candidate_factors": {"a": 0.5, "b": 0.5},
                     "comparison_factors": {"a": 0.0, "b": 0.0}, "target_metric": "quality",
                     "objective_statement": "Confirm quality at the proposed setting versus the reference.",
                     "paired_difference_sd": 0.4, "paired_difference_sd_source": "SYN-PAIRED-SD-001",
                     "paired_difference_sd_basis": "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND",
                     "paired_difference_sd_confidence_level": 0.95,
                     "paired_difference_sd_degrees_of_freedom": 29,
                     "minimum_detectable_effect": 0.2, "minimum_detectable_effect_source": "SYN-MDE-001",
                     "alpha": 0.05, "target_power": 0.8}

    def test_confirmatory_plan_is_powered_pair_blocked_seeded_and_non_executing(self):
        first = propose_window_confirmation(self.window, self.controls, self.bounds, self.spec, [], self.metrics)
        second = propose_window_confirmation(self.window, self.controls, self.bounds, self.spec, [], self.metrics)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "PROPOSED")
        self.assertEqual(first["design"], "randomized blocked D02 candidate confirmation")
        self.assertEqual(first["claim_method"], "randomized_blocked_confirmation_proposal")
        self.assertFalse(first["executed"])
        self.assertEqual(first["actuation"], "none")
        self.assertEqual(first["run_count"], 70)
        self.assertEqual(first["power"]["required_complete_pairs"], 35)
        self.assertEqual(first["power"]["normal_approximation_reference_pairs"], 32)
        self.assertIn("Cornish-Fisher Student-t critical", first["power"]["method"])
        self.assertEqual(first["power"]["paired_difference_sd_basis"],
                         "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND")
        self.assertEqual(first["power"]["paired_sd_scope"],
                         "caller-supplied conservative upper bound; P4 does not recompute or authenticate it")
        self.assertIn("independent normal paired differences are required",
                      first["power"]["paired_difference_distribution_assumption"])
        self.assertIn("heavy tails", " ".join(first["power"]["approximation_limitations"]))
        self.assertFalse(first["candidate_evidence"]["simultaneous_supported_candidate"])
        self.assertEqual(first["candidate_evidence"]["target_metric_interval95"], [2.0, 2.6])
        grouped = {}
        for run in first["runs"]:
            grouped.setdefault(run["block"], []).append(run)
        self.assertEqual(len(grouped), 35)
        self.assertTrue(all({run["arm"] for run in pair} == {"candidate", "reference"}
                            and {run["order_within_block"] for run in pair} == {1, 2}
                            for pair in grouped.values()))
        self.assertEqual(first["evidence_required_before_next_iteration"][0],
                         "assigned and executed order with block and arm identity")

    def test_confirmation_refuses_candidate_not_in_d02_or_forbidden_reference(self):
        unknown = {**self.spec, "candidate_factors": {"a": 0.2, "b": 0.8}}
        self.assertEqual(propose_window_confirmation(self.window, self.controls, self.bounds, unknown,
                                                     [], self.metrics)["status"], "REFUSED")
        withheld = {**self.window, "candidate_cells": [{**self.cell, "supported_candidate": False}]}
        refused = propose_window_confirmation(withheld, self.controls, self.bounds, self.spec,
                                              [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertIn("no longer retained", refused["reason"])
        extrapolated = {**self.window, "candidate_cells": [{**self.cell, "region_class": "extrapolated"}]}
        refused = propose_window_confirmation(extrapolated, self.controls, self.bounds, self.spec,
                                              [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertIn("observed or supported interpolated", refused["reason"])
        forbidden = [{"a": [0.0, 0.1]}]
        refused = propose_window_confirmation(self.window, self.controls, self.bounds, self.spec,
                                              forbidden, self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertIn("forbidden region", refused["reason"])

    def test_confirmation_refuses_inconsistent_withheld_d02_envelopes(self):
        contradictory_results = (
            {**self.window, "candidate_screening_status": "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE"},
            {**self.window, "candidate_counterevidence": {"status": "WITHHELD_COMPLETE_SET_INFEASIBILITY"}},
            {**self.window, "candidate_count": 0},
        )
        for contradictory in contradictory_results:
            with self.subTest(contradictory=contradictory):
                refused = propose_window_confirmation(
                    contradictory, self.controls, self.bounds, self.spec, [], self.metrics)
                self.assertEqual(refused["status"], "REFUSED")
                self.assertEqual(refused["run_count"], 0)
                self.assertFalse(refused["executed"])

    def test_confirmation_refuses_unprovenanced_power_inputs_and_underbudget_plans(self):
        missing_source = {**self.spec, "paired_difference_sd_source": ""}
        self.assertEqual(propose_window_confirmation(self.window, self.controls, self.bounds,
                                                     missing_source, [], self.metrics)["status"], "REFUSED")
        underbudget = {**self.spec, "run_budget": 10}
        refused = propose_window_confirmation(self.window, self.controls, self.bounds,
                                              underbudget, [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertEqual(refused["required_pair_count"], 35)
        self.assertEqual(refused["required_runs"], 70)

    def test_confirmation_refuses_point_sd_estimates_and_requires_bound_metadata(self):
        point_estimate = {**self.spec, "paired_difference_sd_basis": "POINT_ESTIMATE",
                          "paired_difference_sd_confidence_level": None,
                          "paired_difference_sd_degrees_of_freedom": None}
        refused = propose_window_confirmation(self.window, self.controls, self.bounds,
                                              point_estimate, [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertIn("point estimate is not sufficient", refused["reason"])
        missing_bound_df = {**self.spec, "paired_difference_sd_degrees_of_freedom": None}
        refused = propose_window_confirmation(self.window, self.controls, self.bounds,
                                              missing_bound_df, [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertIn("degrees of freedom", refused["reason"])
        low_confidence = {**self.spec, "paired_difference_sd_confidence_level": 0.9}
        refused = propose_window_confirmation(self.window, self.controls, self.bounds,
                                              low_confidence, [], self.metrics)
        self.assertEqual(refused["status"], "REFUSED")

    def test_engineer_hard_sd_bound_is_distinguished_from_chi_square_normality(self):
        hard_bound = {**self.spec, "paired_difference_sd_basis": "ENGINEER_APPROVED_HARD_BOUND",
                      "paired_difference_sd_confidence_level": None,
                      "paired_difference_sd_degrees_of_freedom": None}
        proposal = propose_window_confirmation(self.window, self.controls, self.bounds,
                                               hard_bound, [], self.metrics)
        self.assertEqual(proposal["status"], "PROPOSED")
        assumption = proposal["power"]["paired_difference_distribution_assumption"]
        self.assertIn("engineer-approved hard SD upper bound", assumption)
        self.assertNotIn("required for the one-sided chi-square", assumption)
        self.assertIn("target-power approximation is suitable",
                      " ".join(proposal["required_engineer_review"]))


if __name__ == "__main__":
    unittest.main()
