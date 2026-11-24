# P4 platform qualification matrix

| Environment | Status | Qualification boundary |
|---|---|---|
| macOS ARM64, CPython 3.11.7 | Verified | Standalone core/UI, no-network extraction, optional pinned MCP SDK, synthetic stdio and Streamable HTTP. |
| macOS ARM64, CPython 3.12–3.14 | Support candidate; locally requalified only if final report records each run | Standard-library core/UI only. MCP SDK installation is unsupported without a matching staged wheelhouse. |
| macOS ARM64, CPython 3.10 | Supported by source declaration, not verified here | Standard-library core/UI only; no qualified MCP SDK bundle. |
| macOS Intel, Windows, Linux | Supported-by-design candidate; unverified | No target-host, browser, filesystem, or OS egress qualification evidence is available. |
| Any platform without a matching offline MCP SDK bundle | MCP integration unsupported | Core analysis and standalone local UI may still run if Python >=3.10 and a local browser are available. |

This is not universal offline compatibility. Company target OS, approved OpenCode build, internal network policy, local model, browser policy, and platform-specific SDK wheels require site qualification.
