### Goal
Implement a **self-optimizing iterative closed-loop runner** for a **single case** (e.g., case2) that:

- Starts from either:
  - **scratch** (empty CKG), or
  - a provided **base CKG** (e.g., “case1 resulting CKG”)
- Iterates up to `max_iters` (default 5)
- Stops early when:
  - **Root Cause Accuracy ≥ 9** AND **Overall composite ≥ 8**
- Stores artifacts per-iteration with **no overwrites**
- Produces final iteration’s **detailed judge comments**

Pipeline per iteration:
`ckg-augment → DebugAgent → judge.cli run → feedback_adapter → ckg-augment (next iter)`

---

### Requirements (V-model)

#### R1: Inputs
- `--data <path>`: data file containing **human report + prompt** separated by the `E2E Test Query` marker (same structure as `data/first`, `data/second`, `data/third`)
- `--case-id <caseX>`: `case1|case2|case3` (used in feedback and in `ckg-augment --case`)
- Start mode:
  - `--start-from-scratch` OR `--base-ckg <path>` (mutually exclusive)

#### R2: Iteration limits / stopping
- `--max-iters` default 5
- `--stop-accuracy` default 9
- `--stop-overall` default 8
- Stop when: \(accuracy \ge stop\_accuracy\) AND \(overall \ge stop\_overall\)

#### R3: Artifacts (no overwrites)
Write under:
`output/closed_loop_runs/run_<run_id>/case_XX/iterations/iter_XXXX/{ckg,agent,judge,feedback}/...`

Inputs snapshot under:
`output/closed_loop_runs/run_<run_id>/inputs/...`

The runner must raise if `run_<run_id>` already exists.

#### R4: Feedback wiring
- Judge output (`judge.cli run`) → `orchastrator.feedback_adapter` → feedback JSON consumable by `ckg-augment --feedback`
- Next iteration uses:
  - previous candidate CKG as base
  - previous feedback JSON as `--feedback`

#### R5: Dry-run mode for deterministic tests
- `--dry-run` must avoid external services (OpenAI, Neo4j)
- It must still write the full artifact bundle and iterate deterministically.

---

### Implementation (files)

- **Runner**: `orchastrator/case_loop.py`
  - exports a library function `run_case_loop(...)` (testable)
  - provides CLI: `python -m orchastrator.case_loop ...`

---

### Dry-run design (for tests)
In `--dry-run`:
- Generate a minimal synthetic CKG JSON each iter
- Generate a placeholder agent report
- Generate a synthetic judge JSON with:
  - Root Cause Accuracy score and composite score controlled by a parameter (e.g. `--dry-run-stop-iter`)
- Convert judge → feedback via `feedback_adapter` and keep iterating until stop or max_iters.

This gives deterministic unit/integration tests without OpenAI/Neo4j.

---

### Verification plan (V-model)

#### Unit / contract tests (orchastrator)
- **T1: No-overwrite**
  - If run dir exists: raise `FileExistsError`
- **T2: Stop criteria**
  - If dry-run produces accuracy=9 and overall=8 at iter_1: stop at iter_1
- **T3: Iteration progression**
  - With `--dry-run-stop-iter 3` and `max_iters=5`: should create iter_0001..iter_0003 only
- **T4: Base CKG selection**
  - With `--base-ckg`: ensure snapshot is copied and iter_0001 candidate derives from that
  - With `--start-from-scratch`: snapshot is canonical empty

#### Proof
Run:
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q orchastrator/tests`

