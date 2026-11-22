# P4 implementation decision record

Date: 2026-11-22 (client timezone). Product scope: P4 only; shared contract remains v1.0.0.

## Decisions

1. **Keep the production/runtime path standard-library-only.** Use a small deterministic OLS, observed-only constraint filter, Pareto dominance, seeded full factorial, and study-design-gated effect estimator. These cover the supported workflows without a runtime package tree or public network dependency. The local environment has statsmodels, NumPy, SciPy and scikit-learn, but those are not runtime requirements and are not copied into the bundle.
2. **Compare the numeric method with statsmodels OLS only as a benchmark reference.** Run identical fixed synthetic design matrices and compare coefficients. Do not import statsmodels from the product engine. Keep analytic fixed oracles and seeded tests runnable without optional packages.
3. **Keep the data adapter synthetic-only.** The ZIP supplies only logical MCP operations and no actual MCP tool names, credentials, permission service, source semantics, or approved joins. The product has a local capability-report shape checker; it does not invent a connector or use direct SQL.
4. **Use evidence boundaries instead of a recipe optimizer.** Process candidates are observed settings that pass supplied bounds and metric constraints. A robust observed subset requires an explicit independent-unit field, minimum count, and every observed replicate to pass. No unsupported interpolation/extrapolation is presented as a production window.
5. **Make experiment proposals and effectiveness estimates reviewable and non-executing.** DOE is deterministic full-factorial at approved bounds, with seeded order, blocks, budget refusal, and explicit approval fields. Randomized/DiD effects require synthetic evidence references and assumptions; other before/after shifts remain descriptive.
6. **Use a loopback-only UI.** The bundled browser page talks only to a local Python server bound to `127.0.0.1`, uses no external assets, suppresses request-body logs, bounds payload/rows/jobs, and supports cancellation. Company deployment still requires the actual approved authenticated host.

## OSS tournament outcome

The current product’s deterministic core and zero-dependency install are the baseline. statsmodels is a mature OLS comparator available on the build host; its result and version are recorded in `release/BENCHMARK_REPORT.json`. Its transitive numerical stack would add substantial offline qualification and licensing work while not adding a needed product capability here. Therefore it is not bundled. Other suggested packages (DoWhy, OR-Tools, Ax/BoTorch, MAPIE, PyMC, pymoo) are not included because this candidate does not need their causal graph, optimizer or uncertainty APIs to execute its bounded declared methods. No claim is made that the small methods replace those libraries for broader studies.

## Known limits

- No cluster-robust or mixed-effects OLS; standard errors assume independent, homoskedastic residuals.
- Multi-step effects require the approved relationship evidence field, but real relationship semantics cannot be checked without the internal MCP.
- Worst-observed replicate checks are empirical filters, not tolerance intervals or proof of process robustness.
- DOE power is a planning approximation for a balanced two-level contrast, not a full-factorial power guarantee.
- Effect intervals rely on approximate normal outcome assumptions and are conditional on the stated design.
- There is no declared source-code license in the supplied folder. No third-party runtime packages are bundled, but distribution rights for the product and original launchkit still need owner review.
- The supplied literal R01–R53 corpus and Golden Agentic Engineering Standard are absent; literal compliance is not verified.
