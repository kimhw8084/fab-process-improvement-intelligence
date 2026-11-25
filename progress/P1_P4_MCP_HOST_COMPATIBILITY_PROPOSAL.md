# P1/P4 MCP compatibility change proposal

**State:** Proposed for the P1 owner; no P1 source was changed. The inspected P1 workspace is unversioned, so this is disposable-overlay evidence rather than accepted suite integration.

## Minimal change

In P1 `fabintel/mock_mcp_server.py`, preserve all P1-specific fixtures, scenarios, delay/cancellation behavior and MCP implementation. Change only the synthetic P4 relationship metrics to match the explicit P4 mapping:

```diff
- "metric_field": "response_primary", "metric": "quality"
+ "metric_field": "response_primary", "metric": "yield_index"
...
- "metric_field": "response_secondary", "metric": "secondary_quality"
+ "metric_field": "response_secondary", "metric": "defect_rate"
```

Update `integration/product-source-registry.v1.json` at `products.p1.mcp_synthetic_integration.synthetic_peer_sha256` to `214efd103181659e872680386219f25a2021f96afe768a55ae93ede59115588e`. That SHA-256 is the P1 peer with only these two metric-name edits. Keep the registry hash test enabled.

These are synthetic test semantics only; this proposal conveys no Samsung authorization or mapping.

## Disposable-overlay evidence

- The current P1 peer refused P4 analysis because its relationship metric names did not exactly match the P4 target metric/source-field mapping.
- Applying only the two metric-name edits and refreshing the peer hash pin passed all 32 `tests/test_suite_host.py` tests, including audited P4 acquisition (900 normalized rows and evidence artifact) and combined P1/P4 cancellation coverage.
- Earlier current-P1-source UI checks passed 64 frontend tests, strict typecheck, and 29 P4 component tests. The P1 workspace itself remains untouched.

## Qualification boundary

P1 owns this peer and registry. Before acceptance, rerun P1 host, suite-wide and release-provenance checks against a versioned P1 commit. Owner acceptance, actual shared-host qualification, company authorization, real source mappings and formal accessibility remain pending.

## Shared focus-indicator preflight

The current unversioned P1 stylesheet fails the local source screen: the declared amber keyboard focus indicator has contrast 1.804:1 on the body background and 1.9397:1 on white cards/navigation (3:1 screening threshold). This is a selected-declaration screen, not a WCAG finding or rendered-browser audit.

In a disposable P1 copy only, the following shared-shell rule passed all 10 source-screen pairs (dark ring on light surfaces; white ring on the dark header):

```css
.button:focus-visible, a:focus-visible, summary:focus-visible,
input:focus-visible, select:focus-visible {
  outline: 2px solid #ffffff;
  outline-offset: 2px;
  box-shadow: 0 0 0 5px #142b3d;
}
```

The current-source P4 route was also exercised in the disposable P1 host: synthetic MCP acquisition completed with 900 observations and produced an evidence-bearing `PARTIAL` analysis; the separately invoked permission-denial path returned `REFUSED`, `NOT_ACCESSED`, and withheld positive findings. This host source has no Git identity and the overlay is not authoritative. The stylesheet proposal has not been accepted by P1; keyboard rendering, assistive technology, formal WCAG, and target-host qualification remain pending.
