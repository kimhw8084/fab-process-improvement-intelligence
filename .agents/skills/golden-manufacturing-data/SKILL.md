---
name: golden-manufacturing-data
description: Analyze process evidence with explicit population, grain, units, uncertainty, and refusal boundaries
---

# Manufacturing evidence methods

1. Verify schemas, units, time zone, wafer/lot/step identifiers, source lineage, missingness, exclusions, sampling, and the true independent unit before modeling.
2. Use mature statistical libraries when they improve inference and reduce maintenance; compare against transparent baselines and independent scientific oracles. Do not add an engine only for novelty.
3. Separate associations, predictions, and causal estimates. Diagnose dependence, chamber/product effects, nonlinearity, rank/identifiability, overlap, and residual uncertainty as applicable.
4. Separate observed, interpolated, extrapolated, unsupported, and prohibited process regions. Show predictive uncertainty and reject unsupported candidates; a candidate is not an approved recipe.
5. Cross-step tradeoffs require the approved versioned relationship contract, matching population and grain, valid effectivity, and downstream uncertainty. Otherwise return limited scope.
6. Study effects require a defensible design, assumption diagnostics, sensitivity analysis, attrition and counterevidence. Refuse causal interpretation when requirements fail.
7. No recipe write, manufacturing command, process hold, or unsupervised control is allowed.
