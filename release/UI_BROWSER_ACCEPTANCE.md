# Local browser acceptance record

Date: 2026-11-22. Browser: Codex in-app browser (not the future company-approved host). Server: `python -m fabintel serve --port 8765`, loopback only.

Actions completed: open workspace, load the bundled JSON walkthrough, inspect the form/accessibility tree, run **Analyze dossier**, and inspect the rendered findings.

Observed: `VALID · SYN-p4-d5783ece903a · SYNTHETIC_DEMO`; D01 showed 18 observations and coefficient intervals; D03 showed six Pareto candidates; D02 showed six observed candidates and two replicated settings; D04 showed eight non-executing planned runs; D05 showed a synthetic estimate of 5 with a Welch-t interval. No positive external request occurred. The UI displayed candidate/synthetic-only status and full evidence export controls.

This confirms the local happy path and visible text alternatives. It does **not** qualify a company browser/host, formal keyboard-only task completion, screen reader behavior, WCAG conformance, SSO, or internal authorization. Those remain pending in E07/E12.
