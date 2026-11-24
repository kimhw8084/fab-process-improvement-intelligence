# Offline qualification method

`qualification/qualify_final_transfer.py` takes the final ZIP and adjacent SHA-256 sidecar, verifies the exact archive, safely extracts it into a new temporary directory, validates the embedded source manifest and release manifest, then runs a no-pip core workflow. It also performs local pinned MCP SDK installation, synthetic transport tests, local Chromium workflow checks, and start/stop/restart checks. The caller's OS must enforce egress denial; the P4 application does not supply a sandbox.

Run under the approved host's OS network-deny policy:

```bash
python qualification/qualify_final_transfer.py release/final/P4_INTERNAL_TRANSFER_CANDIDATE.zip \
  --python <approved-python> --report release/final/ARCHIVE_QUALIFICATION.json
```

The archived core is Python standard-library-only and has no P1/P2/P3 runtime dependency. The optional official MCP SDK closure is qualified only for macOS ARM64 CPython 3.11 against local synthetic peers. Browser assets come from the approved local browser installation. Company target OS, OpenCode build/model, OS egress rules, and real MCP source permissions remain pending internal verification.
