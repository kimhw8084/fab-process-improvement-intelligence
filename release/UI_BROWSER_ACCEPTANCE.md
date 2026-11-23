# Local browser acceptance record

Date: 2026-11-22. Browser: Codex in-app browser (not the future company-approved host). Server: `python -m fabintel serve --port 8765`, loopback only. All inputs were bundled synthetic fixtures.

## Exercised workflow

Loaded the 540-observation / 60-independent-lot walkthrough, inspected the labeled controls and evidence disclosure, selected D-optimal in the D04 control, applied it to the visible request, ran **Analyze dossier**, opened the D02 process-grid alternative with Enter, and inspected the result and uncertainty output.

Observed `VALID · SYN-p4-ad5a52afe136 · SYNTHETIC_DEMO`:

- **D01:** 540 observations, lot-clustered quadratic response with chamber fixed effects and coefficient intervals. The UI labels these as observational associations, not intervention effects.
- **D02:** 225 response-surface cells, 76 conservative candidate cells, 9 observed and 216 interpolated; no extrapolated, unsupported, or forbidden cells in this particular fixture. The evidence table exposes all 225 rows with support, nearby independent-unit counts, predictive intervals, and candidate status. The fixture's separately observed feasible set has 180 rows; that observed set is not presented as a validated production window.
- **D03:** 2 mean-Pareto settings across `yield_index` and `defect_rate`, based on `lot_id`; the page warns that intervals are marginal and do not imply causality.
- **D04:** 8 greedy D-optimal linear main-effects runs, `executed=false`; the UI states that the design is local to a finite grid and does not cover interaction or curvature effects.
- **D05:** synthetic randomized two-arm estimate of 5.0, Welch-t 95% interval [3.5873, 6.4127], with assignment and attrition counts and conditional causal interpretation.

The D02 table disclosure opened on Enter and the full 225-row table appeared in the accessibility tree. SVG plots have text summaries, legends/labels, and adjacent data-table alternatives. The request editor and method controls are labeled, and the page exposes evidence JSON and request JSON downloads. The app states that it remains synthetic-only and does not connect to Fab Insight.

This is an interactive local workflow and basic keyboard activation check, not a formal WCAG audit. Keyboard-only task completion, screen-reader review, approved-host/browser compatibility, SSO, and internal authorization remain pending in E07/E12.
