# P4 benchmark protocol (precommitted)

Created before collecting the P4 benchmark result. This is a local software benchmark, not a FAB task-time or ROI study.

## Environment and tasks

- Host: record actual `platform.platform()`, CPU architecture, Python version, and processor with each run.
- Python runtime target for this candidate: standard library on Python 3.10+; current build host is verified separately in `release/NO_NETWORK_QUALIFICATION.md`.
- Fixed task set: integrated synthetic P4 request (18 observations), single-response sensitivity requests (1,000 and 5,000 observations), and deterministic 13,000-schema catalog generation.
- Repetitions: 25 per task; p50 and nearest-rank p95 wall time, plus `tracemalloc` peak Python allocations for one run.
- Scientific reference: fixed independent arithmetic/property suite; where installed, statsmodels OLS on the identical centered design matrix is an additional benchmark-only comparison. Product code must remain usable if it is absent.
- No public network, company data, or company MCP calls occur during the benchmark.

## Measurements and interpretation

Report coefficients and absolute coefficient differences, candidate catalog size, p50/p95 milliseconds, and peak Python allocations. No absolute latency, yield, engineer-minute, or ROI target is set without a measured engineering task baseline. A large speedup cannot compensate for a false causal, join, or safety claim. The 5,000-row cap and 2,000-row Pareto cap are defensive implementation bounds, not throughput qualification.

Human task time, correction burden, case success, review effort, and ROI remain pending an authorized engineer study with pre-registered comparable tasks.
