# Orchastrator (Closed-Loop Orchestrator)

Implements the closed-loop orchestrator that coordinates:
- `ckg-augment` (CKG candidate generation)
- `debug-engine` (agent report generation)
- `judge` (scoring)

This package starts with **dry-run** support to validate the filesystem contract
and stopping logic without requiring Neo4j or API keys.

## Dry-run (Test 2)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q orchastrator/tests
python -m orchastrator.cli run --dry-run --run-id demo_run --max-iters 1
```

Artifacts are written under `output/closed_loop_runs/run_<run_id>/iterations/iter_XXXX/...`

