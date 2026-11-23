---
name: golden-code-audit
description: Audit P4 architecture and release evidence using Golden statuses without overstating its pilot checks
---

# Golden code and release audit

1. Start from the applicable descriptors in `research/golden-agentic-engineering/source/standards/rules.json` and the Golden qualification matrix. Golden reports 19 rule descriptors in this pinned pre-qualification release; it does not enforce all 151 broader requirements.
2. For each release-critical condition record evidence, result, scope, and source hash. Use `PASS`, `FAIL`, `NOT_RUN`, and `DEFERRED` precisely. A missing dependency, host, vulnerability feed, or independent authority remains `NOT_RUN` or `DEFERRED`, never `PASS`.
3. Keep source inspection separate from execution. A static scan cannot establish server authorization, offline behavior, scientific validity, or user success.
4. Do not average away failures or pending gates. Preserve prior valid evidence, identify the exact failing check, repair the bounded cause, and rerun that check.
5. Never label P4 externally transfer ready while a release-critical gate remains open.
