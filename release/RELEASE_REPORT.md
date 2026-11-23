# P4 local candidate release qualification

Date: 2026-11-23 (America/Chicago)
Product: FAB Process Improvement Intelligence, P4
Release state: **CANDIDATE — not approved for external transfer or public distribution**
Exact archive source commit: 4261d394c1e4f735079ec33c76b371ff386143ce
Local repository update: no push or publication.

## Exact local offline archive

- File: release/FAB_INTELLIGENCE_P4_CANDIDATE.zip
- SHA-256: 4a611e77894158bbc03caf0af7d3eb887f3d8f3ce5295ceda1c94ba67ff492b3
- Size: 9,309,496 bytes
- Product source files: 213
- Source manifest SHA-256: a9041796fbd706c0e08f2600c90bbac41b21f17b402abf836c9b842c74c734e0
- Checksum sidecar: release/TRANSFER_BUNDLE.sha256

Two clean detached worktrees at the exact source commit built byte-identical archives and manifests. The workspace archive and sidecar match. A fresh ZIP extraction created a virtual environment without pip; doctor, demo, full synthetic D01-D05 analysis, and an OS-sandboxed socket denial probe passed. The probe returned DENIED and no dependency installation occurred. This qualifies this local macOS ARM64 / Python 3.11.7 artifact only.

Generated benchmark and qualification output files are preserved next to the archive as evidence sidecars and are not runtime inputs in the transfer ZIP. The package retains product code, tests, docs, fixtures, required local UI module, and SPDX SBOM. The build refuses uncommitted product source changes.

## Current gate status at the artifact source commit

- PASS: E01 synthetic workflow, E02 scientific evaluation/performance, E03 schema, E04 offline dependency closure, E06 shared contracts, E10 exact archive/reproducible builds/offline extraction.
- PENDING_INTERNAL: E05 actual source authorization and semantic qualification; E12 approved company-side configuration and engineer acceptance.
- PENDING_AUTHORITATIVE_HOST_AND_FORMAL_ACCESSIBILITY: E07. The P1 host evidence is a 29-file disposable compatibility composition, not an upstream source revision or owner acceptance; formal accessibility/screen-reader review and target-host behavior remain pending.
- PENDING_TARGET_OS: E08. No company-approved host OS/network policy was supplied.
- PENDING_LICENSE_AND_INDEPENDENT_SECURITY_REVIEW: E09. Fresh pip-audit 2.10.1/PyPI lookup covered 48 dependency instances with zero known advisories. Bandit 1.9.4 recorded 8 LOW and 0 MEDIUM/HIGH findings. These limited scans do not establish OS-level security clearance, license approval, source ownership, or transfer rights.
- PENDING_ENGINEER_BASELINE: E11. Synthetic 900-row workflow p50 was 256.57 ms over 25 runs; no eligible engineer task-time or ROI baseline exists.

## Scientific and integration scope

All five P4 capability workflows execute. The integrated synthetic result intentionally remains PARTIAL: D03 is LIMITED_SCOPE, D04 PROPOSED, D05 ESTIMATED. D01 coefficients are observational associations. D02 presents 76 advisory cells, but independent exact-setting evaluation covers only 3; no conditional or simultaneous production coverage claim is made. Experiment proposals are non-executing. Observational DiD does not claim causality.

The official MCP SDK synthetic path is bounded/read-only, validates source semantics, versions, relationships, grain, times and audit receipts, then produces a shared evidence envelope. Its exact success and refusal results are schema-validated and rendered through the P1-contract-compatible P4 panel. The P1 server route itself still serves its local demo fixture and does not invoke MCP; an additive host-owned lifecycle proposal is in integration/proposals/CHANGE-002-P1-MCP-TO-P4-WORKFLOW.md. Actual company mappings, permissions and endpoint remain pending.

## Historical checksum reconciliation

At prior candidate commit d16ec28, the tracked ZIP bytes were verified as SHA-256 97d36ffe6e23b5af5e4b724e84a097f28682a911d834cdbbc545a07660aeda64. The alternate prefix 104d66e8… has no preserved full digest or source bytes and remains unverified. The current local archive is a different, reproducible artifact from source commit 4261d39 with SHA-256 4a611e77894158bbc03caf0af7d3eb887f3d8f3ce5295ceda1c94ba67ff492b3. No new public artifact was published.

Owner/legal transfer approval, company permissions and source semantics, approved target OS/network policy, authoritative P1 source/owner acceptance, formal accessibility review, independent manual security/license review, and measured engineer ROI remain pending. Do not set EXTERNAL_TRANSFER_READY or publish company-related material until the corresponding requirements are genuinely verified.
