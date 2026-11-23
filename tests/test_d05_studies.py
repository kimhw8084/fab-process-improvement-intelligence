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
                    rows.append({"unit_id": f"SYN-{group}-{unit}", "group": group, "period": period, "quality": value})
        ledger = [{"unit_id": f"SYN-{group}-{unit}", "group": group}
                  for group in ("treatment", "control") for unit in range(30)]
        return {"authorized": True, "design": "difference_in_differences", "intervention_id": "SYN-CHANGE",
                "authorization_id": "SYN-AUTH", "metric": "quality", "assignment_ledger": ledger,
                "differential_trend_bound": 0.5, "differential_trend_bound_source": "SYN-BOUND-SOURCE",
                "differential_trend_bound_method": "SYN-BOUND-METHOD",
                "pretrend_equivalence_bound": 0.25, "pretrend_equivalence_bound_source": "SYN-PRE-SOURCE",
                "pretrend_equivalence_bound_method": "SYN-PRE-METHOD", "observations": rows}

    def test_did_uses_two_preperiods_and_quantitative_trend_sensitivity(self):
        result = _effectiveness({"effectiveness": self.did_study()})
        self.assertEqual(result["status"], "ESTIMATED")
        self.assertAlmostEqual(result["estimate"], 2.0)
        self.assertTrue(result["causal_claim"])
        self.assertEqual(result["pretrend_diagnostic"]["status"], "WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND_NOT_PROOF")
        self.assertEqual(result["sensitivity"]["effect_range_under_bound"], [1.5, 2.5])
        self.assertEqual(result["sensitivity"]["ci95_under_bound"], [1.5, 2.5])
        self.assertFalse(result["diagnostics"]["small_sample_warning"])

    def test_detected_parallel_trend_violation_withholds_causal_claim(self):
        result = _effectiveness({"effectiveness": self.did_study(pretrend_difference=2.0)})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")
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
        self.assertIn("source and method", result["sensitivity"]["reason"])

        study = self.did_study()
        study["differential_trend_bound"] = 3.0
        result = _effectiveness({"effectiveness": study})
        self.assertFalse(result["causal_claim"])
        self.assertFalse(result["diagnostics"]["effect_direction_supported_under_trend_bound"])

        study = self.did_study()
        study.pop("pretrend_equivalence_bound_source")
        result = _effectiveness({"effectiveness": study})
        self.assertEqual(result["pretrend_diagnostic"]["status"], "EQUIVALENCE_BOUND_NOT_DOCUMENTED")
        self.assertFalse(result["causal_claim"])

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


if __name__ == "__main__":
    unittest.main()
