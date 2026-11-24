# P4 E01–E10 evidence map before final-archive qualification

This source-tree table records the inherited candidate evidence and boundaries. For the new transfer candidate, use the exact-hash-bound `release/final/E01_E10_FINAL_AUDIT.md` and `ARCHIVE_QUALIFICATION.json` beside the archive; those generated records supersede E08/E10 here.

| Gate | Current disposition | Evidence / boundary |
|---|---|---|
| E01 | PASS, synthetic scope | `release/full_workflow_demo_evidence.json`; D01–D05 vertical workflow. |
| E02 | PASS, synthetic oracles | `qualification/results/` and `release/BENCHMARK_REPORT.json`. |
| E03 | PASS, tested refusals | `release/GATE_REPORT.json`; invalid, permission, drift, leakage cases. |
| E04 | PASS | Frozen contracts and `release/SCHEMA_VALIDATION.json`. |
| E05 | PENDING_INTERNAL | Synthetic denial/provenance only; real grants, semantics, and owner audit remain company-only. |
| E06 | PASS, local scope | No runtime LLM; pinned MCP SDK mock qualification. |
| E07 | PASS_LIMITED_SCOPE | Standalone Chromium keyboard/workflow evidence; formal WCAG/screen-reader review pending. |
| E08 | PENDING_FINAL_ARCHIVE | The preserved baseline was verified on macOS ARM64/CPython 3.11.7. The new candidate must be requalified from fresh extraction on each claimed interpreter and under an OS no-internet policy. |
| E09 | ENGINEERING_EVIDENCE_ONLY | SBOM, notices, secret/security scans; owner, legal, and independent security approval pending. |
| E10 | PENDING_FINAL_ARCHIVE | Must be rebound to the exact final transfer archive, two clean builds, extracted-runtime report, and configured-to-local-only rollback test. |

| E11 | PENDING_INTERNAL | No real engineer task-time baseline or ROI is supplied. The pre-registered measurement protocol is in `docs/INTERNAL_ENGINEERING_ACCEPTANCE.md`. |
| E12 | PENDING_INTERNAL | Actual internal permissions, semantic-owner acceptance, approved target host, and production qualification require company evidence. |

E05 and formal E07/E09 review, E08 target-host acceptance, E10 exact-artifact closure, E11, and E12 are not inferred from synthetic evidence. The candidate can pass a limited externally controlled host qualification without establishing formal transfer authorization or company acceptance.
