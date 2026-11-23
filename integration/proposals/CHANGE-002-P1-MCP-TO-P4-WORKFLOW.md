# CHANGE-002 — P1-owned MCP request lifecycle for P4

Status: **PROPOSED; P1 owner review and all company qualification pending**

This proposal closes the remaining suite-host boundary between P1's request lifecycle and P4's already tested MCP-to-analysis composition. It does not change the shared evidence envelope, create a product-owned MCP transport, or authorize company sources.

## Current contract boundary

The accessible P1 host returns `AnalysisResponse` with `product_id`, `source_preview`, `evidence`, and `spatial_map`, then passes `evidence` and `source_preview` directly to the P4 headless panel. The P4 MCP workflow returns a schema-valid P4 evidence envelope and is synthetic-only. Its current official-SDK workflow has independent transport-to-analysis tests, and `tests/fixtures/mcp_p4_panel_bridge.json` is generated from that workflow and rendered by the P4 component tests.

The current P1 `POST /api/analyze/p4` lifecycle accepts only a local fixture identifier and demo scenario. It does not invoke the MCP acquisition workflow. The browser's successful synthetic run therefore verifies the P1 shell plus the P4 analytical module, while the MCP-backed UI fixture verifies the adapter-to-panel contract. They are not represented as one deployed MCP request.

## Additive P1 service behavior

1. P1 continues to own routing, authentication, authorization context, source selection, request IDs, cancellation, audit visibility, evidence export, and the shared response envelope.
2. The browser submits an analysis intent and time range. It must not submit trusted source IDs, tool names, semantic versions, permission scopes, credentials, or an `INTERNAL_AUTHORIZED` flag.
3. P1 resolves the source selection and permission context from administrator-governed Fab Insight MCP configuration. P1 constructs the bounded, read-only logical request and invokes the configured official-SDK adapter. The site supplies and qualifies the exact tool/source/relationship semantics; no P4 defaults are added.
4. P1 passes the returned semantic catalog and exact approved mappings to the P4 MCP workflow. The workflow validates versions, units, population, relationship endpoints, grain, time limits, row bounds, exact audit scope/source receipts, and metric-to-target mappings before analysis. Invalid or denied evidence returns `REFUSED` or `INCONCLUSIVE`; the UI withholds findings.
5. P1 constructs `source_preview` only from the validated semantic response and permission state. It must not infer source permissions, engineering populations, metric meaning, or units from the analysis output. The response is the existing `AnalysisResponse`: P4 evidence envelope, verified source preview, and `spatial_map: null`.
6. P1 binds its request abort/cancel lifecycle to the adapter. A cancellation before read prevents acquisition; a cancellation after read records the audit receipt, attempts the configured server cancellation, and withholds analysis. No route may write recipes or equipment settings.

## Synthetic qualification acceptance

Before internal configuration, P1 should add a mock-only host scenario that uses the existing official SDK test server and verifies:

- Successful acquisition, normalization, all D01–D05 dossier sections, source hashes and audit receipt through `POST /api/analyze/p4` and into the P1-hosted P4 panel.
- Denied permission, unapproved or drifting semantic/relationship contracts, wrong source version, wrong audit scope, duplicate audit sources, malformed join/grain, out-of-window events, row-limit overflow, connection failure, and cancellation before/after read.
- The source preview is based on the validated semantic response; the shared evidence schema remains unchanged.
- Refused results show a useful reason and no positive claims, D01–D05 findings, charts, or fixture values.
- Existing P1 frontend/route tests and the P4 MCP-to-panel fixture tests pass without a P4-owned shell or a second visualization runtime.

The new P4-side synthetic bridge currently verifies evidence schema validation, exact source fingerprinting, 900-row analysis, all five D01–D05 sections, the shared P1 chart callback/accessibility table, and permission-refusal suppression. It is not a substitute for the P1 host route described here.

## Internal qualification gate

The adapter remains `SYNTHETIC_TEST_ONLY` in the current P4 workflow. Before any real endpoint is reachable, P1/Fab Insight administrators must provide and qualify actual source IDs, tool mappings, semantic and relationship versions, permissions, host/network policy, audit/cancel semantics, and target environment. Security/legal/production review and engineer acceptance remain separately required. No such information is included in this proposal or repository fixture.
