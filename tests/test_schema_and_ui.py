"""Source checks for P4's shared-workspace contribution."""
import json
import unittest
from pathlib import Path

from qualification.build_transfer_bundle import (is_generated_qualification_output, require_clean_worktree,
                                                 source_files)


ROOT = Path(__file__).resolve().parents[1]


class SourceContractTests(unittest.TestCase):
    def test_d05_schema_carries_declared_dependence_and_randomized_attrition_groups(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        study = schema["properties"]["effectiveness"]["properties"]
        dependence = study["shared_dependence_fields"]
        self.assertTrue(dependence["uniqueItems"])
        self.assertIn("do not prove independence", dependence["description"])
        cluster = study["randomization_cluster_field"]
        self.assertEqual(cluster["type"], "string")
        self.assertIn("five independent clusters per arm", cluster["description"])
        assignment = study["assignment_ledger"]["items"]["properties"]
        self.assertEqual(assignment["shared_groups"]["type"], "object")
        self.assertEqual(assignment["shared_groups"]["additionalProperties"]["type"], "string")

    def test_d02_schema_allows_optional_independent_evaluation_partition(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        calibration = schema["properties"]["window_exploration"]["properties"]["calibration"]
        self.assertEqual(calibration["properties"]["evaluation_value"]["type"], "string")
        self.assertNotIn("evaluation_value", calibration["required"])
        precommit = calibration["properties"]["precommit"]["properties"]
        self.assertEqual(precommit["observations_per_setting"]["minimum"], 1)
        self.assertIn("metric_bounds", precommit)
        self.assertIn("metric_bounds", calibration["properties"]["precommit"]["required"])
        self.assertNotIn("observations_per_setting", calibration["properties"]["precommit"]["required"])
        strata = precommit["strata"]
        self.assertEqual(strata["required"], ["fields", "categories"])
        self.assertEqual(strata["properties"]["fields"]["maxItems"], 5)
        self.assertEqual(strata["properties"]["categories"]["maxItems"], 100)
        fixture = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["window_exploration"]["calibration"]["evaluation_value"], "EVALUATION")

    def test_bounded_d03_envelope_requires_declared_candidate_family_and_metric_units(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        contract = schema["properties"]["familywise_mean_bounds"]
        self.assertEqual(set(contract["required"]), {
            "precommit_reference", "bounds_source_reference", "candidate_setting_ids", "metric_units", "metric_bounds"
        })
        self.assertTrue(contract["properties"]["candidate_setting_ids"]["uniqueItems"])
        self.assertEqual(contract["properties"]["metric_bounds"]["additionalProperties"]["maxItems"], 2)

    def test_d04_time_holdout_schema_requires_explicit_boundaries_and_reference(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        contract = schema["properties"]["experiment_design"]["properties"]["validation_time_split"]
        self.assertEqual(set(contract["required"]), {
            "timestamp_field", "training_end", "evaluation_start", "split_reference"})
        self.assertFalse(contract["additionalProperties"])
        self.assertEqual(contract["properties"]["training_end"]["format"], "date-time")
        self.assertEqual(contract["properties"]["evaluation_start"]["format"], "date-time")

    def test_schema_registers_objective_specific_next_best_strategy(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        strategies = schema["properties"]["experiment_design"]["properties"]["strategy"]["enum"]
        self.assertIn("next_best_multiobjective", strategies)
        self.assertEqual(schema["properties"]["objectives"]["items"]["required"], ["metric", "direction"])

    def test_d03_t_envelope_requires_exact_precommitted_setting_and_objective_family(self):
        schema = json.loads((ROOT / "products" / "p4" / "investigation.v1.schema.json").read_text(encoding="utf-8"))
        contract = schema["properties"]["familywise_t_precommit"]
        self.assertEqual(set(contract["required"]), {
            "precommit_reference", "candidate_setting_ids", "objectives"})
        self.assertEqual(contract["properties"]["candidate_setting_ids"]["maxItems"], 40)
        self.assertTrue(contract["properties"]["candidate_setting_ids"]["uniqueItems"])
        self.assertTrue(contract["properties"]["objectives"]["uniqueItems"])

    def test_schema_files_identify_version(self):
        for name in ("evidence.v1.schema.json", "product-manifest.v1.schema.json"):
            doc = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
            self.assertIn("1.0.0", doc["$id"])

    def test_manifest_declares_candidate_and_supported_capabilities(self):
        manifest = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_state"], "CANDIDATE")
        self.assertEqual(manifest["contract_version"], "1.0.0")
        capabilities = " ".join(manifest["capabilities"])
        self.assertTrue(all(code in capabilities for code in ("D01", "D02", "D03", "D04", "D05")))

    def test_p4_contributes_a_module_without_a_competing_shell(self):
        contribution = json.loads((ROOT / "products" / "p4" / "ui_contribution.json").read_text(encoding="utf-8"))
        self.assertEqual(contribution["status"], "HEADLESS_MODULE")
        self.assertEqual(contribution["ownership"]["suite_shell"], "single-suite-host")
        self.assertTrue((ROOT / contribution["module"]).is_file())
        self.assertFalse((ROOT / "ui" / "index.html").exists())

    def test_module_has_no_remote_asset_dependency_and_keeps_table_alternative(self):
        source = (ROOT / "products" / "p4" / "ui" / "P4Panel.tsx").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?:src|href)=[\"']https?://")
        self.assertNotIn("@import url(http", source)
        self.assertIn("<table>", source)
        self.assertIn("renderChart", source)
        self.assertIn("exact values and setting identifiers are listed in the table", source.lower())

    def test_retired_standalone_shell_is_not_in_the_transfer_bundle(self):
        packaged = {path.relative_to(ROOT).as_posix() for path in source_files()}
        self.assertFalse(any(name.startswith("qualification/evidence/legacy/") for name in packaged))
        self.assertTrue((ROOT / "qualification" / "evidence" / "legacy" / "index.html").is_file())

    def test_execution_ledgers_stay_in_workspace_and_out_of_product_bundle(self):
        packaged = {path.relative_to(ROOT).as_posix() for path in source_files()}
        self.assertFalse(any(name.startswith("progress/") for name in packaged))
        self.assertTrue((ROOT / "progress" / "NEXT_ACTIONS.json").is_file())

    def test_generated_qualification_results_remain_sidecars_outside_product_bundle(self):
        packaged = {path.relative_to(ROOT).as_posix() for path in source_files()}
        self.assertFalse(any(name.startswith("qualification/results/") for name in packaged))
        self.assertNotIn("release/BENCHMARK_REPORT.json", packaged)
        self.assertNotIn("release/full_workflow_demo_evidence.json", packaged)
        self.assertNotIn("release/DEPENDENCY_AUDIT.json", packaged)
        self.assertNotIn("release/SOURCE_SECURITY_SCAN.json", packaged)
        self.assertNotIn("release/UI_COMPONENT_QUALIFICATION.json", packaged)
        self.assertIn("release/SBOM.spdx.json", packaged)
        self.assertTrue((ROOT / "qualification" / "results" / "D02_SIMULTANEOUS_COVERAGE_BENCHMARK.json").is_file())
        self.assertTrue(is_generated_qualification_output("qualification/results/new-report.json"))
        self.assertTrue(is_generated_qualification_output("release/BENCHMARK_REPORT.json"))
        self.assertTrue(is_generated_qualification_output("release/full_workflow_demo_evidence.json"))
        self.assertTrue(is_generated_qualification_output("release/DEPENDENCY_AUDIT.json"))
        self.assertTrue(is_generated_qualification_output("release/SOURCE_SECURITY_SCAN.json"))
        self.assertTrue(is_generated_qualification_output("release/UI_COMPONENT_QUALIFICATION.json"))
        self.assertTrue(is_generated_qualification_output("progress/NEXT_ACTIONS.json"))
        self.assertTrue(is_generated_qualification_output("qualification/evidence/legacy/old-run.json"))
        self.assertFalse(is_generated_qualification_output("products/p4/window.py"))

    def test_bundle_builder_ignores_only_declared_generated_evidence_changes(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        generated_status = ("M  qualification/results/current.json\n M release/BENCHMARK_REPORT.json\n"
                            " M release/DEPENDENCY_AUDIT.json\n M release/SOURCE_SECURITY_SCAN.json\n"
                            " M release/UI_COMPONENT_QUALIFICATION.json\n M progress/NEXT_ACTIONS.json\n"
                            "?? progress/new-checkpoint.json\n M qualification/evidence/legacy/old-run.json")
        completed = SimpleNamespace(stdout=generated_status)
        with patch("qualification.build_transfer_bundle.subprocess.run", return_value=completed):
            require_clean_worktree()
        source_change = SimpleNamespace(stdout="M  products/p4/window.py")
        with patch("qualification.build_transfer_bundle.subprocess.run", return_value=source_change):
            with self.assertRaisesRegex(ValueError, "uncommitted product source changes"):
                require_clean_worktree()


if __name__ == "__main__":
    unittest.main()
