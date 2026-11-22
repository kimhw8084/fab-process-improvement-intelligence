# Four concurrent Codex worktrees: zero drift integration protocol

Initialize four independent **fresh directories/worktrees** from the corresponding ZIPs. Shared schemas and `contracts/SHARED_ARCHITECTURE.md` must have identical checksums. P1 is integration owner; no product may overwrite another's namespaced source. No session waits for a sibling to start its own engineering work.

Before product work, each agent runs `python bootstrap_check.py`; it prints the shared contract fingerprint and tests. Freezing happens NOW in these four ZIPs, not after one agent invents it. Shared changes require `/proposals/` RFC, semver version bump, compatibility tests and agreement in merger/integrator branch; until adopted, build against v1.

Product release artifact must include `product.json` (stable manifest), an evidence-schema-conforming sample output, deterministic CLI/API entrypoint, UI contribution metadata, dependency lock and licensing inventory, test evidence, `RELEASE_GATE_REPORT.json`, and exact source hashes.

Integration checker compares: contract version, exact shared-schema hash, unique product IDs and routes, manifest/API compatibility, no conflicting tool/port ownership, all product gates, actual offline dependency compatibility, end-to-end cross-product sample cases, and global permissions/UI/recovery. P1 runs assembler only when other product artifacts are accessible; P1 cannot claim suite ready when sibling outputs are absent.

Cross-product interactions should be through explicit references to immutable evidence IDs and approved semantic IDs, not copying entire data catalogs or raw data between independent stores. Shared views can deep-link into another product's investigation with a scoped source reference subject to authorization.
