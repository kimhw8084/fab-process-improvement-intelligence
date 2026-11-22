# Autonomous implementation backlog — FAB Process Improvement Intelligence

This ordered backlog is suitable for an empty Codex repository. Maintain `progress/STATE.md` as a durable work ledger, not a substitute for execution. Always choose next release-critical gap by its engineering risk, not aesthetic appeal.

## Stage 0 — Reproducible bootstrap, architecture freeze (first work)
- [ ] Run integrity check, basic tests and seeded 13,000-table generator; classify current code BOOTSTRAP_ONLY.
- [ ] Read every contract, spec, policy and critical test. Document gap inventory; freeze shared v1 schema and exact folder/API boundaries.
- [ ] Verify the authoritative R01–R53/Golden standard if actually present; never invent exact text. Track uncovered literal compliance honestly.
- [ ] Establish one product vertical-slice E2E harness with a source-selection view, deterministic calculation, typed evidence, refusal and export.

## Stage 1 — Full integrated product behavior
- [ ] Implement D01: Parameter Sensitivity; independently validate result and negative path.
- [ ] Implement D03: Cross-Step Tradeoffs; independently validate result and negative path.
- [ ] Implement D02: Candidate Process Window; independently validate result and negative path.
- [ ] Implement D04: Next-Best Experiment; independently validate result and negative path.
- [ ] Implement D05: Change-Effect Evaluation; independently validate result and negative path.
- [ ] Implement source/relationship permission checks and rigorous provenance; no fake semantic mappings.
- [ ] Build complete interactive UI inside shared workspace conventions, real empty/error/permission/cancel/recovery paths and full source-to-claim drilldown.
- [ ] Fully implement safe deterministic operation with LLM disabled; add local-model orchestration only where objectively beneficial.

## Stage 2 — Independent qualification and simplification
- [ ] Build fixed challenging positive/negative cases, oracle separation, hidden holdouts, metamorphic tests and blinded engineer-review tasks.
- [ ] Establish baseline metrics; research/benchmark mature OSS against them; select minimal validated stack and pin versions.
- [ ] Fix all scientific false positives, invalid relationships and unsupported conclusions; add regressions.
- [ ] Verify performance p50/p95 and resource budgets; optimize measured bottlenecks without sacrificing rigor.

## Stage 3 — External release engineering
- [ ] Build complete target-OS/arch offline dependencies/installer; test fresh installation under blocked internet egress.
- [ ] Supply-chain SBOM/license/vulnerability checks, security threat testing, auth scopes, audit redaction, stop/rollback, artifact hashes and reproducible archive.
- [ ] Deliver automated internal MCP capability discovery and compatibility/semantic preflight; DO NOT guess any internal API endpoint.
- [ ] Execute full UI and scientific product flows, record evidence in machine-readable release report and independent final audit.
- [ ] Create final product archive and (P1 when siblings available) suite compatibility/integration report; verify extracted package.

## No-handoff continuation policy
Every checkbox represents work to do, not a question to ask. Codex should autonomously resolve implementation questions, seek credible documented evidence, run commands, and iterate to completion. Site-only unknowns remain PENDING_INTERNAL while all external work continues. Halt only for permission/security/legal constraints or a genuinely unresolvable requirement after all authorized alternatives are exhausted; never falsely mark a blocked gate passed.
