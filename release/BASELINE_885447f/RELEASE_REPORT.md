# P4 independent local candidate qualification

- Source commit: `885447fdea4da45b26a8b35ddf1841b0341153f4`
- Candidate: `release/FAB_INTELLIGENCE_P4_CANDIDATE.zip`
- SHA-256: `ba7ef4fea8847f1563963772275dea3f0940737ea06fd421a97f464f33ff67ec` (9,378,600 bytes; 236 source files)
- Source manifest SHA-256: `05297a68ced626b4826bb2c5ce4f9d74b52ffdebd1cc7cbd9bc4449565876bd4`
- Rebuilds: 2 detached clean-source builds matched byte-for-byte.
- Fresh install: PASS, no pip; macOS sandbox denied network access.
- Regression: 275 Python tests passed; 0 skipped.
- Gates: E01–E04, E06, and E10 PASS; E07 PASS_LIMITED_SCOPE for P4 standalone Chromium workflow.
- D01–D05 synthetic states: VALID, VALID, LIMITED_SCOPE, PROPOSED, ESTIMATED.

P4 is a standalone advisory product. The real MCP path was tested only with synthetic fixtures; its profile remained `PENDING_INTERNAL`. Company permissions/semantics, approved target OS, formal accessibility and security/legal review, and engineer ROI remain pending. **No public push or distribution authorization.**
