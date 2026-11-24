"""Tests for the scoped, shared-host contrast screening utility."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from qualification.accessibility_contrast_check import build_report, contrast_ratio


GOOD_HOST_CSS = """
:root { color: #000000; --muted: #222222; --card: #ffffff; --navy: #12334b; --blue: #000000; }
body { background: #ffffff; }
.muted { color: var(--muted); }
.module-card { background: var(--card); }
.button--primary { color: white; background: #000000; }
.suite-nav a[aria-current="page"] { color: #ffffff; background: var(--blue); }
.suite-brand small { color: #ffffff; }
.suite-header { background: var(--navy); }
.suite-nav a { color: #000000; }
.suite-nav { background: #ffffff; }
.button:focus-visible, a:focus-visible, summary:focus-visible, input:focus-visible, select:focus-visible {
  outline: 3px solid #000000;
  box-shadow: 0 0 0 6px #ffffff;
}
"""


class SharedHostContrastTests(unittest.TestCase):
    def test_contrast_ratio_reference_values(self):
        self.assertAlmostEqual(contrast_ratio("#ffffff", "#000000"), 21.0)
        self.assertAlmostEqual(contrast_ratio("#eeaf39", "#f4f7fa"), 1.804, places=3)

    def test_good_host_screen_resolves_variables_and_hashes_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            css = root / "suite.css"
            css.write_text(GOOD_HOST_CSS, encoding="utf-8")
            module = root / "P4Panel.tsx"
            module.write_text("export const P4Panel = true;\n", encoding="utf-8")

            report = build_report(css, module)

        self.assertEqual(report["status"], "PASS_SCREEN")
        self.assertEqual(report["pairs_checked"], 10)
        self.assertEqual(report["host_stylesheet_sha256"], hashlib.sha256(GOOD_HOST_CSS.encode()).hexdigest())
        self.assertTrue(report["p4_module_present_in_supplied_snapshot"])
        self.assertTrue(report["thresholds_are_screening_values_not_a_conformance_claim"])
        self.assertTrue(all(pair["status"] == "PASS_SCREEN" for pair in report["pairs"]))

    def test_host_focus_ring_failure_is_not_hidden_by_passing_text_pairs(self):
        low_contrast_css = GOOD_HOST_CSS.replace("outline: 3px solid #000000", "outline: 3px solid #c0c0c0")
        with tempfile.TemporaryDirectory() as temporary:
            css = Path(temporary) / "suite.css"
            css.write_text(low_contrast_css, encoding="utf-8")
            report = build_report(css)

        self.assertEqual(report["status"], "FAIL_SCREEN")
        self.assertTrue(all(pair["status"] == "PASS_SCREEN" for pair in report["pairs"][:6]))
        self.assertTrue(all(pair["status"] == "FAIL_SCREEN" for pair in report["pairs"][6:9]))
        self.assertEqual(report["pairs"][9]["name"], "keyboard focus indicator against header background")
        self.assertEqual(report["pairs"][9]["status"], "PASS_SCREEN")

    def test_unresolvable_host_declaration_fails_instead_of_assuming_colors(self):
        incomplete_css = GOOD_HOST_CSS.replace("background: #ffffff;", "background: transparent;", 1)
        with tempfile.TemporaryDirectory() as temporary:
            css = Path(temporary) / "suite.css"
            css.write_text(incomplete_css, encoding="utf-8")
            report = build_report(css)

        self.assertEqual(report["status"], "FAIL_SCREEN")
        self.assertEqual(report["pairs"][0]["status"], "FAIL_SCREEN")
        self.assertIsNone(report["pairs"][0]["ratio"])


if __name__ == "__main__":
    unittest.main()
