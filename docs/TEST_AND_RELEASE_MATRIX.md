# Release-blocking scientific and implementation qualification — FAB Process Improvement Intelligence

## Critical independently checked case catalog
The following describe expected behaviors **to be implemented and actually executed by Codex**. The bootstrap supplies only a tiny fixed subset, intentionally insufficient for a product-ready claim. Expand to at least the full catalog with richer parameter sweeps, property/metamorphic tests and correctly sequestered holdouts.

| ID | Input challenge | Required behavior | Independent expected-answer source |
|---|---|---|---|
| P4-01 | factor x=1..4 response=2x | **observational OLS slope=2** | fixed linear arithmetic |
| P4-02 | bounds 1..4, response min5 | **observed candidate settings only 3,4** | explicit fixed bounded observations |
| P4-03 | request to change actual recipe | **REFUSED; zero actuation** | policy oracle |
| P4-04 | no approved constraints | **REFUSED; no candidate settings** | missing constraints oracle |
| P4-05 | fully collinear factors | **cannot identify separate sensitivities** | rank-deficient model fixture |
| P4-06 | unsupported extrapolation beyond data support | **reject process window claim** | out-of-support oracle |
| P4-07 | confounded before/after positive shift | **no causal claim** | zero-effect confounded fixture |
| P4-08 | true intervention with randomized controls | **estimated effect + valid uncertainty** | known intervention oracle |
| P4-09 | no valid control population | **descriptive difference only, causal estimate INCONCLUSIVE** | missing control fixture |
| P4-10 | physical constraint violation | **exclude from candidate or refuse experiment** | forbidden-domain oracle |
| P4-11 | multiobjective tradeoff with downstream degradation | **report both objectives and conflict** | known Pareto oracle |
| P4-12 | future leakage in split | **time/run-separated validation required** | held-out experiment oracle |
| P4-26 | equal declared cohort ID but setting-specific product-family mix | **withhold cross-step Pareto comparison when declared composition differs or is absent** | exact Fraction stratum oracle; seeded zero-within-stratum-effect Simpson challenge |

## Cross-product external release gates
| ID | Check | Evidence required |
|---|---|---|
| E01 | Full integrated scientific workflow, all features | Functional E2E cases, no placeholder critical paths |
| E02 | Independent positive and numeric oracle | Independent fixed expected outputs + held-out cases |
| E03 | Adversarial false claim / refusal | All critical negative examples blocked |
| E04 | Frozen schema, APIs and compatibility | Schema validation + contract fingerprints |
| E05 | Actual read-only authorization + provenance | Denial tests, audit + source lineage |
| E06 | LLM optional + prompt injection boundary | Mock invalid model output, deterministic fallback |
| E07 | Engineer UX and accessibility | Keyboard, errors, chart/table alternatives, recovery |
| E08 | No-network platform install/runtime | Fresh matched OS/arch install with network isolation |
| E09 | Supply-chain/license/security scan | SBOM, license approvals, time-stamped CVE DB |
| E10 | Archive reproducibility, rollback, stop | Hashes, rerun unpack tests, kill switch |
| E11 | Performance, resource and user work | Pre-set baseline comparisons, p95 and user effort |
| E12 | Minimal authorized internal adaptation | Qualify-internal real MCP checklist + guided first result |

## Precommit benchmark method
- Record target OS/architecture CPU/memory, Python/JS/runtime versions, analysis task sizes, expected task mix, correctness oracle, baseline method and threshold BEFORE final holdout scoring.
- Benchmark representative small/medium/13,000-schema source discovery and dense golden event/measurement cases; do not allocate 13,000 fully populated relational tables unless benchmark calls for it.
- Measure source-selection recall and false joins, scientific validity, false positives/abstentions, p50/p95 latency, peak memory, model calls/tokens, full user-review duration and dependency/install cost.
- Noncompensatory safety/false-causal/false-join cases require zero escape in defined critical suite. No percentile score compensates for an invented manufacturing fact.
- A baseline may legitimately outperform a sophisticated model; remove components without justified incremental gain.
- Record failures and retry evidence. A unit test that merely asserts an output exists is not an independent scientific oracle.

## Evidence policy
Every external gate must map to actual test command and artifact path. The supplied `bootstrap_check.py` validates only starter file integrity and a few sanity tests. `EXTERNAL_TRANSFER_READY` is forbidden until code, offline target installation, security/license review, full user path and complete independent science tests exist. Internal readiness is separate and can never be certified using synthetic cases.
