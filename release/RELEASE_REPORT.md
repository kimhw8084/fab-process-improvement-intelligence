# P4 candidate release report

Date: 2026-11-22  
Product: FAB Process Improvement Intelligence, P4  
Release state: **CANDIDATE**  
Source commit: unavailable; this folder has no Git metadata.

## Transfer artifact

- Archive: `release/FAB_INTELLIGENCE_P4_CANDIDATE.zip`
- SHA-256: `97d36ffe6e23b5af5e4b724e84a097f28682a911d834cdbbc545a07660aeda64`
- Size: 126,900 bytes
- Archive entries: 87
- Source files covered by manifest: 86
- Sidecar: `release/TRANSFER_BUNDLE.sha256`
- Source manifest: `release/SOURCE_MANIFEST.sha256`

The archive uses sorted paths and normalized ZIP metadata. The external checksum sidecar and reports containing the archive's own hash are kept beside the ZIP to avoid self-reference.

## Executed evidence

- `python bootstrap_check.py` — PASS; source manifest verified 86 files and the product suite passed.
- `python qualification/run_release_checks.py` — PASS; 37 tests, integrated synthetic D01–D05 workflow, schemas, and frozen shared contracts.
- P4-01 through P4-12 each map to an executed challenge test; 100 seeded slope cases also pass. See `release/TEST_RESULTS.json` and `qualification/critical_cases.json`.
- Fresh archive extraction, venv without pip, checksum/source-manifest verification, doctor/demo/full D01–D05 analysis, and denied network socket — PASS on macOS 26.6.2 arm64 with Python 3.11.7. See `release/OFFLINE_QUALIFICATION.json`.
- Two deterministic archive builds produced the same SHA-256 above. See `release/BUILD_REPRODUCIBILITY.json`.
- Local browser walkthrough completed with the synthetic fixture. See `release/UI_BROWSER_ACCEPTANCE.md`.
- Product runtime has no third-party packages. The optional statsmodels OLS comparison differed by at most `2.84e-14`; it was benchmark-only and is not packaged.

## Benchmark snapshot

On the recorded build host, median/p95 analysis latency was 0.321/0.406 ms for 18 rows, 0.868/0.941 ms for 1,000 rows, and 4.473/4.598 ms for 5,000 rows. The 13,000-table synthetic catalog measured 8.245/11.784 ms. These are local synthetic measurements, not an engineer task-time or ROI study; E11 remains pending.

## Open gates and limits

- E08 is `PASS_BUILD_HOST_ONLY`. The company-approved target OS and approved-host egress policy were not supplied.
- E05 and E12 remain `PENDING_INTERNAL`: no authorized MCP, company identity/scopes, approved source semantics, company data pilot, or internal reviewers were available. Synthetic data is not represented as company evidence.
- E07 remains pending formal keyboard-only, screen-reader, and approved-host accessibility review.
- E09 remains pending owner/legal distribution approval and a current vulnerability-database scan. No root product license was supplied, so SBOM license fields remain `NOASSERTION`; no clearance is claimed.
- The detailed R01–R53 and Golden standard were not supplied and are explicitly left unresolved.
- E11 remains pending a pre-registered engineer workflow, task-time/review baseline, and ROI study.

E10 passed for the exact archive: hash/checksum and source manifest verified, two builds matched, fresh extraction and runtime passed under network denial, and rollback/kill-switch instructions are included. The full external readiness bar is not met; do not label this archive `EXTERNAL_TRANSFER_READY` or `READY_INTERNAL`.

See `release/GATE_REPORT.json` for machine-readable gate states and `DELIVERY_INDEX.md` for the folder contents.
