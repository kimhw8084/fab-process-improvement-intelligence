# Exact-candidate acceptance audit

**Artifact:** `P4_INTERNAL_TRANSFER_CANDIDATE.zip`  
**SHA-256:** `23cba15ba3bfb3219837f0c6f833da93103506f2833a9eefdfa136d750d8ca80`  
**Source commit:** `0dc3105652ac2a7928d7424a96be4cbf4fea2840`  
**Source manifest:** `3555d4ac7c50a42c3b34b6048dd94f542ca5a91af5c2c32b9eeba701cfbaf4f5`  
**Archive qualification:** `ARCHIVE_QUALIFICATION.json`; two detached rebuilds: `BUILD_REPRODUCIBILITY.json`.

| Gate | Disposition | Evidence and boundary |
|---|---|---|
| E01 | PASS, synthetic | Exact extracted standalone Chromium workflow completed demo and synthetic MCP acquisition, D01–D05, evidence inspection, and export. |
| E02 | PASS, synthetic scope | Preserved independent scientific oracles/benchmarks plus exact-source suite: 285 tests run, 23 SDK-dependent cases skipped there and separately exercised in the pinned SDK run (29 passed). |
| E03 | PASS, synthetic refusal scope | Preserved invalid-assumption, permission, schema-drift, bounds, cancellation, and unsupported-evidence cases; exact-source suite passed. |
| E04 | PASS | Eight schema/fixture validations passed from extracted archive; source and manifest hashes verified. |
| E05 | PENDING_INTERNAL | Real source grants, company semantics, bounded production reads, and audit-owner acceptance were not accessed or asserted. |
| E06 | PASS, local scope | Core works without an AI dependency; core egress probes were denied by macOS `no-internet`; optional SDK was hash-installed offline and tested only against synthetic local servers. |
| E07 | PASS_LIMITED_SCOPE | Chromium 158.0 checked keyboard flow, headings, table alternative, evidence, errors, and export; no formal WCAG or screen-reader review. |
| E08 | PASS_LIMITED_PLATFORM | Exact extraction/core/no-internet/startup/rollback passed on macOS ARM64 CPython 3.11.7, 3.12.9, 3.13.13, and 3.14.5. SDK/browser qualification was on 3.11.7. This does not approve the company target host. |
| E09 | ENGINEERING_EVIDENCE_ONLY | SPDX SBOM and license inventories supplied; pip-audit 2.10.1 reported 0 advisories among 48 pinned dependency instances; Bandit reported 8 low and 0 medium/high findings. Ownership, license interpretation, independent security and legal approvals remain pending. |
| E10 | PASS, exact artifact | Adjacent SHA, exact extraction, two byte-identical clean rebuilds, full workflow, stop/restart and synthetic-config rollback to local-only all verified for this hash. |

| Additional gate | Disposition |
|---|---|
| E11 engineer baseline / ROI | PENDING_INTERNAL; protocol is in `docs/INTERNAL_ENGINEERING_ACCEPTANCE.md`; no real performance or ROI is claimed. |
| E12 internal qualification | PENDING_INTERNAL; actual permissions, target host, engineer acceptance, and company approvals remain required. |

## Required readiness outcomes

- **External engineering readiness:** exact local candidate is reproducibly qualified for the stated macOS ARM64 scopes; company transfer authorization is not established.
- **Offline installation readiness:** macOS ARM64 core is verified on CPython 3.11.7–3.14.5. Optional MCP SDK is verified only on 3.11.7. CPython 3.10 is source-declared but unverified. macOS Intel, Windows, and Linux are not supported for this transfer candidate.
- **Autonomous onboarding readiness:** self-contained OpenCode skill is bundled as `@p4-internal-onboarding`; OpenCode 1.3.9 discovered it from the exact fresh extraction under macOS `no-internet` with model fetching and auto-update disabled. Company OpenCode/model behavior remains unverified. Discovery proposes schemas only; authorized semantic-owner review is mandatory.
- **Legal/security evidence readiness:** engineering inventory and limited scans are present; legal/IP and independent security clearance are not.
- **Formal transfer authorization:** PENDING_OWNER_AND_LEGAL_REVIEW.
- **Internal manufacturing qualification:** PENDING_INTERNAL; no Samsung endpoint, manufacturing data, or source permission was used.
- **Production readiness:** NOT_ESTABLISHED.

## Historical checksum reconciliation

The immutable qualified baseline archive from source commit `885447f` is separately preserved and rehashed as `ba7ef4fea8847f1563963772275dea3f0940737ea06fd421a97f464f33ff67ec`. The earlier `97d36ffe…` record refers to bytes attributed to prior commit `d16ec28`; the alternate `104d66e8…` was only an unverified prefix without its input artifact. Neither is the checksum of this final candidate. No historical archive was overwritten by this release.

## First internal action

After formal transfer authorization, extract this archive, open the extracted folder with the company-approved internal OpenCode build/model, and send the one-instruction prompt in `docs/INTERNAL_COMPANY_FIRST_RUN.md`. The skill performs local checks first and asks only for owner authorization and irreducible engineering inputs; all generated mappings remain unapproved until reviewed.
