# P4 architecture reuse decisions — 2026-11-22

## Method foundation

The development-method source is Golden commit `dc2ece864b2d744e47dfe8c7d9ad78aadbed369e`, version `0.1.0-dev`. Seven relevant skills are adapted for Codex and retained in OpenCode-compatible project form. The selected Golden sources and exact hashes are in `research/golden-agentic-engineering/`. Golden was exercised against P4; its `PRE_QUALIFICATION` status and incomplete rule evidence remain explicit. See `qualification/evidence/golden-reference-checks-2026-11-22.json`.

## UI and visualization

| Decision | Evidence and boundary |
|---|---|
| Primary stack: React + TypeScript panel | P1 already contributes a React 19.2 panel against `suite-ui-module.v1`. A local search found no reusable NiceGUI Base; Golden only has a small example. Choosing NiceGUI would add a second runtime and require a bridge to the P1 host. |
| P4 exports `P4Panel` only | The panel uses the P1 source preview and evidence envelope props, native semantic tables, and the shared chart-render callback. The suite host owns routes, shell, design tokens, request lifecycle, and renderer. No P4 shell or CSS system is shipped. |
| Visualization: host-owned ECharts candidate | P1's local fixture benchmark measured ECharts 6.1 at 785,840 minified bytes / 218,270 gzip and 1.11 s build versus Plotly.js at 1,651,750 minified bytes / 454,460 gzip plus 83,130 CSS and 1.37 s build. This is a single local build comparison, not a usability, accessibility, memory, OS, or release benchmark. The host must approve and qualify its selected renderer. |
| Tables: native semantic HTML | P1 selected native tables for result cohorts; the P4 grid defaults to 225 cells and is capped at 1,681. Tables preserve the full D02 classification and interval values. AG Grid Community would add a second table runtime without demonstrated need. |
| No Cytoscape.js | P4 currently exposes linked evidence in tables and does not require an interactive graph visualization. Relationship validation stays in deterministic data logic. |
| No Plotly runtime in P4 | P1's comparison favors ECharts on measured bundle/build size. P4 delegates charts to the host and keeps every plotted value inspectable in a table. |

The P1 contract snapshot used for offline validation is at `research/p1-suite-ui-reference/`. It has no P1 Git commit metadata and is explicitly not the host's final compatibility proof. P1's current schema restricts capability IDs to `A00` form while P4 declares `D01`–`D05`; P4 therefore leaves the new contribution's capability list empty rather than inventing aliases. D02 heatmaps and uncertainty interval marks are also outside `suite-chart.v1`; P4 uses an accessible table for the full scientific result and plots only the supported D03 two-objective scatter. Proposed P1-owned contract improvements are in `integration/proposals/CHANGE-001-suite-ui-contract.md`.

## MCP and semantics

The former P4 JSON-RPC/stdio/HTTP implementation has been replaced by the official MCP Python SDK candidate (`mcp==2.3.0`) for session negotiation, JSON-RPC, stdio, and Streamable HTTP. SDK calls are exercised against P4's realistic synthetic protocol peer over both transports. The P4 adapter retains only explicit transport configuration checks and mapping to the existing `adapter-operations.v1` logical contract; actual meanings, approvals, permissions, source identifiers, and relationships remain owned by the administrator-governed Fab Insight MCP.

The SDK and exact transitive hashes are an **optional** offline MCP extra. The bundled wheelhouse is only macOS ARM64 / CPython 3.11; Windows, Linux, other Python versions, current vulnerability closure, license/security approval, actual target host, and company MCP compatibility are not established. Core scientific analysis remains Python standard library only. P4's product UI consumes the host's JSON evidence envelope and does not duplicate a semantic service.

## Scientific engines and test/development infrastructure

P4 retains its deterministic engine and preserved held-out/refusal fixtures. Existing independent D01–D05 and OSS comparisons remain in their qualified scope; the SciPy, pyDOE3, scikit-optimize, and statsmodels comparisons are benchmark-only and do not become product dependencies. Reuse is accepted only where the fixed oracle demonstrates the improvement. The suite UI tests use the P1 React/toolchain as a test fixture; their versions and lock remain P1-owned.

The loopback HTTP server is retained as a synthetic integration fixture for engine jobs and cancellation, but no longer serves HTML and is not a deployable product backend. The retired standalone page is retained only as local legacy evidence and is excluded from the transfer bundle. The P4 production-facing interface remains the deterministic Python analysis function and CLI until the suite host is available.

## Integration ownership and unresolved checks

P1 owns `suite-ui-module.v1` and `suite-chart.v1`; P4 contributes `products/p4/ui/P4Panel.tsx`. P1's extracted local directory has no Git metadata and no integrated suite host was available, so host compilation, route mounting, shared ECharts execution, authentication, and target OS remain `NOT_RUN`/pending. P4 must not change P1-owned contracts locally. The minimal company-side step remains explicit: supply approved semantics, source/relationship contracts, logical-tool mapping, permissions and read limits; run a read-only qualification under documented authorization; then independently review provenance and engineer results.

Public distribution remains unapproved pending source ownership, license, company-information exposure, dependency vulnerability, and security review. No public push or external publication follows from these local changes.
