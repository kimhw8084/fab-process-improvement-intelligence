# Shortest *authorized* company-side qualification

**Do not connect to an actual company system until the appropriate site owner has approved the exact read-only test.** `python -m fabintel preflight` is local and reports PENDING. `python -m fabintel mcp-test` contacts only the bundled synthetic server and is the externally testable protocol check.

Target intended internal flow:
1. Obtain company approval for transfer; verify archive checksum, scanner reports and approved target OS architecture.
2. Transfer only reviewed source + binaries/dependencies/manifest through an authorized process. The analysis engine remains offline; enabling the optional MCP adapter initiates explicitly configured site communication. Do not use cloud models or export company data.
3. Install fully offline on the confirmed OS using documented install/test commands. Keep credentials in the site's approved secret environment; do not place them in JSON or source.
4. A site owner must author and review `requirements/site-mcp-config.v1.schema.json` configuration from actual discovered server capabilities. Supply the approved source IDs, semantic versions, operation/tool names, argument/result mappings, limits, read-only scope, and approval reference. The shipped example and blank template are synthetic/pending and contain no real mappings.
   For stdio servers, the adapter passes only essential process variables by default. Map a required secret through `transport.env_from` (child variable name to an existing local environment variable name); never put secret values in the JSON config.
5. Only after approval, run `python -m fabintel site-mcp-qualify --config <site-config> --site-approval-reference <approved-ref> --authorized-site-test`. Inspect the local report and require site-side owner/security signoff; this runner never upgrades company readiness by itself.
6. Perform a small authorized read-only true-data pilot with an engineer. Reject conclusions if source semantics, geometry, constraints, statistics or history are unverified.
7. Obtain source owner, security, legal, target-host, and engineering acceptance before any transfer or production use.

Company-specific endpoint names, permissions, OS, deployment host, authenticators, models, accepted source definitions and ROI baselines **cannot be established from this folder**. Site operators must discover and explicitly configure them; this package invents none. The site qualification command has not been run against a real system. No claim of zero-minute or guaranteed immediate production is defensible.
