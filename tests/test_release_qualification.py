"""Independent checks for source-bound release benchmark evidence."""
import unittest

from qualification.benchmark import integrated_demo_is_qualified, product_source_fingerprint
from qualification.run_release_checks import (benchmark_matches_product_sources, benchmark_workflow_is_qualified,
                                               disposable_bridge_snapshot_matches,
                                               disposable_snapshot_fingerprint_matches)
from qualification.workflow_qualification import analysis_result_is_qualified


class BenchmarkSourceBindingTests(unittest.TestCase):
    def test_current_product_source_fingerprint_is_accepted(self):
        files, manifest = product_source_fingerprint()
        report = {"product_source_sha256": files, "product_source_manifest_sha256": manifest}
        self.assertTrue(benchmark_matches_product_sources(report))

    def test_stale_or_incomplete_product_source_fingerprint_is_rejected(self):
        files, manifest = product_source_fingerprint()
        stale_files = dict(files)
        first = next(iter(stale_files))
        stale_files[first] = "0" * 64
        self.assertFalse(benchmark_matches_product_sources({
            "product_source_sha256": stale_files,
            "product_source_manifest_sha256": manifest,
        }))
        self.assertFalse(benchmark_matches_product_sources({
            "product_source_sha256": files,
            "product_source_manifest_sha256": "0" * 64,
        }))


class IntegratedDemoStatusTests(unittest.TestCase):
    def test_complete_partial_demo_is_qualified_without_erasing_limits(self):
        keys = {"D01_sensitivity": "VALID", "D02_supported_region": "VALID",
                "D03_tradeoffs": "LIMITED_SCOPE", "D04_experiment_proposal": "PROPOSED",
                "D05_effectiveness": "ESTIMATED"}
        dossier = {name: {"status": status} for name, status in keys.items()}
        qualified, statuses = integrated_demo_is_qualified(
            {"status": "PARTIAL", "product_id": "p4", "artifacts": [dossier]}, 900)
        self.assertTrue(qualified)
        self.assertEqual(statuses["D03"], "LIMITED_SCOPE")
        self.assertEqual(statuses["D04"], "PROPOSED")

    def test_missing_or_unexpected_capability_refuses_benchmark_qualification(self):
        dossier = {"D01_sensitivity": {"status": "VALID"}, "D02_supported_region": {"status": "VALID"},
                   "D03_tradeoffs": {"status": "LIMITED_SCOPE"}, "D04_experiment_proposal": {"status": "PROPOSED"}}
        qualified, _ = integrated_demo_is_qualified(
            {"status": "PARTIAL", "product_id": "p4", "artifacts": [dossier]}, 900)
        self.assertFalse(qualified)
        dossier["D05_effectiveness"] = {"status": "REFUSED"}
        qualified, _ = integrated_demo_is_qualified(
            {"status": "PARTIAL", "product_id": "p4", "artifacts": [dossier]}, 900)
        self.assertFalse(qualified)


class PerformanceWorkflowQualificationTests(unittest.TestCase):
    def test_partial_demo_performance_record_requires_complete_qualified_statuses(self):
        workflow = {"status": "PARTIAL", "qualification_status": "PASS",
                    "capability_statuses": {"D01": "VALID", "D02": "VALID", "D03": "LIMITED_SCOPE",
                                            "D04": "PROPOSED", "D05": "ESTIMATED"}}
        report = {"result_checks": {"integrated_full_workflow_demo_900_rows": workflow}}
        self.assertTrue(benchmark_workflow_is_qualified(report))
        workflow["capability_statuses"]["D05"] = "REFUSED"
        self.assertFalse(benchmark_workflow_is_qualified(report))
        del workflow["capability_statuses"]["D05"]
        self.assertFalse(benchmark_workflow_is_qualified(report))


class DisposableSnapshotEvidenceTests(unittest.TestCase):
    def test_explicit_snapshot_manifest_is_verified(self):
        import hashlib

        hashes = {"contracts/suite-ui.types.ts": "a" * 64, "tests/test_suite_host.py": "b" * 64}
        manifest = "\n".join(f"{digest}  {name}" for name, digest in sorted(hashes.items())) + "\n"
        digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        evidence = {"files": 2, "file_sha256": hashes, "manifest_sha256": digest, "sha256": digest}
        self.assertTrue(disposable_snapshot_fingerprint_matches(evidence))
        evidence["file_sha256"]["tests/test_suite_host.py"] = "c" * 64
        self.assertFalse(disposable_snapshot_fingerprint_matches(evidence))

    def test_snapshot_without_hash_inventory_or_with_invalid_hash_is_rejected(self):
        self.assertFalse(disposable_snapshot_fingerprint_matches({"files": 27, "sha256": "a" * 64,
                                                                  "manifest_sha256": "a" * 64}))

    def test_mcp_bridge_snapshot_requires_the_exact_fixture_and_positive_boundary_tests(self):
        import hashlib

        fixture_sha256 = "c" * 64
        hashes = {"tests/fixtures/mcp_p4_panel_bridge.json": fixture_sha256}
        manifest = f"{fixture_sha256}  tests/fixtures/mcp_p4_panel_bridge.json\n"
        digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        snapshot = {"files": 1, "file_sha256": hashes, "manifest_sha256": digest, "sha256": digest}
        bridge = {"fixture_sha256": fixture_sha256, "p4_panel_component_tests": 18,
                  "python_bridge_fixture_tests": 2}
        self.assertTrue(disposable_bridge_snapshot_matches(snapshot, bridge, fixture_sha256))
        self.assertFalse(disposable_bridge_snapshot_matches(snapshot, bridge, "d" * 64))
        self.assertFalse(disposable_bridge_snapshot_matches(snapshot, {**bridge, "python_bridge_fixture_tests": 0},
                                                            fixture_sha256))
        without_fixture = {**snapshot, "file_sha256": {}, "files": 0}
        self.assertFalse(disposable_bridge_snapshot_matches(without_fixture, bridge, fixture_sha256))
        self.assertFalse(disposable_snapshot_fingerprint_matches({"files": 1, "file_sha256": {"x": "bad"},
                                                                  "sha256": "a" * 64,
                                                                  "manifest_sha256": "a" * 64}))


class OfflineWorkflowQualificationTests(unittest.TestCase):
    def test_extracted_partial_workflow_is_accepted_but_errors_and_wrong_product_are_refused(self):
        dossier = {"D01_sensitivity": {"status": "VALID"}, "D02_supported_region": {"status": "VALID"},
                   "D03_tradeoffs": {"status": "LIMITED_SCOPE"}, "D04_experiment_proposal": {"status": "PROPOSED"},
                   "D05_effectiveness": {"status": "ESTIMATED"}}
        result = {"status": "PARTIAL", "product_id": "p4", "artifacts": [dossier]}
        qualified, statuses = analysis_result_is_qualified(result)
        self.assertTrue(qualified)
        self.assertEqual(statuses["D03"], "LIMITED_SCOPE")
        self.assertFalse(analysis_result_is_qualified({**result, "product_id": "p3"})[0])
        self.assertFalse(analysis_result_is_qualified({**result, "status": "REFUSED"})[0])


if __name__ == "__main__":
    unittest.main()
