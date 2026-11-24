# P4 internal-candidate install, stop, and rollback

## Offline install

1. Verify `P4_INTERNAL_TRANSFER_CANDIDATE.sha256` beside the archive, then extract into a new, isolated directory.
2. From that directory run `python qualification/first_run.py --output qualification/first-run.json` and `python -m fabintel doctor`. The core scientific engine, CLI, and local UI use the Python standard library and bundled local HTML/CSS/JavaScript/SVG assets; no `pip` or network is needed.
3. MCP integration is optional and platform-specific. Only macOS ARM64 CPython 3.11 has a bundled qualified SDK closure. Install it with `python -m pip install --no-index --require-hashes --find-links vendor/mcp-sdk/2.3.0/macos-arm64-cp311/wheelhouse -r vendor/mcp-sdk/2.3.0/macos-arm64-cp311/requirements.lock`. Other targets stay on local-only mode until matching wheels are staged and qualified.

## Stop and rollback

Run the UI in the foreground with `python -m fabintel serve` and stop it with Ctrl-C. Shutdown cancels active analysis jobs and closes the listener. To roll back, stop the process, restore the separately backed-up owner-reviewed config, and restart without `--mcp-config`; delete only the isolated extraction directory if removing the candidate. No service, persistent database, recipe writer, or equipment-control path is installed.

The final candidate is not transfer-authorized. Site owner permissions, semantic mappings, host policy, legal/security approval, and real manufacturing qualification remain pending.
