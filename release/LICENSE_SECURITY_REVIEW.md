# P4 license and security evidence

Review date: 2026-11-24. Scope: this offline P4 candidate and its declared optional dependencies. This is engineering evidence, not formal clearance.

## Product and dependency scope

- P4 runs independently of P1, P2, and P3. Its scientific core, CLI, local HTTP UI, browser assets, onboarding skill, and core tests use Python/browser standard capabilities; no third-party package is required for offline core analysis or UI operation.
- The UI is P4's bundled local HTML/CSS/JavaScript/SVG workflow. It loads no CDN, remote font, telemetry, or external AI service. Authorized internal MCP discovery/read is an opt-in connection to an owner-approved internal endpoint; it is not part of local-only mode.
- `release/SBOM.spdx.json` covers P4, the pinned Golden development-method snapshot, the optional MCP SDK dependency tree, and qualification-only packages. `release/QUALIFICATION_DEPENDENCY_LICENSE_INVENTORY.json` records exact resolved metadata and license-file hashes for the qualification/reference packages. Those packages are not core runtime dependencies.
- The optional official MCP Python SDK 2.3.0 has a complete 28-wheel SHA-256-locked closure only for macOS ARM64/CPython 3.11. Its wheel/license artifacts are inventoried under `vendor/mcp-sdk/2.3.0/macos-arm64-cp311/`. Three wheel metadata entries have no SPDX expression. No other-platform SDK wheelhouse is supplied.
- The 20 qualification-only packages and 28 optional SDK wheels were scanned by the recorded `pip-audit` run. Findings, timestamp, versions, and limits are in `release/DEPENDENCY_AUDIT.json`. This is advisory evidence for the scanned versions, not a guarantee about the OS, interpreter, future advisories, or licensing.
- The P4 source has no first-party license or supplied ownership/assignment record; its SPDX license is `NOASSERTION`. The Golden snapshot's MIT license applies to that upstream snapshot only. `release/TRANSFER_RIGHTS_ASSESSMENT.md` records the unresolved rights decision.

## Security evidence

- `release/SOURCE_SECURITY_SCAN.json` records Bandit findings for `fabintel/` and `products/p4/`; the scan excludes test and release tooling. Seeded random-number findings are limited to deterministic synthetic fixtures and proposals. Read the recorded dispositions and source commit before relying on it.
- The MCP SDK transport is official and configured, not a custom protocol implementation. Host allowlists, bounded results, no redirects, explicit stdio argument vectors, environment-variable credentials, and test-only synthetic discovery are covered by local tests. Discovery calls only `initialize` and `tools/list`; proposals are never approvals. No actual company endpoint, permission, credential, semantic mapping, or manufacturing data was accessed.
- The exact extracted candidate runner performs a caller-enforced egress denial probe and checks local browser requests. Such checks qualify only the named host and environment. Hashes are unsigned and detect accidental changes only.
- Local error handling, row/analysis bounds, cancellation, foreground shutdown, refusal behavior, and no recipe/equipment write path are covered by source tests and the exact-archive qualification report.

## Remaining decisions

- **Not cleared:** ownership, employer assignment, third-party legal interpretation, trademark use, and transfer or redistribution rights. A company legal/IP owner must authorize transfer.
- **Not cleared:** independent security review, target-host security/egress policy, OpenCode build/model approval, and production approval.
- **Not qualified:** Windows, Linux, macOS Intel, and any macOS/Python combination not listed in the final archive report. The bundled MCP SDK remains macOS ARM64/CPython 3.11 only.
- **Not established:** company semantic correctness, real-data manufacturing performance, engineer acceptance, ROI, or production readiness.

**Disposition: local engineering candidate only. Do not infer authorization from a clean scan, a synthetic mock, or the candidate archive.**
