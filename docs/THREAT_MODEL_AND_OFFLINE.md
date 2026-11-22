# Security, privacy and air-gapped release requirements

Threats: prompt injection in retrieved MCP metadata; invented SQL/join paths; privilege escalation through tools; PII, wafer IP or secret leakage to logs/model prompts; schema poisoning; malicious transitive dependency; path traversal; artifact tampering; LLM output interpreted as trusted code; unbounded joins/queries; prohibited DNS/egress; stale vulnerability databases; UI authentication gaps; background workers without kill switch; fabricated readiness badges; unsafe experiment or recipe actuation.

Controls: explicit tool allowlist, least-privileged read-only service credentials, real server-side role/resource checks, source-scoped grants, parameterized approved query operations, cardinality/grain/time validation, output redaction, provenance/hash audit, network deny by default, local-only assets, secure token references (no credentials in ZIP), signature/hash validation, worker cancellation, bounded CPU/memory, and a deterministic scientific verifier independent of LLM narrative.

Codex must conduct a threat-model review, SBOM (e.g. Syft), transitive license review (e.g. Grant + manual), vulnerability scan (e.g. Grype using preloaded DB, with DB date recorded), and static/offline dependency validation. Tools are evaluation candidates, not automatically installed or bundled by this *bootstrap* ZIP.

Offline verification requires an actual network-disabled install and runtime (not just disabling HTTP calls in one module). Verify no CDN/fonts/analytics/remote plugin registry/auto-update/pip/conda/npm download during launch. Build target-platform Python wheels, JS caches and binaries on matching OS+architecture; macOS-produced caches are not Windows proof.

Log exact OS, arch, Python/JS versions, package lock hashes, network isolation method, allowed intranet endpoints, test outcomes, internal model interface, and failure/recovery behavior. No external company data in build artifacts, metrics or tests. Maintain a shutdown/cancellation procedure that stops all workers and leaves no untracked service processes.
