# Release gate verification and status policy

Statuses:
- `BOOTSTRAP_ONLY`: source scaffold, examples, or incomplete scientific/OS tests. **All four launch ZIPs start here.**
- `CANDIDATE`: complete feature code but some external acceptance evidence missing.
- `EXTERNAL_TRANSFER_READY`: full external scientific, security, license, UI, supply chain, offline and target-OS evidence passed; no known release-critical defects. Actual company qualification separately pending.
- `PENDING_INTERNAL`: a real company-only check not run. Never mask it with synthetic data.
- `READY_INTERNAL`: only after authorized internal MCP/model/data, policy, permissions, and engineer acceptance checks genuinely pass.

Mandatory external gates E01–E12:
E01 verified integrated product-specific end-to-end engineer workflows; E02 all independent scientific positive oracles; E03 all mandatory negative/refusal/unsafe cases; E04 versioned schema and frozen shared integration contract; E05 correct permissions, limited source reads and full provenance; E06 model-off or invalid-model operation safe; E07 UX accessibility / interaction checks; E08 target-OS offline install and egress-block runtime; E09 direct/transitive licensing, SBOM and current-db vulnerability review; E10 reproducible archive, hashes, rollback, kill switch; E11 measured task-level performance vs deterministic baseline and documented thresholds/hardware; E12 complete internal preflight and first-run guide, no false claims or fake table mappings.

External tests must record command, commit/source checksum, hardware/OS, independently prepared expected answer, actual result, log/fixture hash, status and artifact path. An empty/unexecuted test or agent assertion is NOT evidence. For safety/false join/geometry/causal gates, any known critical negative escape fails the release. Usability and numeric thresholds must be precommitted from meaningful baseline/study, not fabricated percentages. No quantitative Samsung ROI claim from synthetic data.

Suggested machine-readable `release/GATE_REPORT.json`:
`{ "state":"BOOTSTRAP_ONLY", "evaluated_commit":null, "gates":{"E01":{"status":"NOT_RUN","evidence":[]},...},"internal":{"state":"PENDING_INTERNAL","unverified":[]},"known_critical_defects":[] }`.
Always regenerate this file from actual test evidence, not manually set all states to pass. Include independent audit run by a distinct test harness; avoid an LLM being the only reviewer.
