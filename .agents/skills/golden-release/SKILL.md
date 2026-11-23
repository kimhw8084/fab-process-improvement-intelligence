---
name: golden-release
description: Qualify the exact P4 artifact reproducibly while keeping external and company-only gates explicit
---

# P4 release qualification

1. Bind every result to an immutable source commit and exact archive SHA-256. Rebuild in a clean checkout and compare archive bytes, source manifest, and sidecar.
2. Run applicable independent checks and preserve `FAIL`, `NOT_RUN`, and `DEFERRED` items. Never convert missing evidence into readiness.
3. Verify offline operation, dependency/license inventory, vulnerability review, target OS, rollback, and suite integration independently.
4. Keep public distribution blocked pending ownership, licenses, company-information exposure, and security review. Do not publish or claim internal approval.
5. Keep actual source semantics, company authorization, target-host compatibility, and engineering ROI pending until evidence comes from an authorized real environment.
