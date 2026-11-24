"""Independent diagnostics, attrition bounds, and invalid-assumption checks for D05."""
import unittest

from products.p4.engine import _effectiveness


def randomized_study():
    rows = []
    for group, values in (("treatment", [11, 12, 13, 12]), ("control", [8, 9, 10, 9])):
        for index, value in enumerate(values):
            rows.append({"unit_id": f"SYN-{group}-{index}", "group": group, "quality": value,
                         "baseline_temp": index + (1 if group == "treatment" else 0)})
    return {"authorized": True, "design": "randomized", "randomized": True,
            "intervention_id": "SYN-INTERVENTION", "authorization_id": "SYN-AUTH",
            "randomization_evidence": "SYN-ALLOC", "metric": "quality",
            "assignment_ledger": [{"unit_id": row["unit_id"], "group": row["group"]} for row in rows],
            "baseline_covariates": ["baseline_temp"], "observations": rows}


class EffectivenessQualification(unittest.TestCase):
    def test_randomized_estimate_reports_attrition_baseline_balance_and_small_sample_warning(self):
        result = _effectiveness({"effectiveness": randomized_study()})
        self.assertEqual(result["status"], "ESTIMATED")
        self.assertEqual(result["estimate"], 3.0)
        self.assertEqual(result["attrition"]["treatment"]["missing_outcome"], 0)
        self.assertIn("standardized_mean_difference", result["baseline_balance"]["baseline_temp"])
        self.assertTrue(result["diagnostics"]["small_sample_warning"])
        self.assertTrue(result["causal_claim"])

    def test_missing_randomized_outcomes_require_bounds_and_return_worst_case_range(self):
        study = randomized_study()
        study["observations"][0]["quality"] = None
        no_bounds = _effectiveness({"effectiveness": study})
        self.assertEqual(no_bounds["status"], "INCONCLUSIVE")
        study["outcome_bounds"] = [0, 20]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "BOUNDED")
        self.assertFalse(result["causal_claim"])
        self.assertEqual(result["attrition"]["treatment"]["missing_outcome"], 1)
        self.assertLess(result["effect_identification_bounds"][0], result["effect_identification_bounds"][1])
        self.assertEqual(result["treatment_mean_bounds"], [9.25, 14.25])
        self.assertEqual(result["control_mean_bounds"], [9.0, 9.0])
        self.assertEqual(result["effect_identification_bounds"], [0.25, 5.25])

    def test_observed_outcomes_must_fall_inside_declared_attrition_bounds(self):
        study = randomized_study()
        study["observations"][0]["quality"] = None
        study["outcome_bounds"] = [9, 10]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertFalse(result["causal_claim"])
        self.assertIn("outside supplied outcome_bounds", result["reason"])

    def test_study_unit_ids_must_match_assignment_ledger_types_exactly(self):
        randomized = randomized_study()
        randomized["assignment_ledger"][0]["unit_id"] = "1"
        randomized["observations"][0]["unit_id"] = 1
        result = _effectiveness({"effectiveness": randomized})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertFalse(result["causal_claim"])

        did = self.did_study()
        original = did["assignment_ledger"][0]["unit_id"]
        did["assignment_ledger"][0]["unit_id"] = "1"
        for row in did["observations"]:
            if row["unit_id"] == original:
                row["unit_id"] = 1
        result = _effectiveness({"effectiveness": did})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertFalse(result["causal_claim"])

    def test_concurrent_intervention_mismatch_and_repeated_units_are_rejected(self):
        study = randomized_study()
        study["observations"][0]["concurrent_intervention_id"] = "SYN-COMED-NEW"
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        study = randomized_study()
        study["observations"][1]["unit_id"] = study["observations"][0]["unit_id"]
        self.assertEqual(_effectiveness({"effectiveness": study})["status"], "INCONCLUSIVE")
        study = randomized_study()
        study["observations"] = study["observations"][1:]
        study["outcome_bounds"] = [0, 20]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "BOUNDED")
        self.assertEqual(result["attrition"]["treatment"]["missing_outcome"], 1)

    @staticmethod
    def did_study(pretrend_difference=0.0, include_pretrend=True):
        rows = []
        for group in ("treatment", "control"):
            for unit in range(30):
                base = 100 + 0.02*unit
                pre2 = base
                pre = base + 0.1 + (pretrend_difference if group == "treatment" else 0)
                post = pre + (2.0 if group == "treatment" else 0.0)
                row_periods = {"pre": pre, "post": post}
                if include_pretrend:
                    row_periods["pre2"] = pre2
                for period, value in row_periods.items():
                    rows.append({"unit_id": f"SYN-{group}-{unit}", "group": group, "period": period, "quality": value,
                                 "concurrent_intervention_id": "none",
                                 "product_id": "SYN-PRODUCT-A" if unit < 15 else "SYN-PRODUCT-B"})
        ledger = [{"unit_id": f"SYN-{group}-{unit}", "group": group}
                  for group in ("treatment", "control") for unit in range(30)]
        return {"authorized": True, "design": "difference_in_differences", "intervention_id": "SYN-CHANGE",
                "authorization_id": "SYN-AUTH", "metric": "quality", "assignment_ledger": ledger,
                "metric_unit": "synthetic quality unit",
                "population_fields": ["product_id"],
                "differential_trend_bound": 0.5, "differential_trend_bound_source": "SYN-BOUND-SOURCE",
                "differential_trend_bound_method": "SYN-BOUND-METHOD", "differential_trend_bound_unit": "synthetic quality unit",
                "pretrend_equivalence_bound": 0.25, "pretrend_equivalence_bound_source": "SYN-PRE-SOURCE",
                "pretrend_equivalence_bound_method": "SYN-PRE-METHOD",
                "pretrend_equivalence_bound_unit": "synthetic quality unit", "observations": rows}

    def test_did_uses_two_preperiods_and_quantitative_trend_sensitivity(self):
        result = _effectiveness({"effectiveness": self.did_study()})
        self.assertEqual(result["status"], "ESTIMATED")
        self.assertAlmostEqual(result["estimate"], 2.0)
        self.assertFalse(result["causal_claim"])
        self.assertTrue(result["conditional_assumptions_passed"])
        self.assertFalse(result["conditional_interpretation_eligible"])
        self.assertEqual(result["conditional_interpretation_scope"], "PENDING_BOUND_SOURCE_QUALIFICATION")
        self.assertEqual(result["bound_source_qualification"], "NOT_ESTABLISHED_BY_AVAILABLE_ADAPTER")
        self.assertEqual(result["pretrend_diagnostic"]["status"], "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF")
        self.assertEqual(result["sensitivity"]["effect_range_under_bound"], [1.5, 2.5])
        self.assertEqual(result["sensitivity"]["ci95_under_bound"], [1.5, 2.5])
        self.assertEqual(result["sensitivity"]["point_estimate_tipping_point_abs_trend"], 2.0)
        self.assertEqual(result["sensitivity"]["ci95_tipping_point_abs_trend"], 2.0)
        self.assertTrue(result["sensitivity"]["robust_to_declared_bound"])
        self.assertEqual(result["sensitivity"]["bound_authentication"], "NOT_VERIFIABLE_BY_P4")
        self.assertFalse(result["diagnostics"]["small_sample_warning"])

    def test_detected_parallel_trend_violation_withholds_causal_claim(self):
        result = _effectiveness({"effectiveness": self.did_study(pretrend_difference=2.0)})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")
        self.assertFalse(result["causal_claim"])

    def test_three_preperiod_placebo_detects_curved_differential_trend_that_two_period_check_misses(self):
        study = self.did_study()
        third_period = []
        for row in study["observations"]:
            unit = int(row["unit_id"].rsplit("-", 1)[1])
            baseline = 100 + 0.02*unit
            if row["period"] == "pre2":
                row["quality"] = baseline + (1.0 if row["group"] == "treatment" else 0.0)
            elif row["period"] == "pre":
                row["quality"] = baseline + (1.1 if row["group"] == "treatment" else 0.1)
            elif row["period"] == "post":
                row["quality"] = baseline + (3.1 if row["group"] == "treatment" else 0.1)
            if row["period"] == "pre2":
                third_period.append({"unit_id": row["unit_id"], "group": row["group"],
                                     "period": "pre3", "quality": baseline})
        study["observations"].extend(third_period)
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_diagnostic"]["status"],
                         "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF")
        stability = result["pretrend_stability_placebo"]
        self.assertEqual(stability["status"], "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")
        self.assertAlmostEqual(stability["estimate"], -1.0)
        self.assertFalse(result["causal_claim"])

    def test_product_mix_shift_and_treatment_control_composition_mismatch_withhold_did_claim(self):
        study = self.did_study()
        for row in study["observations"]:
            if row["unit_id"] == "SYN-treatment-0" and row["period"] == "post":
                row["product_id"] = "SYN-PRODUCT-B"
        shifted = _effectiveness({"effectiveness": study})
        self.assertEqual(shifted["population_compatibility"]["status"], "WITHIN_UNIT_POPULATION_SHIFT")
        self.assertFalse(shifted["causal_claim"])

        study = self.did_study()
        for row in study["observations"]:
            row["product_id"] = "SYN-PRODUCT-A" if row["group"] == "treatment" else "SYN-PRODUCT-B"
        mismatched = _effectiveness({"effectiveness": study})
        self.assertEqual(mismatched["population_compatibility"]["status"],
                         "TREATMENT_CONTROL_COMPOSITION_MISMATCH")
        self.assertFalse(mismatched["causal_claim"])

    def test_did_without_declared_population_fields_remains_descriptive_only(self):
        study = self.did_study()
        study.pop("population_fields")
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["population_compatibility"]["status"], "NOT_PROVIDED")
        self.assertFalse(result["causal_claim"])

    def test_regression_to_mean_after_extreme_treatment_preperiod_is_falsified(self):
        study = self.did_study()
        for row in study["observations"]:
            if row["group"] == "treatment":
                row["quality"] = {"pre2": 100.0, "pre": 105.0, "post": 100.0}[row["period"]]
            else:
                row["quality"] = 100.0
        result = _effectiveness({"effectiveness": study})
        self.assertLess(result["estimate"], 0)
        self.assertEqual(result["pretrend_diagnostic"]["status"], "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")
        self.assertFalse(result["causal_claim"])

    def test_partial_third_preperiod_coverage_withholds_causal_interpretation(self):
        study = self.did_study()
        for row in list(study["observations"]):
            if row["period"] == "pre" and row["unit_id"] == "SYN-treatment-0":
                study["observations"].append({"unit_id": row["unit_id"], "group": row["group"],
                                              "period": "pre3", "quality": 100})
                break
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_stability_placebo"]["status"], "INCOMPLETE_COVERAGE")
        self.assertFalse(result["causal_claim"])

    def test_one_preperiod_or_incomplete_panel_is_descriptive_only_or_refused(self):
        one_period = _effectiveness({"effectiveness": self.did_study(include_pretrend=False)})
        self.assertEqual(one_period["status"], "ESTIMATED")
        self.assertFalse(one_period["causal_claim"])
        incomplete = self.did_study()
        incomplete["observations"] = [row for row in incomplete["observations"]
                                      if not (row["unit_id"] == "SYN-treatment-0" and row["period"] == "post")]
        result = _effectiveness({"effectiveness": incomplete})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertFalse(result["causal_claim"])

    def test_did_refuses_unledgered_units_and_withholds_for_incomplete_pretrend_coverage(self):
        study = self.did_study()
        study.pop("assignment_ledger")
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("assignment ledger", result["reason"])

        study = self.did_study()
        study["observations"] = [row for row in study["observations"]
                                 if not (row["unit_id"] == "SYN-treatment-0" and row["period"] == "pre2")]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "INCOMPLETE_COVERAGE")
        self.assertFalse(result["causal_claim"])

        study = self.did_study()
        study["observations"] = [row for row in study["observations"]
                                 if row["unit_id"] != "SYN-treatment-0"]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["attrition"]["treatment"]["assigned"], 30)
        self.assertEqual(result["attrition"]["treatment"]["complete_pre_post"], 29)

    def test_did_requires_documented_bounds_and_directional_robustness(self):
        study = self.did_study()
        del study["differential_trend_bound_source"]
        result = _effectiveness({"effectiveness": study})
        self.assertFalse(result["causal_claim"])
        self.assertIn("source, method", result["sensitivity"]["reason"])

        study = self.did_study()
        study["differential_trend_bound"] = 3.0
        result = _effectiveness({"effectiveness": study})
        self.assertFalse(result["conditional_interpretation_eligible"])
        self.assertFalse(result["diagnostics"]["effect_direction_supported_under_trend_bound"])

    def test_did_requires_bound_units_to_match_outcome_unit_exactly(self):
        study = self.did_study()
        study["differential_trend_bound_unit"] = "percent"
        result = _effectiveness({"effectiveness": study})
        self.assertFalse(result["causal_claim"])
        self.assertFalse(result["conditional_interpretation_eligible"])
        self.assertIn("unit exactly matching", result["sensitivity"]["reason"])

        study = self.did_study()
        study["pretrend_equivalence_bound_unit"] = "percent"
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "EQUIVALENCE_BOUND_NOT_DOCUMENTED")
        self.assertFalse(result["conditional_interpretation_eligible"])

    def test_hidden_postperiod_confounder_can_defeat_a_caller_underbound_but_never_emits_did_claim(self):
        study = self.did_study()
        # Independent oracle: true intervention effect is -0.5, but a treatment-only
        # unobserved post-period trend of +2.0 makes the observed difference +1.5.
        for row in study["observations"]:
            if row["group"] == "treatment" and row["period"] == "post":
                row["quality"] = row["quality"] - 0.5
        study["differential_trend_bound"] = 0.25
        result = _effectiveness({"effectiveness": study})
        self.assertAlmostEqual(result["estimate"], 1.5)
        self.assertTrue(result["conditional_assumptions_passed"])
        self.assertFalse(result["conditional_interpretation_eligible"])
        self.assertFalse(result["causal_claim"])
        self.assertEqual(result["sensitivity"]["ci95_under_bound"], [1.25, 1.75])
        self.assertEqual(result["sensitivity"]["bound_authentication"], "NOT_VERIFIABLE_BY_P4")
        self.assertIn("neither marks a conditional interpretation eligible nor emits an observational DiD causal claim",
                      result["causal_claim_limitation"])

        study = self.did_study()
        study.pop("pretrend_equivalence_bound_source")
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "EQUIVALENCE_BOUND_NOT_DOCUMENTED")
        self.assertFalse(result["causal_claim"])

    def test_did_negative_control_equivalence_is_a_falsification_gate_not_proof(self):
        study = self.did_study()
        for row in study["observations"]:
            unit = int(row["unit_id"].rsplit("-", 1)[1])
            common_trend = {"pre2": 0.0, "pre": 0.2, "post": 0.4}[row["period"]]
            row["control_metric"] = 50.0 + unit*0.01 + common_trend
        study["negative_control_outcome"] = {"metric": "control_metric", "equivalence_bound": 0.1,
            "metric_unit": "synthetic control unit", "bound_unit": "synthetic control unit",
            "bound_source": "SYN-NC-SOURCE", "bound_method": "SYN-PRESPECIFIED-EQUIVALENCE"}
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["negative_control_diagnostic"]["status"], "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF")
        self.assertTrue(result["conditional_assumptions_passed"])
        self.assertFalse(result["conditional_interpretation_eligible"])
        self.assertFalse(result["causal_claim"])
        self.assertIn("cannot establish absence of unmeasured confounding",
                      result["negative_control_diagnostic"]["qualification"])
        self.assertIn("placebo diagnostic", result["placebo_pretrend"]["interpretation"])

        for row in study["observations"]:
            if row["group"] == "treatment" and row["period"] == "post":
                row["control_metric"] += 1.0
        contaminated = _effectiveness({"effectiveness": study})
        self.assertEqual(contaminated["negative_control_diagnostic"]["status"],
                         "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")
        self.assertFalse(contaminated["causal_claim"])

    def test_did_malformed_or_incomplete_negative_control_withholds_causal_claim(self):
        study = self.did_study()
        study["negative_control_outcome"] = {"metric": "control_metric", "equivalence_bound": 0.1}
        malformed = _effectiveness({"effectiveness": study})
        self.assertEqual(malformed["status"], "INCONCLUSIVE")
        self.assertFalse(malformed["causal_claim"])

        study = self.did_study()
        for row in study["observations"]:
            row["control_metric"] = 50.0
        study["observations"][0]["control_metric"] = None
        study["negative_control_outcome"] = {"metric": "control_metric", "equivalence_bound": 0.1,
            "metric_unit": "synthetic control unit", "bound_unit": "synthetic control unit",
            "bound_source": "SYN-NC-SOURCE", "bound_method": "SYN-PRESPECIFIED-EQUIVALENCE"}
        incomplete = _effectiveness({"effectiveness": study})
        self.assertEqual(incomplete["negative_control_diagnostic"]["status"], "INCOMPLETE_COVERAGE")
        self.assertFalse(incomplete["causal_claim"])

    def test_did_withholds_conditional_claim_for_small_samples_and_concurrent_changes(self):
        study = self.did_study()
        keep = {f"SYN-{group}-{unit}" for group in ("treatment", "control") for unit in range(5)}
        study["assignment_ledger"] = [item for item in study["assignment_ledger"] if item["unit_id"] in keep]
        study["observations"] = [row for row in study["observations"] if row["unit_id"] in keep]
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["status"], "ESTIMATED")
        self.assertTrue(result["diagnostics"]["small_sample_warning"])
        self.assertFalse(result["causal_claim"])

        study = self.did_study()
        study["observations"][0]["concurrent_intervention_id"] = "SYN-UNPLANNED"
        result = _effectiveness({"effectiveness": study})
        self.assertTrue(result["diagnostics"]["differential_concurrent_intervention"])
        self.assertFalse(result["causal_claim"])

    def test_did_detects_differential_concurrent_intervention_prevalence_with_same_label_set(self):
        study = self.did_study()
        for row in study["observations"]:
            row["concurrent_intervention_id"] = "none"
            if row["period"] != "post":
                continue
            unit = int(row["unit_id"].rsplit("-", 1)[1])
            if row["group"] == "treatment":
                row["quality"] -= 2.0  # zero true process effect
                if unit < 15:
                    row["concurrent_intervention_id"] = "SYN-COMED"
                    row["quality"] += 3.0
            elif unit == 0:
                row["concurrent_intervention_id"] = "SYN-COMED"
                row["quality"] += 3.0

        result = _effectiveness({"effectiveness": study})
        self.assertAlmostEqual(result["estimate"], 1.4)  # entirely induced by 50% vs 3.3% co-intervention prevalence
        self.assertEqual(result["diagnostics"]["concurrent_intervention_ids"]["treatment"],
                         result["diagnostics"]["concurrent_intervention_ids"]["control"])
        self.assertTrue(result["diagnostics"]["differential_concurrent_intervention"])
        self.assertEqual(result["concurrent_intervention_diagnostic"]["status"], "DIFFERENTIAL_OR_INCOMPLETE_DECLARED_MIX")
        self.assertIn("post", result["concurrent_intervention_diagnostic"]["periods_with_different_group_proportions"])
        self.assertTrue(result["concurrent_intervention_diagnostic"]["transition_proportions_differ"])
        self.assertFalse(result["conditional_assumptions_passed"])
        self.assertFalse(result["causal_claim"])

    def test_did_missing_concurrent_intervention_labels_are_not_treated_as_none(self):
        study = self.did_study()
        for row in study["observations"]:
            del row["concurrent_intervention_id"]

        result = _effectiveness({"effectiveness": study})
        self.assertFalse(result["conditional_assumptions_passed"])
        self.assertEqual(result["concurrent_intervention_diagnostic"]["status"],
                         "INCOMPLETE_DECLARED_INTERVENTION_HISTORY")
        self.assertEqual(result["concurrent_intervention_diagnostic"]["periods_with_unreported_intervention_ids"]["treatment"],
                         {"pre2": 30, "pre": 30, "post": 30})

    def test_did_detects_arm_specific_intervention_transitions_when_period_margins_match(self):
        study = self.did_study()
        for row in study["observations"]:
            unit = int(row["unit_id"].rsplit("-", 1)[1])
            initial = "SYN-DRUG-A" if unit < 15 else "SYN-DRUG-B"
            row["concurrent_intervention_id"] = (
                "SYN-DRUG-B" if row["group"] == "treatment" and row["period"] == "post" and unit < 15
                else "SYN-DRUG-A" if row["group"] == "treatment" and row["period"] == "post"
                else initial)

        result = _effectiveness({"effectiveness": study})
        diagnostic = result["concurrent_intervention_diagnostic"]
        self.assertEqual(diagnostic["periods_with_different_group_proportions"], [])
        self.assertIn("pre -> post", diagnostic["transitions_with_different_group_proportions"])
        self.assertFalse(result["conditional_assumptions_passed"])

    def test_did_checks_concurrent_intervention_mix_in_each_observed_preperiod(self):
        study = self.did_study()
        for row in study["observations"]:
            if row["period"] == "pre2":
                row["concurrent_intervention_id"] = (
                    "SYN-DRUG-A" if row["group"] == "treatment" or int(row["unit_id"].rsplit("-", 1)[1]) < 15
                    else "SYN-DRUG-B")

        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["concurrent_intervention_diagnostic"]["periods_with_different_group_proportions"], ["pre2"])
        self.assertFalse(result["conditional_assumptions_passed"])


if __name__ == "__main__":
    unittest.main()
