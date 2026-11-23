---
name: golden-offline-toolchain
description: Stage and verify locked P4 dependencies with explicit platform and license boundaries
---

# Offline dependency handling

1. Pin source version and hashes before import. Keep the core analysis dependency-free; optional MCP SDK wheels are an explicit separate extra.
2. Audit every direct and transitive dependency, bundled license, vulnerability data freshness, platform binary, and runtime network behavior. A lock file is not license or security clearance.
3. A macOS ARM64 wheelhouse test supports only that interpreter and platform. Do not infer Windows/Linux or internal-host qualification.
4. Build from staged inputs with network denied, record exact dependency inventory, checksums, source commit, archive hash, and reproducible rebuild result.
5. Keep optional browser tooling out unless its binaries, licenses, egress behavior, and target OS are actually staged and tested.
