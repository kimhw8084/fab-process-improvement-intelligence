"""Independent fail-closed and numeric qualification for cross-step tradeoffs."""
import copy
import json
from math import log, sqrt
from pathlib import Path
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
            "familywise_t_precommit": {
                "precommit_reference": "SYN-D03-PRECOMMIT-01",
                "candidate_setting_ids": ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3"],
                "objectives": [{"metric": "yield", "direction": "maximize"},
                               {"metric": "defect", "direction": "minimize"}]},
            "sources": [{"id": "SYN-UPSTREAM"}, {"id": "SYN-DOWNSTREAM"}],
            "linkage": {
                "approved": True, "relationship_id": "SYN-REL-01", "contract_version": "1.1.0",
                "approval_reference": "SYN-APPROVAL-01", "maximum_lag_seconds": 86400,
                "unit_field": "unit_id", "decision_factors": ["pressure"], "minimum_independent_units": 30,
                "upstream": {"source_id": "SYN-UPSTREAM", "key_field": "upstream.unit_id",
                              "event_time_field": "upstream.event_ts", "population_field": "upstream.population_id",
                              "population_id": "SYN-COHORT-01", "metric_field": "metrics.yield", "metric": "yield"},
                "downstream": {"source_id": "SYN-DOWNSTREAM", "key_field": "downstream.unit_id",
                                "event_time_field": "downstream.event_ts", "population_field": "downstream.population_id",
                                "population_id": "SYN-COHORT-01", "metric_field": "metrics.defect", "metric": "defect"},
                "population_composition_fields": [{
                    "name": "product_family",
                    "upstream_field": "upstream.product_family",
                    "downstream_field": "downstream.product_family",
                }]}
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
                    "upstream": {"unit_id": unit_id, "event_ts": "2026-01-01T00:00:00Z", "population_id": "SYN-COHORT-01",
                                 "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"},
                    "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T03:00:00Z", "population_id": "SYN-COHORT-01",
                                   "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"}})

    def test_paired_population_metrics_and_uncertainty_produce_hand_checked_front(self):
        result = cross_step_tradeoffs(self.rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["population_composition_audit"]["status"],
                         "MATCHED_DECLARED_STRATUM_DISTRIBUTIONS")
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
        self.assertEqual(result["familywise_mean_envelope"]["precommit_source_qualification_status"],
                         "CALLER_SUPPLIED_NOT_AUTHENTICATED")
        self.assertIn({"dominant_setting_id": "SYN-SETTING-3", "dominated_setting_id": "SYN-SETTING-1",
                       "scope": "Bonferroni_familywise_simultaneous_mean_rectangles"},
                      result["familywise_interval_separated_dominance"])
        self.assertIn("SYN-SETTING-2", result["familywise_nondominated_setting_ids"])

    def test_cross_step_pareto_is_withheld_when_product_mix_changes_across_settings(self):
        rows = copy.deepcopy(self.rows)
        data = copy.deepcopy(self.data)
        data["linkage"]["population_composition_fields"] = [{
            "name": "product_family",
            "upstream_field": "upstream.product_family",
            "downstream_field": "downstream.product_family",
        }]
        counts_by_setting = {1: 30, 2: 15, 3: 0}
        unit_index_by_setting = {1: 0, 2: 0, 3: 0}
        for row in rows:
            setting = int(row["factors"]["pressure"])
            unit_index = unit_index_by_setting[setting]
            unit_index_by_setting[setting] += 1
            family = "FAMILY-A" if unit_index < counts_by_setting[setting] else "FAMILY-B"
            row["upstream"]["product_family"] = family
            row["downstream"]["product_family"] = family
            row["metrics"]["yield"] = 90.0 if family == "FAMILY-A" else 70.0
            row["metrics"]["defect"] = 1.0 if family == "FAMILY-A" else 10.0

        result = cross_step_tradeoffs(rows, self.metric_defs, data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["population_composition_audit"]["status"],
                         "MISMATCHED_DECLARED_STRATUM_DISTRIBUTIONS")
        self.assertEqual(result["mean_pareto_setting_ids"], [])
        self.assertEqual(result["pareto_observation_ids"], [])
        self.assertEqual(result["pareto_values"], [])
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_POPULATION_COMPOSITION_MISMATCH")

    def test_sparse_cross_step_setting_makes_front_explicitly_incomplete(self):
        rows = copy.deepcopy(self.rows)
        for unit in range(20):
            unit_id = f"SYN-UNIT-4-{unit:02d}"
            rows.append({"id": f"SYN-PAIR-4-{unit:02d}", "unit_id": unit_id,
                         "factors": {"pressure": 4.0},
                         "metrics": {"yield": 90.0 + unit / 100, "defect": 2.0},
                         "source_ids": ["SYN-UPSTREAM", "SYN-DOWNSTREAM"],
                         "upstream": {"unit_id": unit_id, "event_ts": "2026-01-01T00:00:00Z",
                                      "population_id": "SYN-COHORT-01",
                                      "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"},
                         "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T03:00:00Z",
                                        "population_id": "SYN-COHORT-01",
                                        "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"}})
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertNotIn("SYN-SETTING-4", result["pareto_observation_ids"])
        self.assertNotIn("SYN-SETTING-4", [item["id"] for item in result["candidate_settings"]])
        self.assertEqual(result["unassessed_settings"], [{
            "id": "SYN-SETTING-4", "factors": {"pressure": 4.0},
            "eligible_independent_units": 20, "required_independent_units": 30,
            "reason": "below independent-unit minimum"}])
        self.assertIn("Pareto front is incomplete", result["selection_warning"])
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_INSUFFICIENT_UNITS_FOR_SOME_SETTINGS")

    def test_sparse_observed_setting_makes_front_explicitly_incomplete(self):
        rows = []
        for pressure, count in ((1, 3), (2, 3), (3, 2)):
            for unit in range(count):
                rows.append({"id": f"OBS-{pressure}-{unit}", "unit_id": f"UNIT-{pressure}-{unit}",
                             "factors": {"pressure": pressure},
                             "metrics": {"yield": 80 + pressure + unit / 10,
                                         "defect": 5 - pressure + unit / 10}})
        result = observed_tradeoffs(
            rows, self.metric_defs, {"pressure": {"role": "controllable"}},
            {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3},
            self.data["objectives"])
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertNotIn("SYN-SETTING-3", result["pareto_setting_ids"])
        self.assertEqual(result["unassessed_settings"], [{
            "id": "SYN-SETTING-3", "factors": {"pressure": 3},
            "eligible_independent_units": 2, "required_independent_units": 3,
            "reason": "below independent-unit minimum"}])
        self.assertIn("Pareto front is incomplete", result["selection_warning"])
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_INSUFFICIENT_UNITS_FOR_SOME_SETTINGS")

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

    def test_row_lineage_requires_exact_source_id_array_membership(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["source_ids"] = "SYN-UPSTREAM-SYN-DOWNSTREAM"
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)
        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["downstream_claim"], "withheld")
        self.assertIn("row-level lineage", result["reason"])

    def test_malformed_relationship_families_and_empty_rows_fail_closed(self):
        empty = cross_step_tradeoffs([], self.metric_defs, self.data)
        self.assertEqual(empty["status"], "LIMITED_SCOPE")
        self.assertIn("no observations", empty["reason"])

        duplicate_objective = copy.deepcopy(self.data)
        duplicate_objective["objectives"].append(copy.deepcopy(duplicate_objective["objectives"][0]))
        duplicate = cross_step_tradeoffs(self.rows, self.metric_defs, duplicate_objective)
        self.assertEqual(duplicate["status"], "LIMITED_SCOPE")
        self.assertEqual(duplicate["downstream_claim"], "withheld")

        wrong_direction = copy.deepcopy(self.data)
        wrong_direction["objectives"][0]["direction"] = "minimize"
        conflict = cross_step_tradeoffs(self.rows, self.metric_defs, wrong_direction)
        self.assertEqual(conflict["status"], "LIMITED_SCOPE")
        self.assertIn("direction conflicts", conflict["reason"])

        malformed_sources = copy.deepcopy(self.data)
        malformed_sources["sources"] = ["SYN-UPSTREAM", "SYN-DOWNSTREAM"]
        invalid = cross_step_tradeoffs(self.rows, self.metric_defs, malformed_sources)
        self.assertEqual(invalid["status"], "LIMITED_SCOPE")
        self.assertEqual(invalid["downstream_claim"], "withheld")

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

    def test_engine_refuses_a_missing_objective_without_complete_case_pareto(self):
        source = Path(__file__).resolve().parents[1] / "fixtures" / "full_workflow_demo.json"
        investigation = json.loads(source.read_text(encoding="utf-8"))
        investigation["observations"][0]["metrics"].pop("yield_index")
        result = analyze(investigation)
        self.assertEqual(result["status"], "REFUSED")
        self.assertTrue(any("missing or non-finite metric values" in item
                            for item in result.get("limitations", [])))
        self.assertEqual(result.get("claims", []), [])

    def test_engine_refuses_conflicting_metric_constraints_before_pareto(self):
        source = Path(__file__).resolve().parents[1] / "fixtures" / "full_workflow_demo.json"
        investigation = json.loads(source.read_text(encoding="utf-8"))
        investigation["metrics"][0]["min"] = 20
        investigation["metrics"][0]["max"] = 10
        result = analyze(investigation)
        self.assertEqual(result["status"], "REFUSED")
        self.assertTrue(any("minimum exceeds maximum" in item
                            for item in result.get("limitations", [])))
        self.assertEqual(result.get("claims", []), [])

    def test_constant_observed_metrics_do_not_create_zero_width_population_intervals(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row["metrics"] = {"yield": 80.0, "defect": 5.0}
            row["upstream"]["event_ts"] = "2026-01-01T00:00:00Z"
            row["downstream"]["event_ts"] = "2026-01-01T03:00:00Z"
        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertFalse(result["uncertainty_available"])
        self.assertEqual(result["uncertainty_limitations"], [
            "zero observed variance leaves the marginal Student-t interval unestimable; it does not establish zero population uncertainty",
        ])
        self.assertTrue(all(candidate["uncertainty"][metric]["marginal_ci95"] is None
                            and candidate["uncertainty"][metric]["marginal_ci95_status"] == "NOT_ESTIMABLE_ZERO_OBSERVED_VARIANCE"
                            for candidate in result["candidate_settings"] for metric in ("yield", "defect")))
        self.assertTrue(all(item["marginal_intervals_overlap"]["yield"] is None
                            and item["marginal_interval_status"]["yield"] == "NOT_ASSESSED_ZERO_OBSERVED_VARIANCE"
                            for item in result["uncertainty_comparisons"]))

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
                                     {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3,
                                      "familywise_t_precommit": self.data["familywise_t_precommit"]},
                                     objectives)
        self.assertEqual(matched["familywise_mean_envelope"]["status"],
                         "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE")
        self.assertEqual(matched["familywise_mean_envelope"]["population_compatibility"],
                         "IDENTICAL_INDEPENDENT_UNIT_SET_AT_EVERY_INCLUDED_SETTING")

    def test_observed_t_familywise_withholds_uncommitted_or_mismatched_families(self):
        objectives = self.data["objectives"]
        base = {"tradeoff_unit_field": "unit_id", "tradeoff_min_independent_units": 3}
        matched_rows = copy.deepcopy(self.rows)
        for row in matched_rows:
            row["unit_id"] = "SYN-UNIT-" + row["unit_id"].rsplit("-", 1)[1]
        result = observed_tradeoffs(matched_rows, self.metric_defs,
                                    {"pressure": {"role": "controllable"}}, base, objectives)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "NOT_AVAILABLE_PRECOMMIT_NOT_DECLARED")

        omitted_setting = copy.deepcopy(self.data["familywise_t_precommit"])
        omitted_setting["candidate_setting_ids"].pop()
        result = observed_tradeoffs(matched_rows, self.metric_defs,
                                    {"pressure": {"role": "controllable"}},
                                    {**base, "familywise_t_precommit": omitted_setting}, objectives)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "PRECOMMITTED_SETTING_FAMILY_MISMATCH")

        wrong_objective = copy.deepcopy(self.data["familywise_t_precommit"])
        wrong_objective["objectives"][0]["direction"] = "minimize"
        result = observed_tradeoffs(matched_rows, self.metric_defs,
                                    {"pressure": {"role": "controllable"}},
                                    {**base, "familywise_t_precommit": wrong_objective}, objectives)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "PRECOMMITTED_OBJECTIVE_FAMILY_MISMATCH")

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

    def test_bounded_familywise_envelope_uses_exact_prespecified_family_and_units(self):
        data = copy.deepcopy(self.data)
        data["familywise_mean_bounds"] = {
            "precommit_reference": "SYN-PLAN-01",
            "bounds_source_reference": "SYN-RANGE-01",
            "candidate_setting_ids": ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3"],
            "metric_units": {"yield": "%", "defect": "count"},
            "metric_bounds": {"yield": [60, 100], "defect": [0, 10]},
        }
        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)
        envelope = result["familywise_mean_envelope"]
        self.assertEqual(envelope["status"], "AVAILABLE_BOUNDED_HOEFFDING_ENVELOPE")
        self.assertEqual(envelope["source_qualification_status"], "CALLER_SUPPLIED_NOT_AUTHENTICATED")
        self.assertEqual(envelope["precommitted_candidate_setting_ids"],
                         ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3"])
        self.assertEqual(envelope["hard_bounds_units"], {"defect": "count", "yield": "%"})
        setting = result["candidate_settings"][0]
        expected = 40 * sqrt(log(2 * 6 / 0.05) / (2 * 30))
        self.assertAlmostEqual(setting["uncertainty"]["yield"]["familywise_half_width"], expected)
        self.assertEqual(setting["uncertainty"]["yield"]["familywise_ci95_method"],
                         "two-sided Hoeffding bound with Bonferroni allocation")

    def test_bounded_envelope_refuses_a_different_or_incomplete_candidate_family(self):
        data = copy.deepcopy(self.data)
        data["familywise_mean_bounds"] = {
            "precommit_reference": "SYN-PLAN-01",
            "bounds_source_reference": "SYN-RANGE-01",
            "candidate_setting_ids": ["SYN-SETTING-1", "SYN-SETTING-2"],
            "metric_units": {"yield": "%", "defect": "count"},
            "metric_bounds": {"yield": [60, 100], "defect": [0, 10]},
        }
        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)
        self.assertEqual(result["familywise_mean_envelope"]["status"],
                         "PRECOMMITTED_SETTING_FAMILY_MISMATCH")
        self.assertTrue(all(candidate["uncertainty"]["yield"]["familywise_ci95"] is None
                            for candidate in result["candidate_settings"]))

    def test_bounded_envelope_refuses_bad_bounds_units_and_observed_outliers_without_fallback(self):
        contract = {
            "precommit_reference": "SYN-PLAN-01",
            "bounds_source_reference": "SYN-RANGE-01",
            "candidate_setting_ids": ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3"],
            "metric_units": {"yield": "%", "defect": "count"},
            "metric_bounds": {"yield": [60, 100], "defect": [0, 10]},
        }
        for mutate, expected in (
            (lambda c: c["metric_bounds"].pop("defect"), "INVALID_BOUNDED_MEAN_METRIC_FAMILY"),
            (lambda c: c["metric_units"].update({"yield": "fraction"}), "INVALID_BOUNDED_MEAN_METRIC_UNITS"),
            (lambda c: c["metric_bounds"].update({"yield": [80, 84]}),
             "OBSERVED_UNIT_VALUE_OUTSIDE_SUPPLIED_HARD_BOUNDS"),
        ):
            with self.subTest(expected=expected):
                data = copy.deepcopy(self.data)
                data["familywise_mean_bounds"] = copy.deepcopy(contract)
                mutate(data["familywise_mean_bounds"])
                result = cross_step_tradeoffs(self.rows, self.metric_defs, data)
                self.assertEqual(result["familywise_mean_envelope"]["status"], expected)
                self.assertTrue(all(candidate["uncertainty"]["yield"]["familywise_ci95"] is None
                                    for candidate in result["candidate_settings"]))

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
            "familywise_mean_bounds": {
                "precommit_reference": "SYN-ENGINE-PLAN-01",
                "bounds_source_reference": "SYN-ENGINE-RANGE-01",
                "candidate_setting_ids": ["SYN-SETTING-1", "SYN-SETTING-2", "SYN-SETTING-3"],
                "metric_units": {"yield": "%", "defect": "count"},
                "metric_bounds": {"yield": [0, 100], "defect": [0, 10]},
            },
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
                                 "population_id": "SYN-COHORT-01",
                                 "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"},
                    "downstream": {"unit_id": unit_id, "event_ts": "2026-01-01T03:00:00Z",
                                   "population_id": "SYN-COHORT-01",
                                   "product_family": "FAMILY-A" if unit % 2 == 0 else "FAMILY-B"},
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
        self.assertEqual(tradeoffs["familywise_mean_envelope"]["status"],
                         "AVAILABLE_BOUNDED_HOEFFDING_ENVELOPE")
        self.assertEqual(tradeoffs["familywise_mean_envelope"]["hard_bounds_units"],
                         {"defect": "count", "yield": "%"})

    def test_cross_step_pareto_is_withheld_without_approved_composition_fields(self):
        data = copy.deepcopy(self.data)
        data["linkage"].pop("population_composition_fields")
        data["linkage"]["contract_version"] = "1.0.0"

        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["population_composition_audit"]["status"],
                         "NOT_ASSESSED_NO_DECLARED_COMPOSITION_FIELDS")
        self.assertEqual(result["mean_pareto_setting_ids"], [])
        self.assertEqual(result["pareto_values"], [])

    def test_v1_relationship_cannot_silently_carry_v1_1_composition_fields(self):
        data = copy.deepcopy(self.data)
        data["linkage"]["contract_version"] = "1.0.0"

        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertIn("require relationship contract v1.1.0", result["reason"])
        self.assertEqual(result["pareto_observation_ids"], [])

    def test_unhashable_relationship_version_fails_closed(self):
        data = copy.deepcopy(self.data)
        data["linkage"]["contract_version"] = ["1.1.0"]

        result = cross_step_tradeoffs(self.rows, self.metric_defs, data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["pareto_observation_ids"], [])

    def test_cross_step_refuses_disagreeing_source_stratum_values(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["downstream"]["product_family"] = "FAMILY-OTHER"

        result = cross_step_tradeoffs(rows, self.metric_defs, self.data)

        self.assertEqual(result["status"], "LIMITED_SCOPE")
        self.assertEqual(result["population_composition_audit"]["status"],
                         "UPSTREAM_DOWNSTREAM_COMPOSITION_MISMATCH")
        self.assertEqual(result["pareto_observation_ids"], [])


if __name__ == "__main__":
    unittest.main()
