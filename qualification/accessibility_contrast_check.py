"""Check reviewed UI foreground/background token pairs without third-party tools."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "ui" / "index.html"
OUTPUT = ROOT / "release" / "UI_CONTRAST_CHECK.json"
PAIRS = [
    ("body text", "#152d3e", "#f2f6f7", "text"),
    ("header body", "#f3fbfc", "#102f3e", "text"),
    ("brand", "#9fd9ce", "#102f3e", "text"),
    ("header subtitle", "#c5d8de", "#102f3e", "text"),
    ("button text", "#ffffff", "#176c64", "text"),
    ("warning heading", "#765000", "#fff8e8", "text"),
    ("finding heading", "#176c64", "#ffffff", "text"),
    ("subdued content", "#4e6673", "#ffffff", "text"),
    ("error status text", "#8c3021", "#fff0ee", "text"),
    ("good status text", "#155d4d", "#e9f7f2", "text"),
    ("chart axis text", "#203e49", "#ffffff", "text"),
    ("chart tick text", "#405d68", "#ffffff", "text"),
    ("footer", "#536d78", "#f2f6f7", "text"),
    ("table header", "#254956", "#edf4f5", "text"),
    ("focus outline", "#168b76", "#ffffff", "non_text_indicator"),
]


def luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    results = []
    for name, foreground, background, kind in PAIRS:
        threshold = 4.5 if kind == "text" else 3.0
        tokens_present = all(re.search(re.escape(color), source, re.IGNORECASE)
                             for color in (foreground, background))
        value = contrast_ratio(foreground, background)
        results.append({"name": name, "foreground": foreground, "background": background,
                        "kind": kind, "ratio": round(value, 4), "minimum": threshold,
                        "source_tokens_present": tokens_present,
                        "status": "PASS" if tokens_present and value >= threshold else "FAIL"})
    report = {"status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
              "method": "WCAG relative luminance contrast ratio on a curated set of declared UI token pairs",
              "scope": "Not a complete WCAG audit; does not inspect every rendered combination, image, browser, or operating-system setting.",
              "text_threshold": 4.5, "non_text_indicator_threshold": 3.0,
              "pairs_checked": len(results), "pairs": results}
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
