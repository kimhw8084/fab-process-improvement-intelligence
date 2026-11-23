"""Independent fail-closed and numeric qualification for cross-step tradeoffs."""
import copy
import unittest

from products.p4.tradeoffs import cross_step_tradeoffs
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
