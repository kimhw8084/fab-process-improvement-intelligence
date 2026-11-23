# Golden reusable engineering method reference

P4 pins [golden-agentic-engineering](https://github.com/kimhw8084/golden-agentic-engineering) at `dc2ece864b2d744e47dfe8c7d9ad78aadbed369e` (`0.1.0-dev`). The selected source files are copied under `research/golden-agentic-engineering/source/`; `SOURCE_MANIFEST.json` records their SHA-256 digests. The upstream MIT license is included beside the source snapshot.

Golden is a reusable development-method foundation, not a P4 runtime or a qualified company standard. This version is explicitly `PRE_QUALIFICATION`: `standards/rules.json` declares 19 rule descriptors, while wider requirements remain unimplemented or not independently verified. A passing local fixture or Golden command does not qualify P4, an internal host, or company authorization.

The Codex adaptations live in `.agents/skills/`. OpenCode-compatible project copies live in `.opencode/skills/`; the unmodified upstream skill sources remain in the pinned snapshot for exact comparison. Only the seven applicable methods are included: routing, code audit, manufacturing analytics, React suite modules, MCP, offline dependency handling, and release qualification. NiceGUI was evaluated and not selected as a product stack.

The P4-specific Golden evidence is recorded at `qualification/evidence/golden-reference-checks-2026-11-22.json`. It captures `doctor` and `check --fast` from the pinned executable snapshot and verifies the presence of P4-relevant route definitions. The full route resolver is not vendored because it requires unrelated generic OpenCode agents and skills. Golden's full check, upstream fixture suite, Windows/Linux behavior, and target qualification have not been run here; the fast output is explicitly not release qualification.
