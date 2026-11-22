# Shortest *authorized* company-side qualification

**Never run this external bootstrap against actual company production systems.** This is a future operator procedure that the developed product must make executable; the included `python -m fabintel preflight` is explicitly synthetic and reports PENDING.

Target intended internal flow:
1. Obtain company approval for transfer; verify archive checksum, scanner reports and approved target OS architecture.
2. Transfer only reviewed source + binaries/dependencies/manifest through an authorized process. No external outbound connections, cloud models, or shipping real company data back out.
3. Install fully offline on the qualified OS using documented install/test commands. Select approved local/intranet model endpoint and authentication references without embedding credentials.
4. Run production-capable `qualify-internal` preflight built during the Codex goal: capability/permission discovery, version mapping against existing Fab Insight MCP, approved semantics + joins, read-only bounded retrieval, unit/time/grain/sampling checks, exact model protocol, audit/cancel/recovery and approved UI host auth.
5. Perform a small authorized read-only true-data pilot with an engineer. Reject real conclusions if source semantics, geometry, constraints, statistics or history are unverified.
6. Publish only the passed scope and actual residual caveats; obtain authorized security/owner and engineering approval before production use.

Company-specific endpoint names, permissions, OS, deployment host, authenticators, models, accepted source definitions and ROI baselines **cannot be established from this ZIP**. The internal preflight must discover or explicitly request them there, never invent them externally. No claim of zero-minute or guaranteed immediate production is defensible.
