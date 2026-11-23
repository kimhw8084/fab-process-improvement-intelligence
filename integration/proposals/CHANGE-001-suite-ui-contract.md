# Proposal to P1: suite UI contract capability IDs and scientific chart extensions

**Owner:** P1 suite contract owner (proposal only; P4 does not amend P1 contracts)

## Current compatibility findings

P1's local `suite-ui-module.v1` snapshot accepts only capability IDs matching `A[0-9]{2}`. The P4 product manifest uses D01 through D05. Mapping D-codes to A-codes would invent product semantics, so the P4 contribution registers the correct route and module with an empty capability list and records the gap.

P1's current `suite-chart.v1` accepts only line and scatter charts with point values. It cannot represent the P4 process-window heatmap, classification region, or confidence/predictive intervals. P4 currently sends a two-objective D03 scatter to the shared renderer and exposes exact process-window cells, estimates, and intervals in semantic tables.

## Requested owner review

1. In the next suite UI contract version, permit product-owned capability namespaces or generic stable capability strings without assigning P4 IDs in the shared schema.
2. In a versioned chart contract, consider heatmap cells with an explicit `observed | interpolated | extrapolated | unsupported | prohibited` classification and optional estimate/interval fields.
3. Require an accessible table fallback and visible uncertainty representation for every chart kind.
4. Have P1 publish the approved component API, chart renderer API, design tokens, and an integrated host fixture with versioned hashes.

Until P1 accepts and qualifies changes, P4 keeps the current contracts unmodified. `research/p1-suite-ui-reference/REFERENCE.json` identifies the exact local snapshot hashes used for this proposal.
