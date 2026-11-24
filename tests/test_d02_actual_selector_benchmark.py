"""Small deterministic test for the independent actual-selector challenge."""
from hashlib import sha256
from pathlib import Path
import unittest

from qualification.benchmark_d02_actual_selector import run_benchmark


class ActualD02SelectorBenchmarkTests(unittest.TestCase):
    def test_heldout_harmonic_oracle_exercises_actual_selector_and_exact_baseline(self):
        result = run_benchmark(trials=1, seed=8000)
        self.assertEqual(result["schema"], "p4-d02-actual-selector-interpolation-benchmark/v1")
        self.assertEqual(result["status"], "DIAGNOSTIC_COMPLETE")
        self.assertEqual(result["evaluation_partition_supplied_to_product"], False)
        self.assertEqual(result["actual_p4_candidate_family"]["selected_trials"], 1)
        self.assertGreater(result["actual_p4_candidate_family"]["mean_interpolated_candidate_cells"], 0)
        self.assertEqual(result["actual_p4_candidate_family"]["any_false_feasible_trial_rate"], 1.0)
        self.assertEqual(result["predeclared_baseline"]["false_feasible_trial_rate"], 0.0)
        paired = result["paired_model_form_identifiability"]
        self.assertEqual(paired["status"], "PASS_NONIDENTIFIABILITY_DEMONSTRATED")
        self.assertTrue(paired["observations_exactly_equal"])
        self.assertTrue(paired["selector_outputs_exactly_equal"])
        self.assertEqual(paired["safe_surface_false_feasible_candidates"], 0)
        self.assertGreater(paired["hidden_surface_false_feasible_candidates"], 0)
        self.assertGreater(paired["hidden_surface_false_feasible_interpolations"], 0)
        window_path = Path(__file__).resolve().parents[1] / "products" / "p4" / "window.py"
        self.assertEqual(result["product_window_sha256"], sha256(window_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
