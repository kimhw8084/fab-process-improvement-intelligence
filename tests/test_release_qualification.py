"""Independent checks for source-bound release benchmark evidence."""
import unittest

from qualification.benchmark import product_source_fingerprint
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


if __name__ == "__main__":
    unittest.main()
