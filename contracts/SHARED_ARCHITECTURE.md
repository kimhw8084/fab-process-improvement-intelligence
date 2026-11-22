# Frozen cross-product architecture contract — v1.0.0

This document is included **identically** in all four ZIPs. It is the shared protocol from which each independent product must build; it is not permission to invent the real corporate MCP interface.

## Contract ownership and topology
- Each product exports a stable **product manifest**, a deterministic analysis operation, an evidence envelope, and UI contribution metadata.
- Four products share a single *logical* `FabSemanticsAdapter`; the **existing** administrator-approved Fab Insight MCP is authoritative for meanings and relationships. No independent production semantic catalog, permissions store, or duplicate schema approval workflow.
- One approved unified workspace uses the same navigation and evidence inspector. Preferred deployment: add views to a qualified existing host; fallback: one internal/offline self-hosted workspace, not four unrelated websites. MCP Apps is an optional display adapter only after real host qualification; OpenCode support is not assumed.
- LLM: optional intent/plan/explanation agent through approved local/intranet API; never computes trusted measurements, certifies joins, creates privileges, or substitutes for deterministic scientific validation. Deterministic mode must remain useful.

## Repository and branch conventions
`contracts/` is versioned and immutable at v1.0.0 once agents start. `fabintel/` provides the minimal bootstrap. The production build may refactor it while preserving interfaces. `products/p1..p4/` namespace is owned by the relevant Codex session. `fixtures/`, `tests/`, `qualification/`, `release/` remain product-scoped. P1 produces final suite assembler and shared-compatibility report. For an architecture change, author `proposals/CHANGE-xxx.md`, create backward-compatibility tests, and upgrade all products deliberately.

## Evidence contract
`contracts/evidence.v1.schema.json` defines the public envelope. Required: schema version, investigation ID, product ID, demo/internal mode, status, typed claims, source references, assumptions, limitations, provenance (including content hash). Every claim carries a **category** (DESCRIPTIVE, ASSOCIATION, PREDICTION, CAUSAL_ESTIMATE, INTERVENTION_VALIDATED), certainty, method and source IDs. No claim can have greater epistemic authority than its source support and study design. `REFUSED`/`INCONCLUSIVE` carry a reason and do not present a positive result.

Result status: `VALID`, `PARTIAL`, `INCONCLUSIVE`, `REFUSED`, `ERROR`. For internal results, validated authorization, correct source permissions and real provenance are mandatory. Synthetic demo IDs begin with `SYN-`, and must never appear as ordinary production evidence.

## Logical FabSemanticsAdapter — specification, NOT corporate API names
- `discover() -> capabilities`: read-only tool names/versions, permission scope, limits, supported auth, and audit semantics.
- `semantics(source_ids/version) -> approved source definitions`: source table/column meaning, row grain, effective dates, units and protected fields.
- `relationships(entity_refs) -> relationships`: approved/unapproved status, join keys, cardinality, entity identity and temporal validity. An unverified graph edge is a *candidate*, never a factual join.
- `read_bounded(query_spec, permission_context, limits) -> typed rows`: authorization enforced at real service, read-only privilege at source, maximum rows/bytes/time, cancellation, audit ID.
- `audit(result_id) -> trace`: exact source references, approved relationship and transformation IDs, timestamp and access scope.
- `propose_knowledge(...) -> pending proposal ONLY` if approved existing governance offers such a tool. Never silently update approved semantic knowledge.

Missing required capability = explicitly `UNSUPPORTED` with targeted internal preflight, **not** a default fallback to direct unapproved SQL. SQL parsers are NOT authorization boundaries.

## Shared identity/measurement/event rules
Always carry wafer/lot/product/step-instance/operation/tool/chamber context and effective-time semantics when needed. Preserve observation grain and cardinality. Require confirmed origin/timezone, measurement-unit normalization, sampling plan, records excluded, approved joins and actual scope. Process-instance ID distinguishes rework and repeated operation. No assumed chamber membership from tool group; no inferred identity equivalence without approval. Wafer spatial maps carry coordinate origin/orientation/mask/geometry and distinguish observed vs estimated. Improvements carry explicitly approved factor ranges and evidence status.

## UI integration API
A product contributes `{product_id, route, title, capabilities, required_data, analysis_entrypoint, evidence_schema_version}` as a manifest; the one host renders 1) engineer request, 2) source/scope and data-quality review, 3) findings and uncertainties, 4) drill-down evidence, 5) signed/hashed reproducible export, 6) missing-data/refusal states. UI must be keyboard-operable, clear about synthetic mode, have cancel/retry, and never launch manufacturing actuation.

## Security, governance, release states
Least privilege, deny-by-default, read-only enforcement at data boundary, bounded queries/time, prompt-injection containment for MCP metadata and retrieved text, no external egress, no cleartext secrets, audit redaction, provenance, cancellation/kill switch, rollback. `BOOTSTRAP_ONLY` is not a released product. `EXTERNAL_TRANSFER_READY` requires real target environment no-network verification, complete dependency bundle, security and license review, and independent product scientific/UX gates. `READY_INTERNAL` requires authorized real company-side tests and approval; never produced externally.
