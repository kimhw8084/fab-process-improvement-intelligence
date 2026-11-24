# P4 transfer candidate qualification report

## Scope and authority

This report is embedded in the self-contained P4 candidate. The byte-specific result is the adjacent `ARCHIVE_QUALIFICATION.json`, bound to the SHA-256 and source commit in `RELEASE_MANIFEST.json`. Keep those files with the archive. A result for another hash or source commit does not qualify this package.

P4 is standalone and has no P1/P2/P3 runtime dependency. The core analysis, bundled local UI, and first-run checks require no Python package installation. The optional official MCP SDK is bundled and hash-locked only for macOS ARM64/CPython 3.11. Its local synthetic transports are not evidence of company identity, permission, semantic mapping, or data correctness.

## Qualification procedure

From the adjacent release evidence directory, verify the checksum and run `qualification/qualify_final_transfer.py` against the archive. The runner performs safe fresh extraction; source-manifest checks; no-pip core installation and D01–D05 fixture analysis; the available host no-internet policy probe; the complete Python suite from extracted source; offline pinned MCP SDK installation and mock tests; a real local Chromium workflow from the extracted source; and UI start, stop, and restart on every supplied Python interpreter. `rebuild_final_transfer.py` independently rebuilds from two clean detached worktrees and compares exact archive and manifest bytes.

The runner must report `PASS_EXACT_ARCHIVE_LIMITED_PLATFORM`; `PENDING_EGRESS_POLICY` or `FAIL` is not a release pass. Browser checks prove only the listed local interaction and evidence-export cases, not full WCAG conformance. No universal offline or cross-platform claim is made.

## Decision boundaries

The inherited scientific and refusal evidence is synthetic and bounded by its recorded assumptions. Recommendations are advisory. P4 cannot write recipes or control equipment. The internal onboarding skill is self-contained and discoverable as `@p4-internal-onboarding`; company OpenCode build/model behavior is not qualified here.

This candidate is not distribution-authorized. Actual company source permission and semantics, semantic-owner review, approved target OS/network policy, legal/IP and independent security approvals, engineering acceptance, real manufacturing outcomes, ROI, and production qualification remain pending. The exact E01–E10 gate disposition and artifact-bound checks are supplied beside the final archive; none of these pending items is inferred from a synthetic test.
