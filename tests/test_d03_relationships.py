"""Independent fail-closed and numeric qualification for cross-step tradeoffs."""
import copy
import unittest

from products.p4.tradeoffs import _familywise_t_critical, cross_step_tradeoffs, observed_tradeoffs
from products.p4.engine import analyze


class CrossStepTradeoffQualification(unittest.TestCase):
    def setUp(self):
        self.metric_defs = {"yield": {"direction": "maximize", "unit": "%"},
                            "defect": {"direction": "minimize", "unit": "count"}}
        self.data = {
            "multi_step": True,
            "objectives": [{"metric": "yield", "direction": "maximize"},
                           {"metric": "defect", "direction": "minimize"}],
            "sources": [{"id": "SYN-UPSTREAM"}, {"id": "SYN-DOWNSTREAM"}],
            "linkage": {
                "approved": True, "relationship_id": "SYN-REL-01", "contract_version": "1.0.0",
                "approval_reference": "SYN-APPROVAL-01", "maximum_lag_seconds": 86400,
                "unit_field": "unit_id", "decision_factors": ["pressure"], "minimum_independent_units": 30,
                "upstream": {"source_id": "SYN-UPSTREAM", "key_field": "upstream.unit_id",
                              "event_time_field": "upstream.event_ts", "population_field": "upstream.population_id",
                              "population_id": "SYN-COHORT-01", "metric_field": "metrics.yield", "metric": "yield"},
                "downstream": {"source_id": "SYN-DOWNSTREAM", "key_field": "downstream.unit_id",
                                "event_time_field": "downstream.event_ts", "population_field": "downstream.population_id",
                                "population_id": "SYN-COHORT-01", "metric_field": "metrics.defect", "metric": "defect"}}
        }
        self.rows = []
        for setting, avg_yield, avg_defect in ((1, 80, 5), (2, 85, 6), (3, 82, 4)):
            for unit in range(30):
                noise = ((unit % 5)-2)*0.04
                unit_id = f"SYN-UNIT-{setting}-{unit:02d}"
                self.rows.append({"id": f"SYN-PAIR-{setting}-{unit:02d}", "unit_id": unit_id,
                    "factors": {"pressure": float(setting)},
                    "metrics": {"yield": avg_yield+noise, "defect": avg_defect-noise*0.3},
                    "source_ids": ["SYN-UPSTREAM", "SYN-DOWNSTREAM"],
                    "upstream": {"unit_id": unit_id, "event_ts": "2026-01-01T00:00:00Z", "population_id": "SYN-COHORT-01"},
                    "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T03:00:00Z", "population_id": "SYN-COHORT-01"}})

    def test_paired_population_metrics_and_uncertainty_produce_hand_checked_front(self):
        result = cross_step_tradeoffs(self.rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["pareto_observation_ids"], ["SYN-SETTING-2", "SYN-SETTING-3"])
        setting2 = next(item for item in result["candidate_settings"] if item["factors"]["pressure"] == 2)
        self.assertAlmostEqual(setting2["means"]["yield"], 85.0)
        self.assertEqual(setting2["independent_units"], 30)
        self.assertIn("marginal_ci95", setting2["uncertainty"]["defect"])
        self.assertFalse(result["multiplicity_adjusted"])
        self.assertFalse(result["causal_claim"])
        self.assertIn({"dominant_setting_id": "SYN-SETTING-3", "dominated_setting_id": "SYN-SETTING-1",
                       "scope": "marginal_95_interval_separation_only"}, result["interval_separated_dominance"])
        self.assertEqual(setting2["mean_pareto_status"], "NONDOMINATED_BY_MEANS")
        self.assertEqual(result["familywise_mean_envelope"]["status"], "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE")
        self.assertIn({"dominant_setting_id": "SYN-SETTING-3", "dominated_setting_id": "SYN-SETTING-1",
                       "scope": "Bonferroni_familywise_simultaneous_mean_rectangles"},
                      result["familywise_interval_separated_dominance"])
        self.assertIn("SYN-SETTING-2", result["familywise_nondominated_setting_ids"])

    def test_mismatched_keys_and_duplicate_units_withhold_tradeoffs(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["downstream"]["unit_id"] = "SYN-DIFFERENT"
        self.assertEqual(cross_step_tradeoffs(rows, self.metric_defs, self.data)["status"], "LIMITED_SCOPE")
        rows = copy.deepcopy(self.rows)
        rows[1]["unit_id"] = rows[0]["unit_id"]
        self.assertEqual(cross_step_tradeoffs(rows, self.metric_defs, self.data)["status"], "LIMITED_SCOPE")

    def test_population_or_temporal_incompatibility_withholds_downstream_claim(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["downstream"]["population_id"] = "SYN-OTHER-COHORT"
        self.assertEqual(cross_step_tradeoffs(rows, self.metric_defs, self.data)["status"], "LIMITED_SCOPE")
        rows = copy.deepcopy(self.rows)
        rows[0]["downstream"]["event_ts"] = "2026-01-04T00:00:00Z"
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["downstream_claim"], "withheld")

    def test_missing_source_approval_is_not_inferred_from_field_similarity(self):
        data = copy.deepcopy(self.data)
        data["sources"] = [{"id": "SYN-UPSTREAM"}]
        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")

    def test_contract_cannot_claim_company_approval(self):
        data = copy.deepcopy(self.data)
        data["linkage"]["relationship_id"] = "FAB-REAL-RELATIONSHIP"
        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")

    def test_mean_pareto_front_does_not_hide_overlapping_uncertainty(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            unit = int(row["unit_id"].rsplit("-", 1)[1])
            noise = ((unit % 5)-2) * 10.0
            row["metrics"]["yield"] += noise
            row["metrics"]["defect"] -= noise * 0.3
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["pareto_status_scope"].split(";")[0], "mean-based observed front")
        self.assertEqual(result["interval_separated_dominance"], [])
        self.assertIn("SYN-SETTING-2", result["mean_pareto_setting_ids"])
        self.assertIn("SYN-SETTING-3", result["mean_pareto_setting_ids"])
        self.assertEqual(result["familywise_interval_separated_dominance"], [])

        missing_objective = copy.deepcopy(self.data)
        missing_objective["objectives"] = missing_objective["objectives"][:1]
        refused = cross_step_tradeoffs(self.rows, self.metric_defs, missing_objective)
        self.assertEqual(refused["status"], "LIMITED_SCOPE")
        self.assertEqual(refused["downstream_claim"], "withheld")

    def test_cross_step_metric_constraints_screen_whole_units_and_report_excluded_settings(self):
        metric_defs = copy.deepcopy(self.metric_defs)
        metric_defs["defect"]["max"] = 5.0
        result = cross_step_tradeoffs(self.rows, metric_defs, self.data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertGreater(result["constraint_exclusion_audit"]["excluded_independent_units"], 0)
        setting2 = next(item for item in result["constraint_exclusion_audit"]["settings"]
                        if item["factors"]["pressure"] == 2.0)
        self.assertEqual(setting2["all_independent_units"], 30)
        self.assertEqual(setting2["eligible_independent_units"], 0)
        self.assertEqual(setting2["excluded_independent_units"], 30)
        self.assertIn("per-setting exclusion audit", result["selection_warning"])
        self.assertTrue(all(item["means"]["defect"] <= 5.0 for item in result["candidate_settings"]))

    def test_cross_step_rejects_empty_relationship_unit_identity(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["unit_id"] = ""
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertIn("unit identity is missing", result["reason"])

    def test_observed_tradeoffs_report_whole_unit_constraint_selection(self):
        from products.p4.tradeoffs import observed_tradeoffs

        rows = copy.deepcopy(self.rows)
        rows.append({**copy.deepcopy(next(row for row in rows if row["unit_id"] == "SYN-UNIT-1-02")),
                     "id": "SYN-REPEAT-1-02", "metrics": {"yield": 140.0, "defect": 9.0}})
        metric_defs = copy.deepcopy(self.metric_defs)
        metric_defs["defect"]["max"] = 5.0
        result = observed_tradeoffs(rows, metric_defs, {"pressure": {"role": "controllable"}},
                                    {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3},
                                    self.data["objectives"])

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["constraint_exclusion_audit"]["excluded_independent_units"], 43)
        self.assertIn("may not be comparable to the full source population", result["selection_warning"])
        setting1 = next(item for item in result["candidate_settings"] if item["factors"]["pressure"] == 1)
        self.assertEqual(setting1["constraint_eligibility"]["all_independent_units"], 30)
        self.assertEqual(setting1["constraint_eligibility"]["eligible_independent_units"], 17)
        self.assertEqual(setting1["constraint_eligibility"]["excluded_independent_units"], 13)
        self.assertEqual(setting1["constraint_eligibility"]["all_observation_count"], 31)
        self.assertEqual(setting1["constraint_eligibility"]["eligible_observation_count"], 17)
        self.assertEqual(setting1["constraint_eligibility"]["excluded_observation_count"], 14)
        setting2_audit = next(item for item in result["constraint_exclusion_audit"]["settings"]
                              if item["factors"]["pressure"] == 2)
        self.assertEqual(setting2_audit["eligible_independent_units"], 0)
        self.assertEqual(setting2_audit["excluded_independent_units"], 30)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_AFTER_OUTCOME_BASED_CONSTRAINT_SELECTION")

    def test_observed_familywise_comparison_requires_a_matched_unit_cohort(self):
        from products.p4.tradeoffs import observed_tradeoffs

        objectives = self.data["objectives"]
        unmatched = observed_tradeoffs(self.rows, self.metric_defs,
                                       {"pressure": {"role": "controllable"}},
                                       {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3},
                                       objectives)
        self.assertEqual(unmatched["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_INCOMPATIBLE_INDEPENDENT_UNIT_COHORTS")
        matched_rows = copy.deepcopy(self.rows)
        for row in matched_rows:
            row["unit_id"] = "SYN-UNIT-" + row["unit_id"].rsplit("-", 1)[1]
        matched = observed_tradeoffs(matched_rows, self.metric_defs,
                                     {"pressure": {"role": "controllable"}},
                                     {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3},
                                     objectives)
        self.assertEqual(matched["familywise_mean_envelope"]["status"],
                         "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE")
        self.assertEqual(matched["familywise_mean_envelope"]["population_compatibility"],
                         "IDENTICAL_INDEPENDENT_UNIT_SET_AT_EVERY_INCLUDED_SETTING")

    def test_mixed_type_unit_ids_remain_distinct_in_observed_pareto_means(self):
        rows = []
        values = {
            1: [(1, 100, 0), ("1", 0, 100), ("2", 0, 0)],
            2: [(1, 39, 41), ("1", 40, 40), ("2", 41, 39)],
        }
        for pressure, units in values.items():
            for unit_id, yield_value, defect_value in units:
                rows.append({"id": f"OBS-{pressure}-{type(unit_id).__name__}-{unit_id}",
                             "unit_id": unit_id, "factors": {"pressure": pressure},
                             "metrics": {"yield": yield_value, "defect": defect_value}})
        objectives = [{"metric": "yield", "direction": "maximize"},
                      {"metric": "defect", "direction": "minimize"}]
        result = observed_tradeoffs(
            rows, {"yield": {"direction": "maximize", "unit": "%"},
                   "defect": {"direction": "minimize", "unit": "count"}},
            {"pressure": {"role": "controllable"}},
            {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 2},
            objectives)
        expected_front = ["SYN-SETTING-1", "SYN-SETTING-2"]
        self.assertEqual(result["pareto_setting_ids"], expected_front)
        first = next(item for item in result["candidate_settings"] if item["factors"]["pressure"] == 1)
        self.assertEqual(first["independent_units"], 3)
        self.assertAlmostEqual(first["means"]["yield"], 100/3)
        self.assertAlmostEqual(first["means"]["defect"], 100/3)
        incomplete_rows = copy.deepcopy(rows)
        del incomplete_rows[0]["unit_id"]
        incomplete = observed_tradeoffs(
            incomplete_rows, {"yield": {"direction": "maximize", "unit": "%"},
                              "defect": {"direction": "minimize", "unit": "count"}},
            {"pressure": {"role": "controllable"}},
            {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 2},
            objectives)
        self.assertEqual(incomplete["status"], "LIMITED_SCOPE")
        self.assertEqual(incomplete["pareto_observation_ids"], [])

    def test_familywise_envelope_abstains_for_small_setting_samples(self):
        rows = [row for row in self.rows if int(row["unit_id"].rsplit("-", 1)[1]) < 8]
        data = copy.deepcopy(self.data)
        data["linkage"]["minimum_independent_units"] = 3
        result = cross_step_tradeoffs(rows, self.metric_defs, data)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_REQUIRES_11_INDEPENDENT_UNITS_PER_SETTING")
        self.assertTrue(all(item["uncertainty"]["yield"]["familywise_ci95"] is None
                            for item in result["candidate_settings"]))

    def test_familywise_t_critical_matches_independent_scipy_oracle_on_supported_domain(self):
        try:
            from scipy.stats import t as student_t
        except ImportError:
            self.skipTest("optional SciPy critical-value oracle is unavailable")
        for df in range(10, 301):
            for family_size in (1, 2, 5, 10, 20, 40):
                with self.subTest(df=df, family_size=family_size):
                    actual = _familywise_t_critical(df, family_size)
                    expected = student_t.ppf(1-0.05/(2*family_size), df)
                    self.assertGreaterEqual(actual, expected)
                    self.assertLess(actual-expected, 0.003)
        self.assertIsNone(_familywise_t_critical(9, 4))
        self.assertIsNone(_familywise_t_critical(301, 4))
        self.assertIsNone(_familywise_t_critical(20, 41))

    def test_approved_synthetic_relationship_runs_through_full_engine(self):
        request = {
            "objective": "Synthetic cross-step tradeoff integration",
            "context": {"process_step": "SYN-ETCH-TO-METROLOGY"},
            "constraints_approved": True,
            "grain": "one paired synthetic unit",
            "sampling_unit": "synthetic unit",
            "timestamp_semantics": "UTC event timestamps",
            "factors": [{"name": "pressure", "role": "controllable", "unit": "kPa",
                         "bounds": [1, 3], "approved": True}],
            "metrics": [{"name": "yield", "unit": "%", "direction": "maximize"},
                        {"name": "defect", "unit": "count", "direction": "minimize"}],
            "primary_metric": "yield",
            "objectives": [{"metric": "yield", "direction": "maximize"},
                           {"metric": "defect", "direction": "minimize"}],
            "sources": [{"id": "SYN-UPSTREAM", "approved_semantic_version": "SYNTHETIC-1.0",
                         "grain": "synthetic upstream event", "source_hash": "a" * 64},
                        {"id": "SYN-DOWNSTREAM", "approved_semantic_version": "SYNTHETIC-1.0",
                         "grain": "synthetic downstream event", "source_hash": "b" * 64}],
            "multi_step": True,
            "linkage": self.data["linkage"],
            "observations": [],
        }
        for setting, avg_yield, avg_defect in ((1, 80, 5), (2, 85, 6), (3, 82, 4)):
            for unit in range(30):
                noise = ((unit % 5) - 2) * 0.04
                unit_id = f"SYN-UNIT-{setting}-{unit:02d}"
                request["observations"].append({
                    "id": f"SYN-PAIR-{setting}-{unit:02d}",
                    "unit_id": unit_id,
                    "factors": {"pressure": float(setting)},
                    "metrics": {"yield": avg_yield + noise, "defect": avg_defect - noise * 0.3},
                    "source_ids": ["SYN-UPSTREAM", "SYN-DOWNSTREAM"],
                    "upstream": {"unit_id": unit_id, "event_ts": "2026-01-01T00:00:00Z",
                                 "population_id": "SYN-COHORT-01"},
                    "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T03:00:00Z",
                                   "population_id": "SYN-COHORT-01"},
                })

        result = analyze(request)
        dossier = result["artifacts"][0]
        tradeoffs = dossier["D03_tradeoffs"]
        self.assertIn(result["status"], ("VALID", "PARTIAL"))
        self.assertEqual(tradeoffs["status"], "VALID")
        self.assertEqual(tradeoffs["relationship_id"], "SYN-REL-01")
        self.assertEqual(tradeoffs["compatible_paired_units"], 90)
        self.assertEqual(tradeoffs["pareto_observation_ids"], ["SYN-SETTING-2", "SYN-SETTING-3"])
        self.assertFalse(tradeoffs["causal_claim"])


if __name__ == "__main__":
    unittest.main()
