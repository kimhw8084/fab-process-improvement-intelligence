# Codex execution rules — Fab Intelligence launchkit

Read **GOAL.md**, **docs/PRODUCT_SPEC.md**, **docs/SCIENCE_AND_METHODS.md**, **docs/TEST_AND_RELEASE_MATRIX.md**, **contracts/SHARED_ARCHITECTURE.md**, and **requirements/AUTHORITY_AND_GAPS.md** before modifying software. These are in the ZIP: no earlier conversation or repo history is assumed.

## Continuation and zero-routine-handoff contract
- This is a persistent *product delivery* task, not a request for a design plan. Work autonomously through research → implementation → oracle testing → adversarial testing → benchmarking → independent audit → offline distribution → release evidence.
- Never stop for ordinary design choices, library selection, finding/reproducing bugs, unclear implementation details, test-fixture creation, UX decisions, refactoring, or documentation. Resolve them with grounded engineering judgment and record the decision and evidence.
- If an external environment-specific requirement is inaccessible (actual company MCP credentials, approved table mappings, OS, real manufacturing data), complete every externally achievable task; keep the unmet internal qualification gate explicitly marked **PENDING_INTERNAL**, and produce automated site-side discovery / verification rather than asking now.
- If a truly release-critical external dependency cannot be satisfied from any authorized path, do not fake success or repeatedly bounce the issue to the user. Record a single evidence-backed limitation, a compliant alternative attempted, complete unaffected work, and stop only after no authorized work remains.
- Never treat success claims from a language model as proof. Inspect files, run programs, read outputs, compare with independent oracles, and save test artifacts.
- Avoid infinite unmeasurable 'improvement': release only after *all measurable external gates* pass, no known critical bugs remain, and additional explored alternatives lack credible net gain on the preset acceptance measures.
- Respect permissions, read-only data, company-transfer rules, license terms, corporate security, and human governance even if they appear to slow development.

## Parallel execution
This ZIP is **one independent worktree for one product**. All ZIPs contain byte-identical shared contracts. Own only your namespaced product, tests, product docs and artifacts. Changes to shared contracts require a versioned RFC + migration tests, not unilateral edits.
P1 is the integration assembler owner, not sole owner of common contract content. P2/P3/P4 must finish independently even if integration branches cannot yet be read.

## Efficient implementation strategy
1. Run `python -m unittest discover -s tests -v`, `python -m fabintel demo`, and `python bootstrap_check.py` to inspect the initial runnable scaffold.
2. Write an evidence-backed gap analysis against the product acceptance matrix. *Do not mark the product complete because these bootstrap tests pass*.
3. Prioritize a full vertical slice using the existing scaffold (read-only mock data → validated analysis → evidence schema → simple UI → export → independent test).
4. Expand all capabilities while reusing stable typed interfaces. Compare deterministic baselines first; adopt mature OSS only when justified with a pinned/offline/qualified dependency tree.
5. After every feature, add failure/abstention tests before happy-path expansion. Replay end-to-end user stories and preserve source provenance.
6. Qualify the offline build on the actual chosen OS/arch; qualify each claimed target separately; produce source/dependency inventories and all transfer artifacts.
7. Build internal qualification tooling; do NOT simulate its acceptance or infer company-specific MCP tool names.
8. Re-run fresh extraction tests, full audit, security tests, performance benchmarks, and produce machine-readable `RELEASE_GATE_REPORT.json`.

## Engineering scope and safety
Manufacturing engineers only. P1 statistical evidence; P2 actual process/exposure relationships; P3 wafer spatial/quality evidence; P4 advisory process improvement. No equipment commands, recipe writes, changes to manufacturing systems, uncontrolled network calls, cloud inference fallback, invented SQL joins, unsupported causal claims, or synthetic outputs mislabeled as company results.
