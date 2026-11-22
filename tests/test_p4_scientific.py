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
        rows = [
            {"id": "SYN-PARETO-A", "factors": {"x": 1}, "metrics": {"yield": 10, "defect": 5}},
            {"id": "SYN-PARETO-B", "factors": {"x": 2}, "metrics": {"yield": 8, "defect": 3}},
            {"id": "SYN-PARETO-C", "factors": {"x": 3}, "metrics": {"yield": 7, "defect": 7}},
        ]
        request = {"objective": "Synthetic Pareto check", "context": {"process_step": "SYN-STEP"},
                   "grain": "one synthetic row", "sampling_unit": "synthetic wafer", "timestamp_semantics": "UTC",
                   "constraints_approved": True,
                   "factors": [{"name": "x", "role": "controllable", "unit": "u", "bounds": [1, 3], "approved": True}],
                   "metrics": [{"name": "yield", "unit": "u", "direction": "maximize"},
                               {"name": "defect", "unit": "u", "direction": "minimize"}],
                   "objectives": [{"metric": "yield", "direction": "maximize"}, {"metric": "defect", "direction": "minimize"}],
                   "observations": rows}
        result = analyze(request)
        self.assertEqual(dossier(result)["D03_tradeoffs"]["pareto_observation_ids"], self.oracle["P4-11"]["expected_pareto_ids"])

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
        request = copy.deepcopy(self.full)
        request["experiment_design"]["run_budget"] = 2
        self.assertEqual(dossier(analyze(request))["D04_experiment_proposal"]["status"], "REFUSED")

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
        report = inspect_capability_report({"contract_version": "1.0.0", "environment": "INTERNAL_APPROVED_ONLY",
                                             "operations": operations})
        self.assertEqual(report["static_compatibility"], "SHAPE_COMPATIBLE")
        self.assertEqual(report["status"], "PENDING_INTERNAL")
        self.assertIn("verify server-enforced read-only grants", report["still_requires"])


if __name__ == "__main__":
    unittest.main()
