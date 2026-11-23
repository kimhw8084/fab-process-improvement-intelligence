# P4 license and security review

Review date: 2026-11-23. Scope: source and offline package in this folder, not the user's company infrastructure.

## License inventory

- Scientific core and CLI: Python standard library only.
- UI: a headless React 19.2 peer module owned by P1; P4 adds no chart or table runtime. The shared host's actual dependency lock and final UI host are not available here.
- Product SBOM: `release/SBOM.spdx.json`. It marks P4's declared/concluded license `NOASSERTION` because the supplied project has no root `LICENSE` file. It includes the pinned Golden MIT method snapshot and the optional MCP SDK dependency inventory.
- The optional MCP SDK bundle contains 28 SHA-256-pinned macOS ARM64 / CPython 3.11 wheels. Each wheel has an embedded license file; three packages have no SPDX expression in their wheel metadata. `license-inventory.json`, wheel hashes, and the copied CycloneDX SBOM are packaged. This is evidence for owner/legal review, not approval. No Windows/Linux wheelhouse is included.
- Optional benchmark and independent-reference packages are pinned in `qualification/benchmark-requirements.txt`; they are not copied into the core product runtime. The bundled MCP SDK has a separate hash-locked wheelhouse for macOS ARM64 / CPython 3.11. The qualification audit checks both the resolved benchmark/reference tree and every locked MCP SDK dependency (48 package instances across the two optional trees; shared exact versions may be counted in both scopes). The prior scikit-learn 1.2.2 pin affected by CVE-2024-5206 is updated to 1.5.2. The latest timestamped scan is in `release/DEPENDENCY_AUDIT.json`; the scan covers 48 optional package instances and found no known advisories in its recorded data.
- **Distribution rights are not cleared.** The initial launchkit did not declare a license or ownership notice. Do not interpret this ZIP as a grant to redistribute. Owner/legal review is a release blocker.

## Security review performed

- The scientific core and headless panel perform no outbound connections, SQL, recipe write, model call, or actuation. An optional official MCP SDK adapter supports stdio and Streamable HTTP when invoked with explicit site-owned configuration. `mcp-test` uses only the bundled synthetic mock; no company endpoint, credentials, mapping, or data were used here.
- Bandit 1.9.4 scanned product runtime and P4 Python sources (`fabintel/`, `products/p4/`): 0 high, 0 medium, and 8 low-severity B311 findings. They flag seeded pseudorandomness used only for reproducible synthetic fixtures and DOE proposals, not security tokens or secrets. Each is recorded with a disposition in `release/SOURCE_SECURITY_SCAN.json`, whose product-source commit is `361dcd64d468f294cc2991120cad5353316c4b23`. This scan includes the latest D02 runtime change at that commit. The follow-up evidence commit changes only scan reports, this review note, and continuation records, outside Bandit’s scanned source scope. The scan is limited and is not an independent source review. Bandit ran in an isolated tool environment and is not a product or benchmark dependency.
- The optional HTTP adapter enforces exact host allowlists, rejects redirects and non-loopback cleartext HTTP, sets the SDK SSE event bound, checks decoded result size, and reads bearer credentials only from a named environment variable. The SDK stdio transport starts an explicit argument-vector subprocess without a shell, using the SDK's safe environment inheritance plus explicit child-name-to-local-variable mappings. Protocol tests use P4's synthetic server over stdio and Streamable HTTP; independent security review and company egress/authentication review remain pending.
- The remaining loopback HTTP API is a synthetic integration fixture for bounded engine jobs and cancellation. It serves no HTML and is not a deployable product backend.
- Runtime bounds: 5,000 observations, 10 factors, 2,000 eligible Pareto rows, two active analysis jobs, 16 retained job records, 10,000 DOE runs.
- CLI/UI errors avoid returning Python tracebacks or request bodies. Browser rendering uses text nodes for evidence and does not interpret retrieved input as HTML or code.
- Cancellation and server shutdown are implemented and challenged. Server shutdown requests cancellation for active jobs; the service is foreground-only and has no daemon service manager.
- Hashes detect accidental changes but are not signed. No signing key or trusted distribution chain is supplied.

## Checks not run / remaining gates

- The shipped core runtime has no third-party Python dependencies. A fresh pip-audit scan covers the optional qualification tree and the complete hash-locked MCP SDK tree; Bandit scans product Python sources. Neither check replaces independent manual threat modeling, penetration testing, interpreter/OS scanning, or legal review.
- No root license, copyright ownership evidence, legal approval, or company transfer approval is supplied.
- No actual authorized MCP/user permission check, internal threat review, target-host authentication test, or company security-owner signoff is possible here. The synthetic mock does not qualify company semantics or permissions.
- The P4 React module passed 12 component tests and typecheck against P1's local React 19.2/Vitest 5.1.1 toolchain. A disposable composition of the available P1 shell with current P4 passed 39 frontend tests, typecheck, production build, 11 route tests, and a live synthetic analysis/chart plus denied-permission browser flow. The P1 source snapshot has no resolvable Git commit and the disposable registry pin is not an upstream change. P1 owner confirmation, formal WCAG/screen-reader testing, contrast review, and target-host behavior remain pending.

**Gate result: CANDIDATE. E09 remains pending; no security or legal clearance is claimed. Public distribution is not approved.**
