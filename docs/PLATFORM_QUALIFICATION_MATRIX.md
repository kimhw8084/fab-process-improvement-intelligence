# P4 platform qualification matrix

| Environment | Status | Qualification boundary |
|---|---|---|
| macOS ARM64, CPython 3.11.7 | **Verified candidate platform** | Exact archive: no-pip core, D01–D05, schema validation, no-internet denial, foreground startup/stop, synthetic-config to local-only rollback; 285-suite run (23 optional-SDK cases separately rerun); 29 offline MCP SDK tests; Chromium 158.0 workflow with no external browser requests. |
| macOS ARM64, CPython 3.12.9, 3.13.13, 3.14.5 | **Verified core only** | Exact archive no-pip first-run, D01–D05 workflow, no-internet denial, foreground startup/stop, and synthetic-config to local-only rollback. Full unit and browser suites were run under 3.11.7, not separately under these interpreters. Optional MCP SDK bundle is unsupported here. |
| macOS ARM64, CPython 3.10 | **Supported by source declaration; unverified** | Standard-library core only; no matching MCP SDK bundle or local interpreter was available for qualification. |
| macOS Intel, Windows, Linux | **Unsupported for this transfer candidate; unverified** | No platform-specific archive, host, browser, filesystem, or egress-policy qualification was performed. Do not deploy there on the basis of source portability. |
| Any platform without a matching offline MCP SDK bundle | **MCP integration unsupported** | Core analysis and standalone local UI may run only on a separately qualified Python/OS target. |

This is not universal offline compatibility or a company target-host approval. The verified platform rows describe this exact local candidate only. Company-approved OS, OpenCode build/local model, egress policy, and browser policy still require internal qualification.
