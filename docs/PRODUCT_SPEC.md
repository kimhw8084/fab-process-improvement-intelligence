# Complete engineering product specification — FAB Process Improvement Intelligence

**Scope:** D01 Sensitivity + D02 Robust Process Window + D03 Tradeoffs + D04 Next Experiment + D05 Effectiveness  
**Product ID:** `p4`  
**Shared interface:** `contracts/SHARED_ARCHITECTURE.md` v1.0.0  
**State of supplied code:** BOOTSTRAP_ONLY. The actual product is to be built by Codex.

## Required result, not just a feature list
Make FAB process improvement scientifically defensible: identify candidate controllable factors, analyze multi-step tradeoffs, explore robust evidenced process regions, design authorized next experiments and evaluate completed interventions, with no manufacturing actuation.

## One real end-to-end engineer workflow
**Start:** Engineer supplies an engineering objective plus approved factor bounds, process context, metric definitions, constraints and available historical/experiment data through existing approved MCP semantics.

**Finish:** One decision dossier with descriptive factor-response associations, supported tradeoffs, candidate feasible-region boundaries, engineer-reviewable experimental plan, and post-change effect assessment where study design supports it. No unsafe recipe recommendation or fictitious causal effect.

Codex must implement the complete path, not four/five disconnected notebooks. The operator must be able to produce a new authorized investigation, inspect evidence source-by-source, understand uncertainty, save/share a reviewable artifact and rerun the same result with frozen inputs and software version.

## Combined capability contract
| Subsystem | Required source evidence | Implementation required | Explicit scientific refusal boundary |
|---|---|---|---|
| **D01 factor sensitivity** | Approved factor, observed setting/condition, response, equipment/recipe/product and units | Interactions, nonlinearity, variance, multicollinearity, hierarchy, overlap/positivity diagnostics | Observed correlation is not intervention response |
| **D03 tradeoffs** | Time-valid cross-process linked responses and consistent metric definitions | Multiobjective response analysis, Pareto set on supported data, downstream impact uncertainty | No downstream linkage => limited-scope result with warning |
| **D02 candidate process window** | Evidence-supported response model plus human-approved allowed ranges and specifications | Constrained feasible region, uncertainty, extrapolation guard, robust Pareto tradeoffs | A modeled region is not a validated production recipe |
| **D04 experiment design** | Approved factor grid, blocked/randomization design, budgets and no-go constraints | Classical DOE and power baseline, constrained Bayesian information-gain only if superior | Proposal only, never executes experiment |
| **D05 change effectiveness** | Actual documented intervention and valid control groups/histories | Study design selection, DiD/ITS/matched comparisons when assumptions permit, sensitivity and negative outcomes | No valid control/parallel-trend/overlap => no causal effect |

## Shared scientific preconditions
1. Actual authorized source definitions are discovered from the existing approved Fab Insight MCP and checked for version/effective time; no invented company tool names or table joins.
2. Result data retains wafer/lot/step-instance/metric/tool/chamber where applicable, and always declares its true grain, timestamp semantics, units, sampling plan, exclusions and approved relationship source.
3. LLM may help translate user intent into a proposed plan; deterministic tools independently approve allowed sources/relationships/operations, compute results, and validate claims.
4. Every claim is typed, sourced, uncertainty-qualified, and distinguishable from a hypothesis. Invalid or incomplete analysis returns REFUSED/PARTIAL/INCONCLUSIVE as appropriate.
5. If advanced functionality requires unavailable real data, the rest of the product remains independently useful; no demo-generated fake findings in company mode.
6. No manufacturing equipment commands, recipes updates, unsupervised process holds, or other side effects.

## Expected usable deliverables
- Deterministic API/CLI and an interactive product view in ONE Fab Intelligence workspace, compatible with P1–P4 manifests.
- Source, population and assumption inspector; explanatory visuals with tabular alternatives; missing-data and refusal handling; evidence dossier with immutable source provenance.
- Independent scientific tests, held-out challenge suites, model-off path, permission-denial tests, full integration and UI interaction verification.
- Fully offline and tested target-OS binary/dependency package, licensing and SBOM, checksums, rollback/kill switch, minimal authorized internal MCP/model preflight.
- Reproducible user task evaluations and a nonfabricated ROI study plan; no unmeasured claims of customer adoption/financial returns.

## Non-goals and controlled dependencies
- Not a new semantic approval system or replacement for Fab Insight MCP.
- Not a generic RAG chatbot, autonomous production control service, or unrelated corporate workflow tool.
- Not a duplicate of the existing standalone sampling-prediction project.
- Not a promise that synthetic data proves any Samsung engineering effect.
- Keep independent capability modes when full cross-process/yield/change-control data is unavailable.

## Mandatory review artifacts
1. Algorithm and OSS tournament (`docs/SCIENCE_AND_METHODS.md`), showing why each included component is needed.
2. Data/source contract, every real permission/scope and invalid join case.
3. Product user journey, edge states and UI test evidence.
4. Scientific negative/positive oracles, verified comparisons with a simple baseline.
5. `release/GATE_REPORT.json` with gate-by-gate actual evidence and honest states.
6. Transfer package hash, offline dependency provenance, approved licensing and valid internal first-run preflight.
