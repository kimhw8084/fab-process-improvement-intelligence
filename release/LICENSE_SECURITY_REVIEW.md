# P4 license and security review

Review date: 2026-11-22. Scope: source and offline package in this folder, not the user's company infrastructure.

## License inventory

- Product runtime: Python standard library only. No Python package installation or JavaScript package tree is required.
- UI: plain HTML/CSS/JavaScript; no remote fonts, scripts, icons, telemetry, or CDNs.
- Product SBOM: `release/SBOM.spdx.json`. It marks the product's declared/concluded license `NOASSERTION` because the supplied project has no root `LICENSE` file.
- Optional benchmark and independent-reference packages are pinned in `qualification/benchmark-requirements.txt`; they are not copied into the product runtime and no wheelhouse or transitive package tree is bundled. A previous `pip-audit` review found scikit-learn 1.2.2 affected by CVE-2024-5206; the pin is updated to 1.5.2. The complete resolved 20-package optional tree, including pinned statsmodels 0.15.0 for independent covariance references, passed a fresh audit with zero known advisories. See `release/DEPENDENCY_AUDIT.json`.
- **Distribution rights are not cleared.** The initial launchkit did not declare a license or ownership notice. Do not interpret this ZIP as a grant to redistribute. Owner/legal review is a release blocker.

## Security review performed

- The analysis engine and UI make no outbound connections and perform no SQL, recipe write, model call, or actuation. A separate optional MCP adapter now supports explicit stdio and Streamable HTTP transports when invoked with a site-owned configuration. `mcp-test` uses only the bundled synthetic mock; no company endpoint, credentials, mapping, or data were used here.
- Bandit 1.9.4 scanned the product runtime and P4 Python sources (`fabintel/`, `products/p4/`): 0 high, 0 medium, and 8 low-severity findings. The low findings concern seeded non-cryptographic randomness used only for deterministic synthetic/DOE tasks; explicit no-shell subprocess startup for the configured MCP stdio server; and best-effort HTTP session cleanup. Each reported finding has a recorded disposition in `release/SOURCE_SECURITY_SCAN.json`. Bandit ran in an isolated tool environment and is not a product or benchmark dependency.
- The optional HTTP adapter is a network client: it enforces exact host allowlists, rejects redirects and non-loopback cleartext HTTP, uses bounded payloads/timeouts, and reads bearer credentials only from a named environment variable. The stdio adapter starts an explicit argument-vector subprocess without a shell, passes only essential environment variables by default, and permits additional secrets only through an explicit child-name-to-local-variable mapping. This code has protocol and environment-isolation tests, but has not had an independent security audit or company egress/authentication review.
- UI server binds to IPv4 loopback only, validates `Host`, rejects cross-origin requests, sets a restrictive content security policy, accepts at most 2 MiB per request, and writes no request body to access logs.
- Runtime bounds: 5,000 observations, 10 factors, 2,000 eligible Pareto rows, two active analysis jobs, 16 retained job records, 10,000 DOE runs.
- CLI/UI errors avoid returning Python tracebacks or request bodies. Browser rendering uses text nodes for evidence and does not interpret retrieved input as HTML or code.
- Cancellation and server shutdown are implemented and challenged. Server shutdown requests cancellation for active jobs; the service is foreground-only and has no daemon service manager.
- Hashes detect accidental changes but are not signed. No signing key or trusted distribution chain is supplied.

## Checks not run / remaining gates

- The shipped runtime has no third-party Python dependencies. A fresh pip-audit scan of the full optional qualification dependency tree found zero known package advisories after the scikit-learn pin remediation, recorded in `release/DEPENDENCY_AUDIT.json`. The limited Bandit static scan is also recorded. Neither check replaces independent manual threat modeling, penetration testing, interpreter/OS scanning, or legal review.
- No root license, copyright ownership evidence, legal approval, or company transfer approval is supplied.
- No actual authorized MCP/user permission check, internal threat review, target-host authentication test, or company security-owner signoff is possible here. The synthetic mock does not qualify company semantics or permissions.
- The UI was exercised in the local browser, but formal WCAG/screen-reader testing on the approved company host is pending.

**Gate result: CANDIDATE. E09 remains pending; no security or legal clearance is claimed. Public distribution is not approved.**
