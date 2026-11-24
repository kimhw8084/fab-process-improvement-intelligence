"""Independent checks for source-bound release benchmark evidence."""
import unittest

from qualification.benchmark import integrated_demo_is_qualified, product_source_fingerprint
from qualification.run_release_checks import benchmark_matches_product_sources, benchmark_workflow_is_qualified
from qualification.ui_evidence import REQUIRED_STANDALONE_CHECKS, standalone_ui_evidence_matches
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


class StandaloneP4BrowserEvidenceTests(unittest.TestCase):
    def report(self):
        return {
            "schema": "p4-standalone-ui-browser/v1",
            "status": "PASS_STANDALONE_INTERACTION_LIMITED_SCOPE",
            "source_commit": "CURRENT-SOURCE",
            "source_sha256": {"app.js": "a" * 64},
            "browser": "Chromium",
            "checks": {name: True for name in REQUIRED_STANDALONE_CHECKS},
            "external_requests": [], "page_errors": [], "failed_responses": [],
            "accessibility_scope": {"keyboard_workflow": "checked",
                                    "screen_reader_and_formal_wcag_audit": "not performed"},
            "scope": "P4 standalone local application only; no P1 or other product host",
        }

    def test_source_bound_standalone_browser_workflow_is_accepted(self):
        report = self.report()
        self.assertTrue(standalone_ui_evidence_matches(report, "CURRENT-SOURCE", report["source_sha256"]))

    def test_stale_or_incomplete_browser_evidence_is_rejected(self):
        report = self.report()
        self.assertFalse(standalone_ui_evidence_matches(report, "STALE-SOURCE", report["source_sha256"]))
        report["checks"]["evidence_export_downloaded"] = False
        self.assertFalse(standalone_ui_evidence_matches(report, "CURRENT-SOURCE", report["source_sha256"]))

    def test_external_requests_errors_or_accessibility_overclaim_are_rejected(self):
        report = self.report()
        report["external_requests"] = ["https://example.invalid"]
        self.assertFalse(standalone_ui_evidence_matches(report, "CURRENT-SOURCE", report["source_sha256"]))
        report = self.report()
        report["accessibility_scope"]["screen_reader_and_formal_wcag_audit"] = "passed"
        self.assertFalse(standalone_ui_evidence_matches(report, "CURRENT-SOURCE", report["source_sha256"]))


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
