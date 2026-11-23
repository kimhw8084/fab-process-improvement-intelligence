"""Independent checks for source-bound release benchmark evidence."""
import unittest

from qualification.benchmark import integrated_demo_is_qualified, product_source_fingerprint
from qualification.run_release_checks import benchmark_matches_product_sources


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
        qualified, statuses = integrated_demo_is_qualified({"status": "PARTIAL", "artifacts": [dossier]}, 900)
        self.assertTrue(qualified)
        self.assertEqual(statuses["D03"], "LIMITED_SCOPE")
        self.assertEqual(statuses["D04"], "PROPOSED")

    def test_missing_or_unexpected_capability_refuses_benchmark_qualification(self):
        dossier = {"D01_sensitivity": {"status": "VALID"}, "D02_supported_region": {"status": "VALID"},
                   "D03_tradeoffs": {"status": "LIMITED_SCOPE"}, "D04_experiment_proposal": {"status": "PROPOSED"}}
        qualified, _ = integrated_demo_is_qualified({"status": "PARTIAL", "artifacts": [dossier]}, 900)
        self.assertFalse(qualified)
        dossier["D05_effectiveness"] = {"status": "REFUSED"}
        qualified, _ = integrated_demo_is_qualified({"status": "PARTIAL", "artifacts": [dossier]}, 900)
        self.assertFalse(qualified)


if __name__ == "__main__":
    unittest.main()
