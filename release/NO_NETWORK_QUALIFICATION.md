# No-network install/runtime qualification

## Exact artifact and scope

The authoritative source commit, ZIP SHA-256, source-manifest digest, install result, analysis result, and socket-denial probe for the latest local candidate are recorded in `OFFLINE_QUALIFICATION.json` and `BUILD_REPRODUCIBILITY.json`. Those values must match the adjacent archive and checksum sidecar; this note does not qualify a different ZIP. The local run uses only synthetic data and contacts no company endpoint.

## Procedure

`qualification/offline_qualify.py` extracts the supplied ZIP into a fresh temporary directory, verifies the SHA-256 sidecar and packaged source manifest, creates a virtual environment with `with_pip=False`, then runs `doctor`, `demo`, full D01–D05 analysis, and a socket-denial probe. The caller's OS must enforce the network block; P4 does not provide a sandbox.

The qualified local-host invocation is:

```bash
sandbox-exec -p '(version 1)(allow default)(deny network*)' python qualification/offline_qualify.py release/FAB_INTELLIGENCE_P4_CANDIDATE.zip
```

## Boundaries

The product core uses the Python standard library only. The optional MCP SDK is a separate hashed wheelhouse, qualified only for its recorded macOS ARM64 / CPython 3.11 target against a synthetic loopback mock. This does not qualify live MCP endpoints or OS egress policy. The company-approved target OS/architecture, host, and network policy remain pending internal confirmation.

The suite UI is a headless P1-compatible React module tested with P1's local toolchain; this CLI qualification does not test or approve an integrated browser host.
