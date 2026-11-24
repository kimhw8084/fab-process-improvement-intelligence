"""Independent checks for deterministic, always-unapproved MCP role proposals."""
import copy
import unittest

from fabintel.onboarding import inspect_onboarding


class Adapter:
    def __init__(self, columns, *, relation=None, version="SEM-7", grain="wafer-row"):
        self.columns = columns
        self.relation = relation
        self.version = version
        self.grain = grain

    def call(self, operation, payload):
        if operation == "discover":
            return {"tool_versions": {"demo.discover": "1", "demo.semantics": "1"},
                    "semantic_versions": [self.version], "auth_scopes": ["READ"], "audit_support": True}
        if operation == "semantics":
            sources = payload["approved_source_ids"]
            return {"approval": "SYNTHETIC_REVIEW_RECORD", "semantic_version": self.version,
                    "grain": self.grain, "source_versions": {source: "SYN-SOURCE-V1" for source in sources},
                    "units": {item["name"]: item.get("unit") for item in self.columns},
                    "column_definitions": self.columns}
        if operation == "relationships":
            return self.relation or {"approved": False, "cardinality": "many_to_many"}
        raise AssertionError(operation)


def config():
    return {"environment": "SYNTHETIC_TEST_ONLY", "qualification_status": "PENDING_INTERNAL",
        "approved_source_ids": ["SYN-SOURCE-A"], "approved_semantic_versions": ["SEM-7"],
        "operations": {"discover": {"tool_name": "demo.discover"},
                       "semantics": {"tool_name": "demo.semantics"}},
        "p4_profile": {"semantic_version": "SEM-7", "permission_scope": "READ",
            "analysis_template": {"objective": "Improve synthetic quality", "context": {"step": "etch"},
                "grain": "wafer-row", "sampling_unit": "lot", "timestamp_semantics": "UTC event time",
                "constraints_approved": True,
                "factors": [{"name": "pressure", "unit": "Pa", "bounds": [1, 2], "approved": True}],
                "metrics": [{"name": "quality", "unit": "%", "direction": "maximize"}]},
            "normalization": {"factor_fields": {"pressure": "pressure"},
                "metric_fields": {"quality": "quality"}}}}


class OnboardingProposalTests(unittest.TestCase):
    def test_exact_name_and_unit_mapping_is_proposed_never_approved(self):
        columns = [{"name": "pressure", "type": "number", "unit": "Pa", "description": "irrelevant"},
                   {"name": "quality", "type": "number", "unit": "%"},
                   {"name": "x7", "type": "number", "unit": "Pa", "description": "pressure"}]
        report = inspect_onboarding(Adapter(columns), config())
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual([p["status"] for p in report["source_role_proposals"]], ["REVIEW_REQUIRED", "REVIEW_REQUIRED"])
        self.assertTrue(all(p["authority"].startswith("proposal only") for p in report["source_role_proposals"]))
        self.assertEqual(report["authorized_review"]["status"], "PENDING_SITE_OWNER")
        self.assertEqual(report["source_role_proposals"][0]["proposal_basis"], "EXPLICIT_SITE_PROFILE_MAPPING")

    def test_exact_identifier_and_unit_can_build_only_an_unapproved_normalization_proposal(self):
        draft = config()
        draft["p4_profile"]["normalization"]["factor_fields"] = {}
        draft["p4_profile"]["normalization"]["metric_fields"] = {}
        columns = [{"name": "pressure", "type": "number", "unit": "Pa", "description": "quality result"},
                   {"name": "quality", "type": "number", "unit": "%", "description": "pressure setting"}]
        report = inspect_onboarding(Adapter(columns), draft)
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual(report["proposed_normalization"]["factor_fields"], {"pressure": "pressure"})
        self.assertEqual(report["proposed_normalization"]["metric_fields"], {"quality": "quality"})
        self.assertEqual(report["authorized_review"]["status"], "PENDING_SITE_OWNER")
        self.assertTrue(all(item["status"] == "REVIEW_REQUIRED" for item in report["source_role_proposals"]))

    def test_structurally_different_synthetic_catalog_uses_explicit_site_maps_only(self):
        draft = config()
        draft["p4_profile"]["normalization"]["factor_fields"]["pressure"] = "press_set"
        draft["p4_profile"]["normalization"]["metric_fields"]["quality"] = "q_score"
        columns = [{"name": "press_set", "type": "number", "unit": "Pa", "description": "not a recipe field"},
                   {"name": "q_score", "type": "number", "unit": "%", "description": "could mean anything"},
                   {"name": "quality", "type": "string", "unit": "%", "description": "tempting but incompatible"}]
        report = inspect_onboarding(Adapter(columns), draft)
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual([item["source_field"] for item in report["source_role_proposals"]], ["press_set", "q_score"])
        self.assertTrue(all(item["status"] == "REVIEW_REQUIRED" for item in report["source_role_proposals"]))
        self.assertEqual(report["authorized_review"]["status"], "PENDING_SITE_OWNER")

    def test_unapproved_two_source_relationship_requires_repair(self):
        draft = config()
        draft["approved_source_ids"].append("SYN-SOURCE-B")
        columns = [{"name": "pressure", "type": "number", "unit": "Pa"},
                   {"name": "quality", "type": "number", "unit": "%"}]
        report = inspect_onboarding(Adapter(columns), draft)
        self.assertEqual(report["status"], "CONFIGURATION_REPAIR_REQUIRED")
        self.assertEqual(report["relationship_review"]["status"], "REFUSED")
        self.assertEqual(report["authorized_review"]["approval_reference"], None)

    def test_misleading_descriptor_does_not_create_a_role_mapping(self):
        draft = config()
        draft["p4_profile"]["normalization"]["factor_fields"] = {}
        columns = [{"name": "x7", "type": "number", "unit": "Pa", "description": "pressure factor"},
                   {"name": "quality", "type": "number", "unit": "%"}]
        report = inspect_onboarding(Adapter(columns), draft)
        factor = report["source_role_proposals"][0]
        self.assertIsNone(factor["source_field"])
        self.assertEqual(factor["proposal_basis"], "NO_SAFE_AUTOMATIC_MATCH")
        self.assertEqual(factor["status"], "REFUSED")

    def test_incompatible_unit_and_reused_factor_outcome_field_are_refused(self):
        draft = config()
        draft["p4_profile"]["analysis_template"]["metrics"][0]["unit"] = "kPa"
        draft["p4_profile"]["normalization"]["metric_fields"]["quality"] = "pressure"
        columns = [{"name": "pressure", "type": "number", "unit": "kPa"},
                   {"name": "quality", "type": "number", "unit": "%"}]
        report = inspect_onboarding(Adapter(columns), draft)
        self.assertEqual(report["source_role_proposals"][0]["status"], "REFUSED")
        self.assertIn("unit mismatch", report["source_role_proposals"][0]["validation_errors"][0])
        self.assertIn("already assigned", report["source_role_proposals"][1]["validation_errors"][0])

    def test_missing_experiment_context_requires_configuration_repair(self):
        draft = config()
        draft["p4_profile"]["analysis_template"].pop("sampling_unit")
        columns = [{"name": "pressure", "type": "number", "unit": "Pa"},
                   {"name": "quality", "type": "number", "unit": "%"}]
        report = inspect_onboarding(Adapter(columns), draft)
        self.assertEqual(report["status"], "CONFIGURATION_REPAIR_REQUIRED")
        self.assertEqual(report["validation"][-1]["check"], "experimental context")
        self.assertEqual(report["validation"][-1]["status"], "REFUSED")


if __name__ == "__main__":
    unittest.main()
