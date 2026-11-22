# Scientific algorithms and critical decision rules — FAB Process Improvement Intelligence

## Three evidence-permission modes and deterministic boundaries

**Level 1 OBSERVATIONAL:** classify factors as controllable vs measured environmental covariates and latent/unknown; validate units, factor ranges, recipe/product/layer and chamber contexts. Fit interpretable baselines (stratified OLS/mixed-effects, interactions, nonlinear terms where justified). Compare against simple means, quantify uncertainty, nonstationarity and multicollinearity. Non-identifiability prevents causal statements.

**Level 2 EXPERIMENT DESIGN:** require engineer-approved objective(s), domain, forbidden combinations, physical/quality/safety constraints and actual authorization *before suggesting candidate settings*. Build deterministic full-/fractional-factorial or response-surface/Latin designs with blocking and power assumptions; compare more advanced Bayesian acquisition on an identical synthetic ground-truth optimizer benchmark. Optimize information gain or supported quality metrics, not illegal equipment actions. No automatic experiment launch.

**D02 robust windows:** distinguish already observed points, interpolated regions validated inside support, and all unsupported extrapolations. Constrain by all explicit physical and downstream requirements. Calibrate uncertainty over proper new-run/new-tool holdouts; do not label predicted feasible window as production qualified.

**D03 cross-step tradeoffs:** require approved temporal links to downstream outcomes; multi-output model or observed Pareto frontier with uncertainty. If no downstream data, return scope-limited within-step tradeoff rather than speculation. Never secretly choose engineering value weights or override a constraint.

**Level 3 INTERVENTION-VALIDATED:** evaluate documented experiments or interventions. Randomized comparison if truly randomized, otherwise choose DiD/ITS/matched controls only when diagnostics support design assumptions; report sensitivity to unmeasured confounding and separate statistical evidence from production qualification. Record null/harmful experiments, not only wins.

**OSS candidates:** statsmodels (baseline), DoWhy for explicit causal graphs/estimands, OR-Tools/Emukit/Ax/BoTorch for constrained designs only after an independent performance/complexity tournament, MAPIE/PyMC/pymoo for uncertainty and multiobjective scenarios as justified. Heavy dependencies are conditional, never mandatory merely from name recognition.


## Minimum correct implementation order
A. Validate source/identity/units/permissions BEFORE scientific analysis. B. Implement an independently understandable deterministic baseline and a fixed positive/negative oracle. C. Create an evidence envelope and show a complete user workflow. D. Add the full required scientific methods with assumption diagnostics and falsifying cases. E. Compare advanced OSS only where it can beat or materially extend that baseline; freeze test cases first. F. Run the combined product and real target-OS/offline qualification. G. Repeat audit until all gates pass.

## Mathematical and evaluation requirements
- For numeric estimates, specify the estimand, unit, effective independent sample, uncertainty method, algorithm/version and declared applicability domain.
- For classification, retrieval and anomaly cases, precommit held-out metrics, precision/recall/calibration or appropriately justified equivalents. Never fit thresholds to evaluation answers.
- Use group/time/device/wafer/lot/experiment-aware holdouts where dependencies require them; random measurement-row splits are not acceptable evidence of broader generalization.
- Distinguish data observed, data estimated and data unknown; refuse if physical constraints or study assumptions cannot be verified.
- Run property, metamorphic, adversarial and counterfactual *tests* where meaningful (e.g. changing labels must not create a spurious causal claim; adding an unapproved join must trigger refusal).
- An LLM explanation must be mechanically checked against the verified evidence object. An independent code-based oracle, not an agent's agreement, determines scientific pass/fail.

## Scientific peer review rubric
Engineer/reviewer should be able to answer: Is the population actually eligible? What was the measured unit and its grain? Which approved sources and joins were used? Could sampling or timing explain the observation? Is the statistical estimand identifiable? Which alternative explanations were tested? Which result is observed rather than predicted? What result would invalidate the conclusion? Does the method generalize to unseen wafers/lots/tools/periods? What is explicitly unknown?
