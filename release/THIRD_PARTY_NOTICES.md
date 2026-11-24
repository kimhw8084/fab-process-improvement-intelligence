# P4 third-party notices and transfer-rights assessment

P4's offline core and local UI use Python/browser standard capabilities and bundled first-party HTML, CSS, JavaScript, and SVG. The product loads no remote assets. The optional official MCP Python SDK 2.3.0 and its 28-wheel macOS ARM64/CPython 3.11 closure are in `vendor/mcp-sdk/2.3.0/macos-arm64-cp311/`; exact wheel and embedded license-file hashes are recorded in that directory and the SPDX SBOM. Three SDK dependency metadata entries lack SPDX expressions and require legal interpretation.

Qualification/reference packages are pinned in `qualification/benchmark-requirements.txt`. The exact resolved packages, raw license metadata, and license-file hashes are documented in `release/QUALIFICATION_DEPENDENCY_LICENSE_INVENTORY.json`; they are not required or bundled as P4 runtime dependencies. The pinned Golden development-method snapshot has its own MIT notice. Its license is not a grant for P4 first-party work.

The P4 source supplies no first-party license, copyright/ownership record, trademark grant, or redistribution authorization. The SPDX record uses `NOASSERTION`. This inventory is evidence for review, not legal interpretation or approval. A company legal/IP owner must establish ownership and authorize transfer before internal or external distribution.
