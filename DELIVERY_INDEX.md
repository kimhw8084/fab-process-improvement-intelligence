# P4 delivery index

This folder contains the P4 source, qualification resources, evidence, and a deterministic transfer ZIP.

## Start and run

- [START_HERE.md](START_HERE.md) — quick start, demo, and offline UI.
- [README.md](README.md) — product behavior and CLI/API entry points.
- [GOAL.md](GOAL.md) — supplied build specification.
- [product.json](product.json) — product manifest.
- [ui/index.html](ui/index.html) — local engineer interface.

## Scientific and product evidence

- [qualification/critical_cases.json](qualification/critical_cases.json) — P4-01 through P4-12 with executed test mapping.
- [fixtures/p4_independent_oracles.json](fixtures/p4_independent_oracles.json) — numeric oracle inputs and expected results.
- [tests/test_d01_d02_independent.py](tests/test_d01_d02_independent.py), [tests/test_d03_relationships.py](tests/test_d03_relationships.py), [tests/test_d04_designs.py](tests/test_d04_designs.py), [tests/test_d05_studies.py](tests/test_d05_studies.py) — independent scientific and refusal challenges.
- [release/TEST_RESULTS.json](release/TEST_RESULTS.json) and [release/TEST_LOG.txt](release/TEST_LOG.txt) — test summary and full log.
- [release/full_workflow_demo_evidence.json](release/full_workflow_demo_evidence.json) — synthetic D01–D05 dossier.
- [release/SCHEMA_VALIDATION.json](release/SCHEMA_VALIDATION.json) — schema validation results.
- [release/BENCHMARK_REPORT.json](release/BENCHMARK_REPORT.json) — host-specific latency, memory, and optional OLS reference comparison.
- [release/D04_OSS_COMPARISON.json](release/D04_OSS_COMPARISON.json) and [release/D04_OSS_DECISION.md](release/D04_OSS_DECISION.md) — seeded comparison with SciPy, pyDOE3, and scikit-optimize; qualification-only dependencies are pinned in [qualification/benchmark-requirements.txt](qualification/benchmark-requirements.txt).
- [release/DEPENDENCY_AUDIT.json](release/DEPENDENCY_AUDIT.json) — current `pip-audit` result for the optional qualification dependency tree. Source, OS/interpreter, ownership, and legal reviews are separate gates.

## Transfer and qualification

- [release/FAB_INTELLIGENCE_P4_CANDIDATE.zip](release/FAB_INTELLIGENCE_P4_CANDIDATE.zip) — candidate transfer archive.
- [release/TRANSFER_BUNDLE.sha256](release/TRANSFER_BUNDLE.sha256) — archive SHA-256.
- [release/SOURCE_MANIFEST.sha256](release/SOURCE_MANIFEST.sha256) — source file hashes.
- [release/OFFLINE_QUALIFICATION.json](release/OFFLINE_QUALIFICATION.json) — fresh extraction, no-pip, network-denied run against the exact archive.
- [release/BUILD_REPRODUCIBILITY.json](release/BUILD_REPRODUCIBILITY.json) — two-build reproducibility check.
- [release/GATE_REPORT.json](release/GATE_REPORT.json) — machine-readable candidate state and gate evidence.
- [release/INTERNAL_PREFLIGHT.json](release/INTERNAL_PREFLIGHT.json) — local first-run report; company qualification remains pending.
- [release/SBOM.spdx.json](release/SBOM.spdx.json) and [release/LICENSE_SECURITY_REVIEW.md](release/LICENSE_SECURITY_REVIEW.md) — dependency inventory and license/security review.
- [release/RELEASE_REPORT.md](release/RELEASE_REPORT.md) — final archive hash, commands, and qualification limits.
- [release/PUBLISHED_ARTIFACT_RECONCILIATION.md](release/PUBLISHED_ARTIFACT_RECONCILIATION.md) — verifies the prior d16ec28 artifact's Git blob and resolves its published SHA-256.

## Integration and operations

- [contracts/](contracts/) — frozen shared schemas and architecture contract.
- [fabintel/mcp_client.py](fabintel/mcp_client.py), [fabintel/mock_mcp_server.py](fabintel/mock_mcp_server.py), and [requirements/site-mcp-config.v1.schema.json](requirements/site-mcp-config.v1.schema.json) — configurable MCP transport, semantic mapping, test mock, and site-owned config contract.
- [docs/](docs/) — product, science, threat model, backlog, integration, and release requirements.
- [qualification/](qualification/) — offline builders, validators, benchmark, fixtures, and internal first-run runner.
- [release/RUNBOOK_ROLLBACK_KILL_SWITCH.md](release/RUNBOOK_ROLLBACK_KILL_SWITCH.md) — shutdown and rollback procedure.
- [release/UI_BROWSER_ACCEPTANCE.md](release/UI_BROWSER_ACCEPTANCE.md) — observed local browser walkthrough and pending accessibility scope.

Release state is **CANDIDATE**. Company authorization/source semantics, target-OS confirmation, formal accessibility/user baselines, distribution rights, and independent source security review remain open gates. Generated test/gate/offline reports and archive checksum/reproducibility records stay beside the transfer ZIP so no report is self-referential; the ZIP contains the product source, tests, schemas, requirements, and static qualification resources. No new public upload is authorized by this package state.
