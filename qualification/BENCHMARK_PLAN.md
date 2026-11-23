# P4 benchmark protocol v3 (precommitted)

Protocol v3 was frozen on 2026-11-22 before collecting the refreshed result in `release/BENCHMARK_REPORT.json`. It supersedes v2 because D02 now requires an independent-unit holdout, and the integrated fixture was expanded from 60 to 100 independent lots. This is a local software benchmark, not a FAB task-time or ROI study.

## Environment and tasks

- Record actual OS, CPU architecture, Python version, and processor with each run. Current host qualification is in `release/NO_NETWORK_QUALIFICATION.md`.
- Product runtime target: Python 3.10+ standard library; optional benchmark and independent-reference tools are isolated to `qualification/benchmark-requirements.txt`.
- Measure 25 repetitions per task with `perf_counter`, report median and nearest-rank p95 wall time, and one-run `tracemalloc` peak allocation.
- Tasks: the integrated 900-observation / 100-independent-lot D01–D05 walkthrough; generated single-metric sensitivity workloads at 18, 1,000, and 5,000 observations; and a 13,000-row schema-catalog construction task. The catalog contains table metadata, not populated data tables.
- Compare D01 coefficients on the same 900 fixed synthetic observations and the same centered first-order interaction model against statsmodels OLS; report coefficient deltas and reference-fit runtime. This isolates the arithmetic comparison from the full demo's chamber, quadratic, and clustered settings.
- `qualification/run_release_checks.py` fails if any scientific test is skipped. Install the pinned optional qualification requirements before running the full test suite.
- No company data, live MCP call, equipment action, or public network call occurs in the benchmark workload. Dependency advisory lookup is a separate qualification step.

## Measurements and interpretation

Report input size, VALID result status, p50/p95 milliseconds, peak Python allocations, and the exact host. The OLS comparison must use identical observations, centered main effects, and one two-factor interaction; maximum coefficient difference is the numerical parity measure. No absolute latency, yield, engineer-minute, or ROI target is invented without a measured engineering-task baseline.

The 5,000-row analysis cap and 2,000-row Pareto cap are defensive implementation limits, not throughput qualification. Human task time, correction burden, case success, review effort, and ROI remain pending an authorized engineer study with pre-registered comparable tasks.
