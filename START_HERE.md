# Run P4 locally

This folder is a self-contained **CANDIDATE**, not an approved manufacturing system. Python 3.10+ and its standard library are the only runtime dependencies. The demo fixture and every result are synthetic.

## Command line

From this directory:

```bash
python bootstrap_check.py
python -m fabintel doctor
python -m fabintel demo
python -m fabintel analyze --input fixtures/full_workflow_demo.json --output decision-dossier.json
python -m fabintel preflight
```

`python -m fabintel preflight --report PATH` checks the shape of a supplied capability snapshot against the frozen *logical* adapter contract. It does not connect to or certify the real MCP.

## Offline engineer UI

```bash
python -m fabintel serve
```

Open the loopback address printed in the terminal. The service binds only to `127.0.0.1`; it reads no external assets, makes no outbound calls, and keeps request data in process memory. Use **Load synthetic walkthrough**, inspect the request, run the dossier, and export the evidence JSON. `Ctrl-C` cancels active analyses and stops the server.

## Included resources

- `products/p4/engine.py`: deterministic analysis engine.
- `products/p4/investigation.v1.schema.json`: P4 request shape.
- `contracts/`: unchanged shared v1 evidence and adapter contracts.
- `fixtures/full_workflow_demo.json`: synthetic end-to-end D01–D05 example.
- `fixtures/p4_independent_oracles.json` and `tests/test_p4_scientific.py`: independent numeric and adversarial cases.
- `qualification/`: reproducible demo generator, first-run preflight checker, benchmark protocol, and challenge catalog.
- `ui/index.html`: bundled local engineer interface.
- `release/`: gate report, build/install/rollback instructions, SBOM, security/license findings, hashes, and transfer archive when built.

An engineer or authorized site owner must complete the internal steps documented in `docs/INTERNAL_COMPANY_FIRST_RUN.md`. No actual internal source mapping, permission, or company approval is included here.
