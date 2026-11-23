# Local browser and keyboard acceptance record

Date: 2026-11-22. Browser: Codex in-app browser (not the future company-approved host). Server: `python -m fabintel serve --port 8765`, loopback only. All inputs were bundled synthetic fixtures.

## Exercised workflow

Two local walkthroughs were observed. The first used the D-optimal D04 controls and opened the D02 process-grid alternative with Enter. The second was a keyboard-only task from page reload: Tab navigation to the file control, Shift+Tab to **Load synthetic walkthrough**, Enter, Tab navigation to **Analyze dossier**, Enter, then Enter on the D02 accessible-table disclosure. No pointer input was used in this second run.

The second run displayed `VALID · SYN-p4-7f2cf09a1af7 · SYNTHETIC_DEMO` and moved keyboard focus to the **2 · Findings and evidence** heading after completion. The heading has a visible 3 px focus outline and is described by the result-status message. The status region announces progress politely. On errors, focus returns to **Analyze dossier**. The accessibility tree exposed all form controls with names (20 enabled controls, zero unnamed in the observed page), both SVGs with title and descriptions, and all three evidence tables with captions and scoped column headers.

- **D01:** 540 observations, lot-clustered quadratic response with chamber fixed effects and coefficient intervals. The UI labels these as observational associations, not intervention effects.
- **D02:** 225 response-surface cells, 76 conservative candidate cells, 9 observed and 216 interpolated; no extrapolated, unsupported, or forbidden cells in this particular fixture. The keyboard-opened evidence table exposes all 225 rows with support, nearby independent-unit counts, predictive intervals, and candidate status. The separately observed feasible set has 180 rows and is not presented as a validated production window.
- **D03:** 2 mean-Pareto settings across `yield_index` and `defect_rate`, based on `lot_id`; the page warns that intervals are marginal and do not imply causality.
- **D04:** the keyboard walkthrough proposed 8 randomized full-factorial runs, `executed=false`; the separate control walkthrough proposed 8 greedy D-optimal linear main-effects runs, `executed=false`. Their displayed limitations require review and the D-optimal model does not cover interaction or curvature effects.
- **D05:** synthetic randomized two-arm estimate of 5.0, Welch-t 95% interval [3.5873, 6.4127], with assignment and attrition counts and conditional causal interpretation.

SVG plots have text summaries, legends/labels, and adjacent accessible data-table alternatives. The request editor and method controls are labeled, and the page exposes evidence JSON and request JSON downloads. The product states that it remains synthetic-only and does not connect to Fab Insight.

## Scope and remaining qualification

This is a local manual keyboard task and browser accessibility-tree check, not a formal WCAG audit. A dependency-free check passes 15 curated text/focus-token contrast pairs; it does not cover every rendered combination. No operating-system screen reader was run. The full color/contrast audit, browser/host matrix, formal WCAG evaluation, approved-host behavior, SSO, and internal authorization remain pending. These limits are machine-recorded in `release/UI_ACCESSIBILITY_CHECK.json` and `release/UI_CONTRAST_CHECK.json` and remain reflected in E07/E12.
