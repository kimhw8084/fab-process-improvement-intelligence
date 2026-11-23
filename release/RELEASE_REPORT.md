# P4 release qualification record

Date: 2026-11-22 (America/Chicago)  
Product: FAB Process Improvement Intelligence, P4  
Release state: **CANDIDATE — external transfer not approved**  
Product implementation commit: `15a150dea2cb1d9c3ba356035219b47b10f2c1da`  
Complete package source snapshot: `65521742de34240f8de03e52d89b87288497c585`  
Repository update: local only; no public push or publication.

## Exact local bundle

- File: `release/FAB_INTELLIGENCE_P4_CANDIDATE.zip`
- SHA-256: `40312dc3a780171aaec7a8b96868fe6784eab567fde7d13a9ee77a6f71dc05ad`
- Size: 273,135 bytes
- ZIP entries: 109 (108 source files plus the archive manifest)
- Source manifest: `release/SOURCE_MANIFEST.sha256`
- Checksum sidecar: `release/TRANSFER_BUNDLE.sha256`

Two clean detached worktree builds at package source commit `65521742de34240f8de03e52d89b87288497c585` produced the same SHA-256. The workspace archive and sidecar match those builds; the source manifest matches the clean committed tree. A fresh extraction and dependency-free virtual environment passed the local offline qualification. See `release/BUILD_REPRODUCIBILITY.json` and `release/OFFLINE_QUALIFICATION.json`.

The earlier artifact reconciliation remains separate: the tracked ZIP blob at published candidate commit `d16ec28` has SHA-256 `97d36ffe6e23b5af5e4b724e84a097f28682a911d834cdbbc545a07660aeda64`. The reported prefix `104d66e8…` has no preserved full digest or source bytes and remains unverified. Neither old value is the current local bundle checksum.

## Product and independent qualification evidence

- **D01–D05:** integrated synthetic dossier is VALID. The fixed evaluation includes held-out nonlinear, confounded, clustered/correlated, sparse/out-of-domain, multiobjective, failed-experiment, attrition, and invalid-assumption cases; 100 seeded slope cases; fixed numeric oracles; and refusal checks. The current local qualification suite recorded 84 tests with zero skips. This qualifies the implemented synthetic evaluation scope, not production performance on fab data.
- **D01 reference parity:** matched centered first-order OLS coefficients differ from statsmodels 0.15.0 by at most `1.42e-14`; statsmodels is benchmark-only and is not a product runtime dependency.
- **D02:** observed, interpolated, extrapolated, and unsupported regions are reported separately; unsupported candidates are refused. Benchmark and test details are in `tests/test_d01_d02_independent.py` and `release/TEST_RESULTS.json`.
- **D03:** approved relationship contracts, compatible population checks, uncertainty propagation, and Pareto tradeoffs are exercised; incompatible populations fail closed.
- **D04:** fixed-seed comparisons against SciPy Latin hypercube sampling, pyDOE3 D-optimal design, exhaustive finite-grid optimum, and scikit-optimize expected improvement passed. The product retained portable methods only where the independent benchmark demonstrated performance and rejects the tested unsupported multimodal proposal. See `release/D04_OSS_COMPARISON.json` and `release/D04_OSS_DECISION.md`.
- **D05:** study-design balance, assumptions, sensitivity, counterevidence, attrition, and failed runs are included; confounded or invalid designs do not produce causal claims.
- **MCP adapter:** configurable JSON-RPC stdio and Streamable HTTP mapping were tested against the bundled realistic synthetic mock, including tool discovery, pagination, SSE, bounded read-only access, scoped configuration, and fail-closed permission/mapping cases. No actual Samsung connector, tool identifiers, source mapping, or authorization is claimed. Company qualification remains a separate required step.
- **Engineer workflow:** local keyboard-only execution completed the demo and analysis with Enter, returned visible focus to the results heading, and opened the full 225-row D02 evidence table. The local UI check found no unnamed enabled controls; its evidence tables have captions and scoped headers, and both SVG charts have titles/descriptions. Fifteen curated token contrast pairs passed. This continuation also adds a visible keyboard focus outline for the clipped native JSON file input, with a regression check. Screen-reader and formal WCAG/approved-host reviews were not run. See `release/UI_BROWSER_ACCEPTANCE.md`, `release/UI_ACCESSIBILITY_CHECK.json`, and `release/UI_CONTRAST_CHECK.json`.
- **Performance:** on the documented local macOS/arm64/Python 3.11.7 host, the 540-row/60-lot integrated synthetic workflow measured p50 70.4 ms and p95 71.7 ms over 25 repetitions. The benchmark has no engineer task-time or ROI baseline; no ROI claim is made. See `release/BENCHMARK_REPORT.json`.
- **Dependencies/source scan:** product runtime uses only the Python standard library. A clean audit of 20 optional qualification packages found zero known advisories. A scoped Bandit scan recorded eight LOW findings and zero MEDIUM/HIGH findings; each LOW finding has a documented disposition. These scans do not substitute for independent manual/OS security review or license/legal review. See `release/DEPENDENCY_AUDIT.json`, `release/SOURCE_SECURITY_SCAN.json`, and `release/LICENSE_SECURITY_REVIEW.md`.
- **Offline:** exact local ZIP extraction, checksum/manifest checks, doctor, demo, integrated D01–D05 analysis, and a network-deny probe passed under the caller's OS sandbox. The product itself does not enforce an OS network sandbox; deployment must apply its host network policy. See `release/NO_NETWORK_QUALIFICATION.md`.

## Gate state

The gate record at package source commit `65521742de34240f8de03e52d89b87288497c585` is `CANDIDATE`: E01–E04, E06, and E10 pass within their recorded synthetic/external scope. E05 and E12 remain `PENDING_INTERNAL`; E07 remains `PENDING_FORMAL_ACCESSIBILITY`; E08 remains `PENDING_TARGET_OS`; E09 remains `PENDING_LICENSE_AND_INDEPENDENT_SECURITY_REVIEW`; E11 remains `PENDING_ENGINEER_BASELINE`. The gate definitions and evidence are in `release/GATE_REPORT.json`.

Company-only authorization, approved source semantics and lineage, actual target host/OS, formal accessibility review, ownership and distribution rights, independent security review, and real engineer ROI remain explicitly pending until verified by their appropriate owners. The canonical literal R01–R53/Golden requirements were not supplied in this folder, so literal requirement-by-requirement compliance is not asserted.

This package is **not** `EXTERNAL_TRANSFER_READY`, `READY_INTERNAL`, or publicly distributable. No public push was made. Do not publish company-related material until ownership, license, and security review authorize distribution.
