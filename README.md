# FAB Process Improvement Intelligence (P4)

This folder contains an offline, standard-library-only candidate for P4 engineer workflows.

- **D01:** linear, interaction, quadratic, categorical fixed-effect, and category-specific slope models with pivoted QR identifiability checks, HC3 or independent-cluster covariance, confidence intervals, leverage, and residual diagnostics.
- **D02:** bounded one/two-factor response-surface exploration. Cells are labeled observed, interpolated, extrapolated, unsupported, or forbidden. A candidate requires local independent-unit support and every predictive interval to fit the explicit metric limits; it is not a production recipe.
- **D03:** independent-unit aggregated Pareto analysis. Cross-step analysis requires an explicit relationship contract, compatible population, one-to-one key, time lag, source lineage, and downstream uncertainty.
- **D04:** randomized full factorial, regular half-fraction, Latin hypercube, finite-grid D-optimal, and sequential EI suggestions. Designs are non-executing. Sequential proposals require independent-unit clustered uncertainty, grouped holdout validation, and an engineer-specified prediction-error limit.
- **D05:** randomized intention-to-treat and three-period difference-in-differences estimates with assignment denominators, attrition, baseline/pretrend diagnostics, documented bounds, counterevidence, and refusal behavior.

The configurable MCP adapter supports stdio and Streamable HTTP for an explicitly mapped, site-owned server. The only bundled mapping and live tests use a synthetic mock. No actual company tool, source semantics, permissions, endpoint, or join is supplied.

**Release state: CANDIDATE.** The offline scientific, synthetic MCP, DOE benchmark, dependency advisory, and local UI qualifications are recorded in this folder. Do not use `EXTERNAL_TRANSFER_READY`: source ownership and distribution rights, independent source security review, company target OS, formal accessibility review, actual company source semantics/permissions, engineer acceptance, and internal approval remain unverified.

Start with [START_HERE.md](START_HERE.md). The original self-contained build requirements remain in [GOAL.md](GOAL.md) and [AGENTS.md](AGENTS.md); shared P1–P4 schemas remain frozen at v1.0.0.

## Reproduce the full scientific qualification

The application runtime remains standard-library-only. The independent reference tests and OSS tournaments use a separate pinned environment:

```bash
python3 -m venv .qualification-venv
. .qualification-venv/bin/activate
python -m pip install -r qualification/benchmark-requirements.txt
python qualification/run_release_checks.py
```

The qualification runner treats skipped tests as a failure. `release/DEPENDENCY_AUDIT.json` records the full optional dependency scan; the dependencies are not needed to run the product offline.
