# P1 suite UI contract compatibility record and additive proposal

**Owner:** P1 suite contract owner (proposal only; P4 does not amend P1 contracts)

## Current observed compatibility

The accessible P1 folder has no Git metadata, so its source commit cannot be verified. Its `suite-ui-module.v1.schema.json` was refreshed into the P4 read-only snapshot on 2026-11-22 and hashed as `e3f0da372a2528d993a8a1555403c6e115df7256edfc8cfc0f09be3995e17c4f`. Compared with the prior local snapshot, this schema now permits uppercase capability namespaces such as P4's D01 through D05 and adds `spatial_map` to the `required_data` enum. The P4 contribution registers D01–D05 directly and validates against this accessible snapshot. This verifies local compatibility only; it does not establish P1 upstream approval or host integration.

P1's accessible `suite-chart.v1` still accepts line and scatter charts with point values. It cannot represent the P4 process-window heatmap, region classification, or predictive intervals. P4 delegates supported D03 scatter rendering to the shared renderer and exposes exact process-window cells, classifications, estimates, and uncertainty in semantic tables.

## Requested owner follow-up

1. Pin the accessible P1 schema changes to an upstream source commit and confirm the D01–D05 module registration.
2. In a versioned chart contract, consider heatmap cells with explicit `observed | interpolated | extrapolated | unsupported | prohibited` classification and optional estimate/interval fields.
3. Require an accessible table fallback and visible uncertainty representation for every chart kind.
4. Publish the approved component API, chart renderer API, design tokens, and an integrated host fixture with versioned hashes.

P4 does not modify P1-owned contracts. `research/p1-suite-ui-reference/REFERENCE.json` identifies the current accessible snapshot hashes. The actual P1 host remains unavailable for integrated qualification.
