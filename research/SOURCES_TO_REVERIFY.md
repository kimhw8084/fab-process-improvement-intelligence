# Research candidates to inspect during substantive implementation

These are technology leads from November 22, 2026 research. They are not installed, not guaranteed compatible, and are not independent proof of Samsung performance.

- Existing Fab Insight MCP and approved internal OpenCode/LLM are required integration points (actual company interface unknown).
- P1: DuckDB, Pandera, statsmodels, ruptures, River; first compare simple deterministic baselines.
- P2: NetworkX, CORE-T (research software), schemagraph (MCP-native but unqualified), ocel-mine (MIT engine; distinguish companion UI license), Splink/Valentine if data reconciliation is actually required.
- P3: scikit-image, PySAL/esda, scikit-learn, wafermap rendering (check maintenance/compatibility), conditional statistical models.
- P4: statsmodels, DoWhy, OR-Tools, Ax, BoTorch, MAPIE, PyMC, pymoo; do not blindly vendor them all.
- Packaging/security: Syft, Grant, Grype with locally supplied DB, uv/pip wheelhouses, pnpm offline store, MCP Inspector, Inspect AI as qualified.

**License and maturity traps noted in prior research:** AGPL libraries and ELv2/BSL source-available libraries are not automatically acceptable under the user's permissive-OSS preference. Public repo README claims are insufficient; verify actual release/commit and transitive dependency tree.

Potential upstream authoritative Golden Agentic Engineering reference previously discussed: `kimhw8084/golden-agentic-engineering` at commit `dc2ece864b2d744e47dfe8c7d9ad78aadbed369e`. This ZIP does not contain its source or establish that this is the full canonical standard. Use only if legitimately accessible, independently verify exact commit and avoid requiring any external network at deployment.
