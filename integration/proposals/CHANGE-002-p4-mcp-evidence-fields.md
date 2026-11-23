# P1 logical adapter evidence-field proposal

**Owner:** P1 shared-adapter contract owner (proposal only; the frozen shared contract remains unchanged)

## Current behavior

P4 consumes the frozen `adapter-operations.v1.json` contract at version `1.0.0`. Its configurable result maps may carry additional fields. The P4 workflow independently requires these fields before normalizing data or invoking D01–D05:

- `semantics.semantic_version` and a complete per-source `semantics.source_versions` map;
- `relationships.relationship_contract`, including the owner-approved relationship identity, population, grain, cardinality, and effective-time definition;
- `read_bounded.source_versions` matching the semantic catalog and a per-source SHA-256 extract hash map.

The official MCP SDK transport stays generic. P4 does not set tool names or company permissions. Missing fields, drift, mismatched join lineage, invalid grain, or invalid audit evidence withhold analysis. Tests exercise these cases only with `SYN-` fixtures.

## Additive owner decision requested

Consider a separately versioned adapter contract revision that standardizes semantic-catalog version echo, versioned relationship-contract evidence, and per-source content hashes as optional negotiated capabilities. Keep existing version 1.0 consumers compatible. Products that need these values must explicitly request and validate them; absence must remain `UNSUPPORTED` or a refusal, never a fallback to inferred semantics.

P4's current implementation remains compatible with the version 1.0 logical operation contract by mapping these extra fields above the frozen base contract and refusing if they are absent. This proposal does not assert P1 adoption, actual Samsung source mappings, authorization, or internal qualification.
