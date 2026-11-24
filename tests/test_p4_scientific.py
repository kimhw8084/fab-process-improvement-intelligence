"""Independent and adversarial P4 challenge cases with fixed arithmetic oracles."""
import copy
import json
import random
import unittest
from pathlib import Path

from fabintel.contracts import ContractError, validate_envelope
from fabintel.project import analyze
from fabintel.qualification import inspect_capability_report

ROOT = Path(__file__).resolve().parent.parent


def dossier(result):
    return result["artifacts"][0]


class P4IndependentChallenges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = json.loads((ROOT / "fixtures" / "case_positive.json").read_text())
        cls.unsafe = json.loads((ROOT / "fixtures" / "case_negative.json").read_text())
        cls.full = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text())
        cls.oracle = json.loads((ROOT / "fixtures" / "p4_independent_oracles.json").read_text())

    def test_p4_01_fixed_slope_oracle(self):
        result = analyze(self.legacy)
        actual = dossier(result)["D01_sensitivity"]["terms"]["factor"]["estimate"]
        self.assertAlmostEqual(actual, self.oracle["P4-01"]["expected"], places=12)

    def test_declared_repeated_sampling_units_override_row_independent_uncertainty(self):
        reference = dossier(analyze(self.full))["D01_sensitivity"]
        self.assertEqual(reference["formula_sensitivity"]["status"], "COMPLETED_DIAGNOSTIC")
        self.assertEqual(reference["formula_sensitivity"]["model_selection"].split(";")[0], "none")
        request = copy.deepcopy(self.full)
        request["model"]["covariance"] = "HC3"
        request["model"].pop("cluster_field", None)
        adjusted = dossier(analyze(request))["D01_sensitivity"]
        self.assertEqual(adjusted["status"], "VALID")
        self.assertEqual(adjusted["inference"]["covariance"], "cluster")
        self.assertEqual(adjusted["inference"]["independent_cluster_field"], "lot_id")
        self.assertTrue(adjusted["inference"]["covariance_auto_selected_for_repeated_units"])
        self.assertAlmostEqual(adjusted["terms"]["pressure"]["standard_error"],
                               reference["terms"]["pressure"]["standard_error"], places=10)

        missing = copy.deepcopy(request)
        missing["observations"][0].pop("lot_id")
        withheld = analyze(missing)
        self.assertEqual(withheld["status"], "REFUSED")
        self.assertEqual(withheld["claims"], [])
        self.assertTrue(any("independent-unit field is missing" in item
                            or "relationship field is missing: lot_id" in item
                            for item in withheld["limitations"]))

    def test_duplicate_adjustment_sensitivity_fields_refuse_the_investigation(self):
        request = copy.deepcopy(self.full)
        request["model"]["adjustment_sensitivity_fields"] = ["product", "product"]
        result = analyze(request)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["claims"], [])
        self.assertIn("unique nonempty row field paths", result["limitations"][0])

    def test_declared_adjustment_sensitivity_runs_through_the_d01_dossier(self):
        request = copy.deepcopy(self.full)
        for index, observation in enumerate(request["observations"]):
            observation["product"] = "A" if index % 2 else "B"
        request["model"]["adjustment_sensitivity_fields"] = ["product", "chamber"]
        report = dossier(analyze(request))["D01_sensitivity"]["formula_sensitivity"]
        self.assertEqual(report["adjustment_sensitivity"]["requested_fields"], ["product", "chamber"])
        self.assertEqual(report["adjustment_sensitivity"]["already_in_base_formula"], ["chamber"])
        adjusted = next(item for item in report["variants"]
                        if item["formula"] == "adjustment_field:product")
        self.assertEqual(adjusted["status"], "VALID")
        self.assertEqual(adjusted["fixed_effect_fields"], ["chamber", "product"])

    def test_cluster_level_binary_exposure_withholds_sparse_arm_uncertainty_in_dossier(self):
        request = copy.deepcopy(self.full)
        request["model"]["factor_fields"] = ["pressure"]
        request["model"]["interactions"] = False
        request["model"]["quadratic"] = False
        for observation in request["observations"]:
            lot_number = int(observation["lot_id"].rsplit("-", 1)[1])
            observation["factors"]["pressure"] = 1.0 if lot_number <= 3 else 0.5
        result = analyze(request)
        report = dossier(result)["D01_sensitivity"]
        self.assertEqual(report["status"], "INCONCLUSIVE")
        self.assertEqual(report["inference"]["cluster_level_factor_support"][0]["cluster_count_by_level"], [3, 97])
        self.assertIsNotNone(report["terms"]["pressure"]["estimate"])
        self.assertIsNone(report["terms"]["pressure"]["ci95"])
        self.assertFalse(any(claim["method"] == "robust_linear_model" for claim in result["claims"]))

    def test_split_cluster_refusal_does_not_become_a_rank_claim(self):
        request = copy.deepcopy(self.full)
        request["model"]["covariance"] = "cluster"
        request["model"]["cluster_field"] = "id"
        result = analyze(request)
        report = dossier(result)["D01_sensitivity"]
        self.assertEqual(report["status"], "INCONCLUSIVE")
        self.assertEqual(report["inference"]["cluster_nesting"]["status"],
                         "INDEPENDENT_UNIT_SPLIT_ACROSS_CLUSTERS")
        self.assertFalse(any(claim["method"] in ("robust_linear_model", "qr_rank_diagnostic")
                             for claim in result["claims"]))

    def test_time_split_uses_actual_rows_and_reports_heldout_prediction_error(self):
        report = dossier(analyze(self.full))["validation_split"]
        self.assertEqual(report["status"], "COMPLETED_DIAGNOSTIC")
        self.assertEqual(report["training_group_count"], 80)
        self.assertEqual(report["test_group_count"], 20)
        self.assertEqual(report["test_row_count"], 180)
        self.assertIn("descriptive performance", report["generalization_claim"])
        self.assertIn("rmse", report["heldout_performance"])

        declared_only = copy.deepcopy(self.full)
        for field in ("timestamp_field", "group_field", "split_reference"):
            declared_only["validation_split"].pop(field)
        declaration = dossier(analyze(declared_only))["validation_split"]
        self.assertEqual(declaration["status"], "DECLARATION_ONLY")
        self.assertIn("no observations were evaluated", declaration["generalization_claim"])

        shifted = copy.deepcopy(self.full)
        test_groups = set(shifted["validation_split"]["test_groups"])
        for row in shifted["observations"]:
            if row["lot_id"] in test_groups:
                row["metrics"]["yield_index"] += 10
        shifted_report = dossier(analyze(shifted))["validation_split"]
        self.assertEqual(shifted_report["status"], "COMPLETED_DIAGNOSTIC")
        self.assertGreater(shifted_report["heldout_performance"]["rmse"],
                           report["heldout_performance"]["rmse"] + 8.0)

    def test_p4_02_observed_candidates_only(self):
        result = analyze(self.legacy)
        self.assertEqual(dossier(result)["D02_observed_process_window"]["candidate_factor_values"]["factor"],
                         self.oracle["P4-02"]["expected_candidate_settings"])

    def test_p4_03_actuation_is_refused(self):
        result = analyze(self.unsafe)
        self.assertEqual(result["status"], self.oracle["P4-03"]["expected_status"])
        self.assertEqual(result["claims"], [])
        self.assertIn("actuation", result["limitations"][0].lower())

    def test_p4_04_missing_constraints_refuse_candidates(self):
        request = {**self.legacy, "constraints_approved": False}
        result = analyze(request)
        self.assertEqual(result["status"], self.oracle["P4-04"]["expected_status"])
        self.assertEqual(result["claims"], [])

    def test_p4_05_collinearity_blocks_separate_sensitivities(self):
        rows = [{"id": f"SYN-{i}", "factors": {"a": x, "b": 2*x}, "metrics": {"y": 3*x}}
                for i, x in enumerate((1, 2, 3, 4, 5), 1)]
        request = {"objective": "Synthetic rank check", "context": {"process_step": "SYN-STEP"},
                   "grain": "one synthetic row", "sampling_unit": "synthetic wafer", "timestamp_semantics": "UTC",
                   "constraints_approved": True,
                   "factors": [{"name": "a", "role": "controllable", "unit": "u", "bounds": [1, 5], "approved": True},
                               {"name": "b", "role": "controllable", "unit": "u", "bounds": [2, 10], "approved": True}],
                   "metrics": [{"name": "y", "unit": "u", "direction": "maximize"}], "observations": rows}
        result = analyze(request)
        sensitivity = dossier(result)["D01_sensitivity"]
        self.assertTrue(sensitivity.get("rank_deficient"))
        self.assertEqual(result["status"], "PARTIAL")

    def test_outcome_dependent_missingness_refuses_biased_complete_case_sensitivity(self):
        rows = [{"id": f"SYN-MISS-{x}", "factors": {"x": float(x)},
                 "metrics": {"y": float(x*x)}} for x in range(10)]
        request = {"objective": "Missingness adversarial check", "context": {"process_step": "SYN-STEP"},
                   "grain": "one synthetic run", "sampling_unit": "synthetic lot", "timestamp_semantics": "UTC",
                   "constraints_approved": True,
                   "factors": [{"name": "x", "role": "controllable", "unit": "u",
                                "bounds": [0, 9], "approved": True}],
                   "metrics": [{"name": "y", "unit": "score", "direction": "maximize"}],
                   "observations": rows}
        complete = analyze(request)
        complete_slope = dossier(complete)["D01_sensitivity"]["terms"]["x"]["estimate"]
        self.assertAlmostEqual(complete_slope, 9.0, places=12)
        self.assertIn("measurement uncertainty was not supplied or propagated",
                      dossier(complete)["D01_sensitivity"]["assumptions"])
        self.assertIn("sampling-frame completeness and source rows omitted before acquisition were not independently verified",
                      dossier(complete)["D01_sensitivity"]["assumptions"])

        selected = copy.deepcopy(request)
        for observation in selected["observations"]:
            if observation["factors"]["x"] >= 6:
                observation["metrics"].pop("y")
        observed_rows = [(row["factors"]["x"], row["metrics"]["y"])
                         for row in selected["observations"] if "y" in row["metrics"]]
        mean_x = sum(x for x, _ in observed_rows) / len(observed_rows)
        mean_y = sum(y for _, y in observed_rows) / len(observed_rows)
        complete_case_slope = sum((x-mean_x)*(y-mean_y) for x, y in observed_rows) / sum((x-mean_x)**2 for x, _ in observed_rows)
        self.assertAlmostEqual(complete_case_slope, 5.0, places=12)

        refused = analyze(selected)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertEqual(refused["claims"], [])
        self.assertIn("no imputation or complete-case missingness assumption is applied", refused["limitations"][0])

    def test_supplied_measurement_uncertainty_is_not_silently_ignored(self):
        request = copy.deepcopy(self.legacy)
        for observation in request["observations"]:
            observation["measurement_uncertainty"] = {"response": 0.1}
        result = analyze(request)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["claims"], [])
        self.assertIn("measurement_uncertainty was supplied but is not propagated",
                      result["limitations"][0])

    def test_p4_06_out_of_support_rows_never_become_candidates(self):
        request = {**self.legacy, "bounds": [1, 8]}
        result = analyze(request)
        part = dossier(result)["D02_observed_process_window"]
        self.assertEqual(part["candidate_factor_values"]["factor"], [3.0, 4.0])
        self.assertEqual(dossier(result)["D01_sensitivity"]["factor_support"]["factor"]["observed_range"],
                         self.oracle["P4-06"]["expected_supported_range"])
        self.assertEqual(part["extrapolation"], "none; unobserved settings are not candidates")

    def test_p4_07_confounded_before_after_is_not_causal(self):
        request = copy.deepcopy(self.legacy)
        request["effectiveness"] = {"authorized": True, "design": "before_after", "metric": "y",
                                    "observations": [{"period": "pre", "y": 1}, {"period": "post", "y": 9}]}
        result = analyze(request)
        effect = dossier(result)["D05_effectiveness"]
        self.assertEqual(effect["status"], self.oracle["P4-07"]["expected_design_status"])
        self.assertFalse(effect["causal_claim"])
        self.assertNotIn("CAUSAL_ESTIMATE", [claim["category"] for claim in result["claims"]])
        self.assertEqual(effect["descriptive_before_after"], 8)

    def test_p4_08_randomized_effect_matches_independent_interval(self):
        result = analyze(self.full)
        effect = dossier(result)["D05_effectiveness"]
        oracle = self.oracle["P4-08"]
        self.assertEqual(effect["status"], "ESTIMATED")
        self.assertAlmostEqual(effect["estimate"], oracle["expected_difference"], places=12)
        self.assertAlmostEqual(effect["se"], oracle["expected_standard_error"], places=12)
        self.assertAlmostEqual(effect["welch_df"], oracle["expected_welch_degrees_of_freedom"], places=12)
        for actual, expected in zip(effect["ci95_welch_t_approximation"], oracle["expected_95_percent_interval"]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertTrue(effect["causal_claim"])
        self.assertEqual(result["mode"], "SYNTHETIC_DEMO")

    def test_p4_09_missing_control_withholds_effect(self):
        request = copy.deepcopy(self.full)
        request["effectiveness"]["observations"] = [r for r in request["effectiveness"]["observations"] if r["group"] == "treatment"]
        result = analyze(request)
        effect = dossier(result)["D05_effectiveness"]
        self.assertEqual(effect["status"], self.oracle["P4-09"]["expected_design_status"])
        self.assertFalse(effect["causal_claim"])

    def test_p4_10_forbidden_region_excluded_from_window_and_doe(self):
        request = copy.deepcopy(self.full)
        request["forbidden_regions"] = [{"pressure": [3, 3], "temperature": [40, 40]}]
        result = analyze(request)
        part = dossier(result)
        candidates = {tuple(sorted(r["factors"].items())) for r in request["observations"]
                      if r["id"] in part["D02_observed_process_window"]["candidate_observation_ids"]}
        forbidden = tuple(sorted({"pressure": 3.0, "temperature": 40.0}.items()))
        self.assertNotIn(forbidden, candidates)
        self.assertFalse(any(run["pressure"] == 3.0 and run["temperature"] == 40.0
                             for run in part["D04_experiment_proposal"]["runs"]))

    def test_p4_11_pareto_front_matches_hand_checked_points(self):
        rows = []
        for tag, x, y, defect in (("A", 1, 10, 5), ("B", 2, 8, 3), ("C", 3, 7, 7)):
            for replicate, noise in enumerate((-0.1, 0.0, 0.1), 1):
                rows.append({"id": f"SYN-PARETO-{tag}-{replicate}", "factors": {"x": x},
                             "metrics": {"yield": y+noise, "defect": defect-noise}, "unit_id": f"SYN-{tag}-{replicate}"})
        request = {"objective": "Synthetic Pareto check", "context": {"process_step": "SYN-STEP"},
                   "grain": "one synthetic row", "sampling_unit": "synthetic wafer", "timestamp_semantics": "UTC",
                   "constraints_approved": True,
                   "factors": [{"name": "x", "role": "controllable", "unit": "u", "bounds": [1, 3], "approved": True}],
                   "metrics": [{"name": "yield", "unit": "u", "direction": "maximize"},
                               {"name": "defect", "unit": "u", "direction": "minimize"}],
                   "objectives": [{"metric": "yield", "direction": "maximize"}, {"metric": "defect", "direction": "minimize"}],
                   "robustness": {"independent_unit_field": "unit_id"}, "observations": rows}
        result = analyze(request)
        self.assertEqual(dossier(result)["D03_tradeoffs"]["pareto_setting_ids"], self.oracle["P4-11"]["expected_pareto_setting_ids"])

    def test_p4_12_future_leakage_is_refused(self):
        request = copy.deepcopy(self.full)
        request["validation_split"]["train_timestamps"] = ["2026-01-05T00:00:00Z"]
        request["validation_split"]["test_timestamps"] = ["2026-01-04T00:00:00Z"]
        result = analyze(request)
        split = dossier(result)["validation_split"]
        self.assertEqual(split["status"], self.oracle["P4-12"]["expected_split_status"])
        self.assertIn(self.oracle["P4-12"]["expected_reason_contains"], split["reason"])

    def test_seeded_one_hundred_case_slope_oracle(self):
        sweep = self.oracle["property_sweep"]
        rng = random.Random(sweep["seed"])
        for case in range(sweep["cases"]):
            n = rng.randint(5, 15)
            xs = rng.sample(range(-100, 101), n)
            ys = [3.25*x + rng.uniform(-0.25, 0.25) for x in xs]
            mx, my = sum(xs)/n, sum(ys)/n
            expected = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sum((x-mx)**2 for x in xs)
            request = {"constraints_approved": True, "bounds": [min(xs), max(xs)], "minimum_response": -1e9,
                       "observations": [{"factor": x, "response": y} for x, y in zip(xs, ys)]}
            result = analyze(request)
            actual = dossier(result)["D01_sensitivity"]["terms"]["factor"]["estimate"]
            self.assertAlmostEqual(actual, expected, delta=1e-9, msg=f"sweep case {case}")

    def test_doe_is_seeded_non_executing_and_budget_bounded(self):
        first, second = analyze(self.full), analyze(self.full)
        a = dossier(first)["D04_experiment_proposal"]
        b = dossier(second)["D04_experiment_proposal"]
        self.assertEqual(a, b)
        self.assertFalse(a["executed"])
        self.assertEqual(a["actuation"], "none")
        self.assertEqual(a["objective_statement"], self.full["objective"])
        self.assertEqual(a["objective"]["source"], "investigation.objective")
        self.assertEqual(a["objective"]["selection_policy"],
                         "separate objectives; no scalar weighting or tradeoff preference is inferred")
        self.assertEqual(a["objective"]["metrics"], [
            {"metric": "yield_index", "unit": "synthetic index", "direction": "maximize", "min": 85, "max": None},
            {"metric": "defect_rate", "unit": "synthetic rate", "direction": "minimize", "min": None, "max": 2.8},
        ])
        self.assertEqual(a["factor_definitions"], [
            {"name": "pressure", "unit": "synthetic pressure unit", "approved_bounds": [1, 3], "role": "controllable"},
            {"name": "temperature", "unit": "synthetic temperature unit", "approved_bounds": [40, 50], "role": "controllable"},
        ])
        self.assertIn("planning approximation", a["information_value"]["qualification"])
        self.assertEqual(a["pre_execution_uncertainty"]["status"], "NOT_ESTIMATED_FOR_NEW_RUNS")
        self.assertTrue(a["required_engineer_review"])
        self.assertTrue(a["evidence_required_before_next_iteration"])
        self.assertEqual(len(a["runs"]), 8)
        request = copy.deepcopy(self.full)
        request["experiment_design"]["run_budget"] = 2
        self.assertEqual(dossier(analyze(request))["D04_experiment_proposal"]["status"], "REFUSED")

    def test_multiobjective_next_best_runs_as_shared_dossier_alternatives(self):
        request = copy.deepcopy(self.full)
        request["experiment_design"] = {
            "strategy": "next_best_multiobjective", "run_budget": 1, "blocks": 1,
            "seed": 13, "validation_seed": 17, "candidate_levels": 7,
            "independent_unit_field": "lot_id", "min_independent_units": 30,
            "validation_min_training_groups": 30, "validation_fraction": 0.2,
            "maximum_grouped_validation_rmse": 1.0,
            "fixed_effects": {"chamber": "SYN-CH-A"},
            "objective_statement": "Offer separate one-run alternatives for the two supplied outcomes.",
        }
        result = analyze(request)
        proposal = dossier(result)["D04_experiment_proposal"]
        self.assertEqual(proposal["status"], "PROPOSED", proposal.get("reason"))
        self.assertEqual(proposal["run_count"], 0)
        self.assertEqual(proposal["alternative_count"], 2)
        self.assertEqual([item["objective_metric"] for item in proposal["run_options"]],
                         ["yield_index", "defect_rate"])
        self.assertEqual(proposal["objective"]["selection_policy"],
                         "separate objectives; no scalar weighting or tradeoff preference is inferred")
        self.assertEqual(proposal["information_value"]["status"], "OBJECTIVE_SPECIFIC_MODEL_ADVISORY")
        self.assertEqual(proposal["pre_execution_uncertainty"]["status"], "SEPARATE_OBJECTIVE_MODELS")
        self.assertTrue(any("select at most one alternative" in item
                            for item in proposal["required_engineer_review"]))
        self.assertFalse(proposal["executed"])
        self.assertEqual(proposal["actuation"], "none")
        self.assertTrue(any("alternatives" in item["statement"] for item in result["claims"]))

    def test_doe_refuses_when_no_engineering_objective_is_supplied(self):
        request = copy.deepcopy(self.full)
        request["objective"] = "   "
        result = analyze(request)
        self.assertEqual(result["status"], "REFUSED")
        self.assertTrue(any("require an objective" in item for item in result.get("limitations", [])))

    def test_d02_candidate_flows_into_d04_randomized_confirmation_with_limits_and_evidence(self):
        baseline_evidence = analyze(self.full)
        baseline = dossier(baseline_evidence)
        supported = baseline["D02_supported_region"]
        self.assertEqual(supported["candidate_scope"], "MODEL_BASED_ADVISORY_SCREENING_ONLY")
        self.assertGreater(supported["screened_candidate_counts_by_region"]["interpolated"], 0)
        d02_claim = next(claim for claim in baseline_evidence["claims"]
                         if "response-surface model screened" in claim["statement"])
        self.assertIn("unvalidated model hypotheses", d02_claim["statement"])
        self.assertIn("does not validate a process window", d02_claim["statement"])
        candidate = supported["candidate_cells"][0]
        reference = {}
        for factor in self.full["factors"]:
            if factor.get("role", "controllable") != "controllable":
                continue
            name = factor["name"]
            lower, upper = factor["bounds"]
            value = candidate["factors"][name]
            reference[name] = float(upper if value == lower else lower)
        request = copy.deepcopy(self.full)
        request["experiment_design"] = {
            "strategy": "confirm_window_candidate", "run_budget": 24, "seed": 24,
            "candidate_factors": candidate["factors"], "comparison_factors": reference,
            "target_metric": "yield_index",
            "objective_statement": "Compare candidate and reference yield index under randomized lot blocks.",
            "paired_difference_sd": 0.4, "paired_difference_sd_source": "SYN-PAIRED-SD-001",
            "paired_difference_sd_basis": "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND",
            "paired_difference_sd_confidence_level": 0.95,
            "paired_difference_sd_degrees_of_freedom": 29,
            "minimum_detectable_effect": 1.0, "minimum_detectable_effect_source": "SYN-MDE-001",
            "alpha": 0.05, "target_power": 0.8,
        }
        result = dossier(analyze(request))
        proposal = result["D04_experiment_proposal"]
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertEqual(proposal["design"], "randomized blocked D02 candidate confirmation")
        self.assertEqual(proposal["candidate_evidence"]["factors"], candidate["factors"])
        self.assertEqual(proposal["candidate_evidence"]["target_metric_interval95"],
                         candidate["predictions"]["yield_index"]["predictive_interval95"])
        self.assertEqual(proposal["run_count"], 24)
        self.assertFalse(proposal["executed"])
        self.assertEqual(proposal["actuation"], "none")
        self.assertEqual(proposal["claim_method"], "randomized_blocked_confirmation_proposal")

    def test_central_composite_doe_runs_through_the_complete_p4_dossier(self):
        request = copy.deepcopy(self.full)
        request["experiment_design"] = {"strategy": "central_composite", "run_budget": 10,
                                         "center_replicates": 2, "blocks": 2, "seed": 31}
        result = analyze(request)
        proposal = dossier(result)["D04_experiment_proposal"]
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertIn("face-centered central-composite", proposal["design"])
        self.assertEqual(proposal["run_count"], 10)
        self.assertEqual(proposal["quadratic_model_matrix_rank"], 6)
        self.assertFalse(proposal["executed"])
        self.assertEqual(proposal["actuation"], "none")

    def test_cancellation_and_fake_internal_sources_fail_closed(self):
        canceled = analyze(self.full, cancel=lambda: True)
        self.assertEqual(canceled["status"], "REFUSED")
        bad_source = copy.deepcopy(self.legacy)
        bad_source["sources"] = [{"id": "PROD_TABLE", "approved_semantic_version": "v1", "grain": "wafer", "source_hash": "a"*64}]
        self.assertEqual(analyze(bad_source)["status"], "REFUSED")
        internal = {**self.legacy, "mode": "INTERNAL_AUTHORIZED"}
        self.assertEqual(analyze(internal)["status"], "REFUSED")

    def test_source_claims_require_row_level_lineage(self):
        request = copy.deepcopy(self.legacy)
        request["sources"] = [{"id": "SYN-HISTORY", "approved_semantic_version": "SYNTHETIC-1",
                                "grain": "one synthetic wafer row", "source_hash": "a"*64}]
        for row in request["observations"]:
            row["source_id"] = "SYN-HISTORY"
        result = analyze(request)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["claims"][0]["source_ids"], ["SYN-HISTORY"])
        request["observations"][0].pop("source_id")
        self.assertEqual(analyze(request)["status"], "REFUSED")

    def test_contract_validator_rejects_unknown_evidence_properties(self):
        result = analyze(self.legacy)
        result["unreviewed_field"] = "unexpected"
        with self.assertRaises(ContractError):
            validate_envelope(result)

    def test_internal_preflight_shape_never_claims_company_qualification(self):
        contract = json.loads((ROOT / "contracts" / "adapter-operations.v1.json").read_text())
        operations = {item["name"]: {"supported": True, "returns": item["returns"]}
                      for item in contract["logical_operations"]}
        operations["read_bounded"].update({"read_only": True, "max_rows": 1000, "max_seconds": 30})
        report = inspect_capability_report({"contract_version": contract["contract_version"], "environment": "INTERNAL_APPROVED_ONLY",
                                             "operations": operations})
        self.assertEqual(report["static_compatibility"], "SHAPE_COMPATIBLE")
        self.assertEqual(report["status"], "PENDING_INTERNAL")
        self.assertIn("verify server-enforced read-only grants", report["still_requires"])


if __name__ == "__main__":
    unittest.main()
