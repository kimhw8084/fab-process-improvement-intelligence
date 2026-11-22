# P4 license and security review

Review date: 2026-11-22. Scope: source and offline package in this folder, not the user's company infrastructure.

## License inventory

- Product runtime: Python standard library only. No Python package installation or JavaScript package tree is required.
- UI: plain HTML/CSS/JavaScript; no remote fonts, scripts, icons, telemetry, or CDNs.
- Product SBOM: `release/SBOM.spdx.json`. It marks the product's declared/concluded license `NOASSERTION` because the supplied project has no root `LICENSE` file.
- `statsmodels` 0.14.0, NumPy 1.26.4, and SciPy 1.11.4 are installed on the build host and were used only for an optional numerical benchmark comparison. They are not copied into the product ZIP and are not runtime dependencies. No wheelhouse or transitive package tree is bundled.
- **Distribution rights are not cleared.** The initial launchkit did not declare a license or ownership notice. Do not interpret this ZIP as a grant to redistribute. Owner/legal review is a release blocker.

## Security review performed

- Analysis is deterministic and read-only. There is no SQL path, process-control operation, recipe write, model call, outbound HTTP client, or data upload path.
- UI server binds to IPv4 loopback only, validates `Host`, rejects cross-origin requests, sets a restrictive content security policy, accepts at most 2 MiB per request, and writes no request body to access logs.
- Runtime bounds: 5,000 observations, 10 factors, 2,000 eligible Pareto rows, two active analysis jobs, 16 retained job records, 10,000 DOE runs.
- CLI/UI errors avoid returning Python tracebacks or request bodies. Browser rendering uses text nodes for evidence and does not interpret retrieved input as HTML or code.
- Cancellation and server shutdown are implemented and challenged. Server shutdown requests cancellation for active jobs; the service is foreground-only and has no daemon service manager.
- Hashes detect accidental changes but are not signed. No signing key or trusted distribution chain is supplied.

## Checks not run / remaining gates

- `syft`, `grype`, `pip-audit`, and `osv-scanner` are not installed in the build environment. No vulnerability database was available, so there is no CVE scan or scan timestamp. The shipped runtime dependency list is empty beyond Python's own standard library.
- No root license, copyright ownership evidence, legal approval, or company transfer approval is supplied.
- No actual authorized MCP/user permission check, internal threat review, target-host authentication test, or company security-owner signoff is possible here.
- The UI was exercised in the local browser, but formal WCAG/screen-reader testing on the approved company host is pending.

**Gate result: CANDIDATE. E09 remains pending; no security or legal clearance is claimed.**
