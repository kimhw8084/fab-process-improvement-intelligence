# No-network install/runtime qualification

## Candidate source

- Product implementation commit: `5eeab108522abee3230ad38393f52e34ce6fd0cb`
- Exact bundle source snapshot and ZIP checksum: recorded in the adjacent `release/RELEASE_REPORT.md`, `release/SOURCE_MANIFEST.sha256`, and `release/OFFLINE_QUALIFICATION.json`.
- The source manifest covers every packaged file. No company endpoint or dataset was used.

## Tested host

- OS: macOS 26.6.2 (Darwin 25.6.0)
- Architecture: arm64 (Apple M3 host)
- Python: 3.11.7
- Product runtime: Python standard library only; no package installation, wheels, JavaScript packages, remote fonts/scripts, CDN assets, analytics, or updater.
- Company-approved target OS/architecture: **not supplied; pending internal confirmation**.

## Exact procedure run

The qualification script extracts the exact ZIP into a fresh temporary directory, verifies the adjacent SHA-256 sidecar and all source-manifest entries, creates a virtual environment with `with_pip=False`, then runs `doctor`, `demo`, full D01–D05 analysis, and a socket denial probe. The caller OS must enforce the network block. The executed macOS command was:

```bash
sandbox-exec -p '(version 1)(allow default)(deny network*)' python qualification/offline_qualify.py release/FAB_INTELLIGENCE_P4_CANDIDATE.zip
```

## Result

**PASS** for the exact ZIP whose checksum is in the adjacent offline qualification record. Fresh extraction and source verification passed; the venv had no pip or third-party packages; doctor and demo returned the expected candidate/synthetic states; the 540-observation/60-lot D01–D05 dossier returned `VALID`; and the sandboxed socket probe returned `DENIED` (errno 1). The adjacent `OFFLINE_QUALIFICATION.json` records the exact ZIP SHA-256. `BUILD_REPRODUCIBILITY.json` records two clean detached-worktree builds at the package source snapshot and the source-manifest comparison.

The loopback browser is tested separately by `tests/test_offline_server.py` and the local browser walkthrough. This CLI/install qualification does not claim an isolated or approved company browser host. The result applies only to the recorded macOS/Python/arm64 host; company target compatibility and egress policy remain unqualified.
