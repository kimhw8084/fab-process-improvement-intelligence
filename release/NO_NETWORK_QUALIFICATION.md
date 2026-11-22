# No-network install/runtime qualification

## Candidate build host

- OS: macOS 26.6.2 (Darwin 25.6.0)
- Architecture: arm64 (Apple M3 host)
- Python: 3.11.7
- Runtime dependencies: Python standard library only; no vendored wheels, JS packages, fonts, CDN assets, analytics, or updater.
- Company-approved target OS/architecture: **not supplied; internal confirmation pending**.

## Reproducible check procedure

`qualification/offline_qualify.py` extracts the checked ZIP into a fresh temporary directory, creates a venv with `with_pip=False`, verifies the included source manifest and the adjacent transfer-checksum sidecar, and runs doctor/demo/analysis inside that environment. The socket probe confirms that the caller's OS sandbox denies network access. Run it under macOS `sandbox-exec` with `network*` denied:

```bash
python qualification/build_transfer_bundle.py
sandbox-exec -p '(version 1)(allow default)(deny network*)' python qualification/offline_qualify.py release/FAB_INTELLIGENCE_P4_CANDIDATE.zip
```

The Python service's browser interaction uses loopback. The network-denied CLI/install qualification does not claim a network-isolated browser host. A separate local HTTP UI and cancel flow is covered by `tests/test_offline_server.py`; current-target site egress policy remains an internal gate.

## Current result

The exact archive is qualified after assembly with a fresh extraction and a venv created without pip. The resulting `release/OFFLINE_QUALIFICATION.json` is kept beside the ZIP in the project folder so it can include the ZIP's own SHA-256 without creating a self-reference. Its result applies only to the recorded OS, Python build, and CPU architecture; the company target remains unqualified until confirmed and tested.
