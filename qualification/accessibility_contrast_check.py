"""Screen selected shared-suite CSS contrast pairs against a supplied host snapshot.

This deliberately does not claim a complete WCAG audit. The snapshot is supplied by
the caller so P4 does not copy, fork, or silently qualify the P1-owned shell.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CSS_RELATIVE = Path("products/p1/ui/suite.css")
P4_MODULE_RELATIVE = Path("products/p4/ui/P4Panel.tsx")
PAIR_SPECS = (
    ("suite body text", (":root", "color"), ("body", "background"), "text"),
    ("muted module text", (".muted", "color"), (".module-card", "background"), "text"),
    ("primary button text", (".button--primary", "color"), (".button--primary", "background"), "text"),
    ("active navigation text", (".suite-nav a[aria-current=\"page\"]", "color"),
     (".suite-nav a[aria-current=\"page\"]", "background"), "text"),
    ("header subtitle", (".suite-brand small", "color"), (".suite-header", "background"), "text"),
    ("regular navigation link", (".suite-nav a", "color"), (".suite-nav", "background"), "text"),
)
FOCUS_SELECTORS = (".button:focus-visible", "a:focus-visible", "summary:focus-visible",
                   "input:focus-visible", "select:focus-visible")
FOCUS_BACKGROUNDS = (("body background", ("body", "background")),
                     ("module card background", (".module-card", "background")),
                     ("navigation background", (".suite-nav", "background")),
                     ("header background", (".suite-header", "background")))


def _blocks(css: str) -> list[tuple[list[str], dict[str, str]]]:
    """Read simple selector/declaration blocks, including blocks inside media rules."""
    cleaned = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    blocks = []
    for selector_text, body in re.findall(r"([^{}]+)\{([^{}]*)\}", cleaned):
        selectors = [selector.strip() for selector in selector_text.split(",")
                     if selector.strip() and not selector.strip().startswith("@")]
        declarations = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            declarations[name.strip().lower()] = value.strip()
        if selectors:
            blocks.append((selectors, declarations))
    return blocks


def _property(blocks: list[tuple[list[str], dict[str, str]]], selector: str, name: str) -> str | None:
    values = [declarations[name] for selectors, declarations in blocks
              if selector in selectors and name in declarations]
    return values[-1] if values else None


def _resolve_color(value: str | None, blocks: list[tuple[list[str], dict[str, str]]]) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value in {"white", "black"}:
        return "#ffffff" if value == "white" else "#000000"
    match = re.fullmatch(r"var\((--[a-z0-9_-]+)\)", value)
    if match:
        return _resolve_color(_property(blocks, ":root", match.group(1)), blocks)
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return "#" + "".join(char * 2 for char in value[1:])
    return None


def luminance(color: str) -> float:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError(f"expected six-digit hex color, got {color!r}")
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _pair(name: str, foreground_spec: tuple[str, str], background_spec: tuple[str, str],
          kind: str, blocks: list[tuple[list[str], dict[str, str]]]) -> dict:
    foreground_decl = _property(blocks, *foreground_spec)
    background_decl = _property(blocks, *background_spec)
    foreground = _resolve_color(foreground_decl, blocks)
    background = _resolve_color(background_decl, blocks)
    minimum = 4.5 if kind == "text" else 3.0
    ratio = contrast_ratio(foreground, background) if foreground and background else None
    passed = ratio is not None and ratio >= minimum
    return {"name": name, "foreground_selector": foreground_spec[0],
            "foreground_property": foreground_spec[1], "foreground": foreground,
            "background_selector": background_spec[0], "background_property": background_spec[1],
            "background": background, "kind": kind, "ratio": round(ratio, 4) if ratio is not None else None,
            "screening_minimum": minimum,
            "status": "PASS_SCREEN" if passed else "FAIL_SCREEN"}


def build_report(css_path: Path, module_path: Path | None = None) -> dict:
    css = css_path.read_text(encoding="utf-8")
    blocks = _blocks(css)
    pairs = [_pair(name, fg, bg, kind, blocks) for name, fg, bg, kind in PAIR_SPECS]
    focus_blocks = [declarations for selectors, declarations in blocks
                    if any(selector in selectors for selector in FOCUS_SELECTORS)
                    and ("outline" in declarations or "box-shadow" in declarations)]
    indicator_colors = []
    for focus_block in focus_blocks:
        for property_name in ("outline", "box-shadow"):
            declaration = focus_block.get(property_name, "")
            for match in re.finditer(r"(?i)(#[0-9a-f]{3,8}|\bwhite\b|\bblack\b)", declaration):
                resolved = _resolve_color(match.group(0), blocks)
                if resolved and resolved not in indicator_colors:
                    indicator_colors.append(resolved)
    for background_name, background_spec in FOCUS_BACKGROUNDS:
        background_decl = _property(blocks, *background_spec)
        background = _resolve_color(background_decl, blocks)
        ratios = ({color: contrast_ratio(color, background) for color in indicator_colors}
                  if background else {})
        passing_colors = [color for color, ratio in ratios.items() if ratio >= 3.0]
        best_color = max(ratios, key=ratios.get) if ratios else None
        ratio = ratios.get(best_color) if best_color else None
        minimum = 3.0
        pairs.append({"name": f"keyboard focus indicator against {background_name}",
                      "foreground_selector": ", ".join(FOCUS_SELECTORS),
                      "foreground_property": "outline and box-shadow",
                      "foreground": best_color, "indicator_colors": indicator_colors,
                      "passing_indicator_colors": passing_colors,
                      "background_selector": background_spec[0],
                      "background_property": background_spec[1], "background": background,
                      "kind": "non_text_indicator", "ratio": round(ratio, 4) if ratio is not None else None,
                      "screening_minimum": minimum,
                      "status": "PASS_SCREEN" if passing_colors else "FAIL_SCREEN"})

    report = {
        "schema": "p4-shared-suite-contrast-screen/v1",
        "status": "PASS_SCREEN" if all(pair["status"] == "PASS_SCREEN" for pair in pairs) else "FAIL_SCREEN",
        "method": "WCAG relative-luminance contrast ratio on selected declarations in a caller-supplied shared P1 stylesheet",
        "scope": "A source-level screen of selected CSS declarations only. For focus it checks declared outline and box-shadow color candidates against selected host surfaces; this is not a rendered indicator test. It does not compute the browser cascade, focus geometry/area, zoom/reflow, assistive-technology behavior, all color pairs, or WCAG conformance. P1 host ownership and formal accessibility qualification remain separate.",
        "thresholds_are_screening_values_not_a_conformance_claim": True,
        "host_stylesheet": str(css_path),
        "host_stylesheet_sha256": hashlib.sha256(css.encode("utf-8")).hexdigest(),
        "p4_module_present_in_supplied_snapshot": bool(module_path and module_path.is_file()),
        "p4_module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest()
        if module_path and module_path.is_file() else None,
        "pairs_checked": len(pairs), "pairs": pairs,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", type=Path, required=True,
                        help="P1-owned snapshot containing products/p1/ui/suite.css")
    parser.add_argument("--output", type=Path,
                        help="JSON report destination (defaults to qualification/results/P1_SHARED_UI_CONTRAST_SCREEN.json)")
    args = parser.parse_args()
    css_path = args.suite_root / CSS_RELATIVE
    if not css_path.is_file():
        parser.error(f"shared P1 stylesheet not found: {css_path}")
    module_path = args.suite_root / P4_MODULE_RELATIVE
    report = build_report(css_path, module_path)
    output = args.output or ROOT / "qualification" / "results" / "P1_SHARED_UI_CONTRAST_SCREEN.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_SCREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
