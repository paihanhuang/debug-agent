# Closed-Loop Implementation Plan (Per-Case Iteration, OpenAI, No Overwrites)

This document is the **complete implementation plan** for wiring the closed-loop system using:
- `ckg-augment/` (candidate CKG generation; supports `--init-empty` and `--feedback`)
- `debug-engine/` (report generation; GraphRAG + Neo4j + OpenAI)
- `judge/` (evaluation; OpenAI provider)
- `orchastrator/` (state manager and loop runner)

**Key requirement:** run the loop in **per-case iteration mode** (case1/case2/case3 each refined independently).

---

## Implementation Plan: Real Closed-Loop Iteration (OpenAI, No Overwrites) — V-Model

This section is the **step-by-step wiring plan** to execute a real iteration (`iter_0001`) end-to-end and then evolve into feedback-driven iterations (`iter_0002+`), while preserving the no-overwrite and per-case requirements.

### Requirements (Definition of Done)

#### Functional
- Orchestrator can run **one real iteration** per case (`iter_0001`) that:
  - Generates a candidate CKG at an **iteration+case specific path**
  - Runs debug-engine E2E using that candidate via **CKG path injection**
  - Runs judge batch using **OpenAI** (`--provider openai`)
  - Writes all artifacts under `output/closed_loop_runs/run_<run_id>/case_XX/iterations/iter_0001/...`
  - Writes `feedback_iter_0001_case_XX.json`
  - Evaluates stop criteria **per case**: accuracy ≥ 9 AND overall > 8

#### Non-functional
- No file overwrites:
  - Orchestrator refuses to reuse `run_<run_id>`
  - Orchestrator does not overwrite `assets/ckg/full_ckg.json`
  - All outputs include `iter_XXXX` and `case_XX` in filenames

### Design rationale (why these choices)
- **CKG path injection via E2E harness** is the smallest safe change that enables per-iteration CKG evaluation without destabilizing debug-engine internals.
- **Per-case iteration** reduces cross-case interference (each case refines toward its own ground truth).
- **Judge provider explicit** (`openai`) removes ambiguity and avoids accidental Anthropic fallback.
- **Iter_0001 is a baseline** for each case; `iter_0002+` introduces feedback as the controlled change driver.

---

### Step-by-step implementation (V-Model)

#### Step 1 — Specify the runtime contract between orchestrator and debug-engine
- Add env var contract:
  - `CKG_JSON_PATH`: path to CKG JSON that debug-engine should load for the current E2E run
- Behavior:
  - If set: use it
  - If not set: preserve current default behavior

**Verification**
- Minimal smoke run:
  - `CKG_JSON_PATH=assets/ckg/full_ckg.json python tests/test_e2e_production.py`

#### Step 2 — Implement CKG path injection in debug-engine E2E (minimal code change)
- Modify `tests/test_e2e_production.py`:
  - Read `CKG_JSON_PATH` with fallback
  - Use it as the source CKG JSON for Neo4j loading / retrieval initialization

**Verification**
- Run with and without `CKG_JSON_PATH` set; both should succeed.

#### Step 3 — Orchestrator: implement non-dry-run execution (per-case, iter_0001 only)
Add orchestrator execution mode that runs:
1) `ckg-augment` to produce `candidate_ckg_iter_0001_case_XX.json`
2) debug-engine E2E with `CKG_JSON_PATH=<candidate>`
3) `judge.cli batch --provider openai`
4) capture artifacts into the iteration folder
5) generate `feedback_iter_0001_case_XX.json`
6) evaluate stop criteria for that case

**Design note:** `judge.cli batch` evaluates all 3 cases; orchestrator must select the result matching `case_XX` and store only the per-case files in that case folder.

**Verification**
- Run orchestrator for a single case and `max-iters=1`:
  - Assert all expected artifacts exist under that case/iter folder
  - Assert the per-case judge report JSON contains only that case (or is a filtered/copy)

#### Step 4 — Enforce no-overwrite and deterministic artifact naming
- Orchestrator must:
  - fail fast if `run_<run_id>` exists
  - copy agent outputs into case/iter folder using:
    - `agent_report_iter_XXXX_case_XX.md`
  - copy or generate per-case judge outputs using:
    - `judge_qa_report_iter_XXXX_case_XX.json`
    - `judge_qa_summary_iter_XXXX_case_XX.json`

**Verification**
- Run two separate `run_id`s; confirm both preserved.
- Attempt same `run_id`; confirm orchestrator raises error.

#### Step 5 — Implement feedback-driven iteration (iter_0002+)
For each case independently:
- Use the previous iteration’s feedback:
  - `--feedback feedback_iter_0001_case_XX.json`
  - `--case caseX` (case1/case2/case3)
- Generate:
  - `candidate_ckg_iter_0002_case_XX.json`
- Repeat debug-engine + judge, then re-evaluate stop criteria.

**Verification**
- Confirm `augmentation_diff_iter_0002_case_XX.json` includes `feedback_added_entities` changes when missing elements are present.
- Confirm judge scores change across iterations (even if modest).

---

### Verification plan (what to test and when)

#### Unit tests (fast, deterministic)
- Extend orchestrator unit tests to:
  - mock command runner
  - assert correct command sequence and env vars (especially `CKG_JSON_PATH`)
  - assert correct destination filenames include iter+case
  - assert stop logic per case (accuracy ≥ 9 and overall > 8)

#### Dry-run integration (contract validation)
- Extend orchestrator dry-run integration to per-case mode:
  - run for cases 01..03
  - produce per-case iteration folders and feedback files
  - ensure no overwrite behavior

#### Real integration (gated)
Prereqs:
- `OPENAI_API_KEY`
- Neo4j reachable (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)

Run:
- `max-iters-per-case=1` for each case to validate wiring
- Then enable iter_0002 for one case to validate feedback loop effect

---

## 0) Goals & Constraints

### Goals
- For each case (01..03), iteratively refine a candidate CKG until:
  - **Root Cause Accuracy >= 9** AND
  - **Overall (composite) > 8**
- Preserve full history of artifacts:
  - Every file name includes **iteration number** and **case number**
  - No old files are overwritten

### Constraints
- Use existing implementations in `debug-engine/` and `judge/` (minimal changes only to support CKG path injection).
- Use **OpenAI** for both debug-engine and judge.
- Support **start from scratch** (no base CKG) per case.

---

## 1) Per-Case Loop Definition (Behavioral Contract)

### Case set
- case_01 uses `data/first`
- case_02 uses `data/second`
- case_03 uses `data/third`

### Per-case iteration sequence
For each `case_XX`, the orchestrator runs iterations:
- `iter_0001` → baseline run
- `iter_0002..iter_N` → feedback-guided runs

**Stop criteria (per case):**
Stop iterating on a case when:
- average Root Cause Accuracy for that case >= 9 AND
- composite score for that case > 8

**Run completion (all cases):**
The overall run is “complete” when **all three cases** reach stop criteria OR their `max-iters` limit.

---

## 2) Artifact Storage Contract (No Overwrites)

### Storage root
- `output/closed_loop_runs/`

### Run folder
- `output/closed_loop_runs/run_<run_id>/`

### Per-case folders
- `output/closed_loop_runs/run_<run_id>/case_01/`
- `output/closed_loop_runs/run_<run_id>/case_02/`
- `output/closed_loop_runs/run_<run_id>/case_03/`

### Per-case iteration folder layout
For each case and iteration:
- `.../case_XX/iterations/iter_XXXX/`
  - `ckg/`
    - `candidate_ckg_iter_XXXX_case_XX.json`
    - `augmentation_diff_iter_XXXX_case_XX.json`
  - `agent/`
    - `agent_report_iter_XXXX_case_XX.md`
    - `production_comparison_iter_XXXX_case_XX.json`
  - `judge/`
    - `judge_qa_report_iter_XXXX_case_XX.json`
    - `judge_qa_summary_iter_XXXX_case_XX.json`
  - `feedback/`
    - `feedback_iter_XXXX_case_XX.json`

### Inputs snapshot
At run start:
- `output/closed_loop_runs/run_<run_id>/inputs/`
  - `human_report_case_01.txt`
  - `human_report_case_02.txt`
  - `human_report_case_03.txt`
  - `base_ckg_snapshot.json` (may be empty canonical snapshot in scratch mode)

**No-overwrite rule:**
- Orchestrator fails fast if `run_<run_id>` exists.
- Orchestrator never writes to `assets/ckg/full_ckg.json`.

---

## 3) Required Wiring Change: Debug Engine Must Accept CKG Path

### Requirement
`debug-engine` E2E must accept a CKG JSON path so the orchestrator can pass the iteration-specific candidate CKG.

### Contract
- New env var: `CKG_JSON_PATH`
- E2E harness (`tests/test_e2e_production.py`) uses:
  - `os.getenv("CKG_JSON_PATH", "assets/ckg/full_ckg.json")`

**Rationale**
This is the smallest change that enables “no overwrite” iteration bundles and supports scratch bootstrapping.

---

## 4) Orchestrator: Non-Dry-Run (Per-Case) Implementation Plan (V-Model)

### 4.1 Requirements & Spec
Add a new orchestrator run mode:
- `--provider openai` (judge provider)
- `--per-case` (default true)
- `--start-from-scratch` (if true, use `ckg-augment --init-empty`)
- `--max-iters-per-case <N>`

### 4.2 Test Design (before coding)

#### Test 1 (unit, already exists; extend)
- Mock command runner; assert commands are invoked in this order for each case/iter:
  1) `ckg-augment` with `--init-empty` (scratch) or `--ckg <base>`
  2) debug-engine E2E with `CKG_JSON_PATH=<candidate_ckg_iter_XXXX_case_XX.json>`
  3) `judge.cli batch --provider openai`
  4) copy artifacts into `case_XX/iterations/iter_XXXX/...` with correct filenames

#### Test 2 (dry-run integration, extend)
- Add orchestrator dry-run support for per-case folders:
  - It writes synthetic judge reports per case and per iteration
  - It writes `feedback_iter_XXXX_case_XX.json`
  - It enforces stop criteria per case

#### Test 3 (real integration, gated)
- Only runs if:
  - `OPENAI_API_KEY` set
  - Neo4j reachable (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)
- Run `max-iters-per-case=1` to validate full wiring.

### 4.3 Implementation Steps

#### Step A — Orchestrator config + data model changes
- Represent execution as:
  - outer loop: cases (01..03)
  - inner loop: iterations (0001..max)
- Extend summary writing:
  - per-case score trend
  - whether stop criteria reached per case

#### Step B — Implement real command runner
- Implement a `run_cmd()` helper (raises on failure).
- Ensure `.env` is loaded by each component (judge already does; `ckg-augment` now does).

#### Step C — Implement per-case iteration runner
For each case:
1) **Candidate CKG generation**
   - iter_0001:
     - scratch mode: `python -m ckg_augment.cli --report data/<case> --init-empty ...`
     - base mode: `python -m ckg_augment.cli --report data/<case> --ckg <base_ckg> ...`
   - iter_0002+:
     - same but add `--feedback <previous feedback>`
2) **Run debug-engine E2E**
   - `CKG_JSON_PATH=<candidate_ckg_iter_XXXX_case_XX.json> python tests/test_e2e_production.py`
3) **Capture agent artifacts**
   - Copy:
     - `output/e2e_production/agent_report_case{1..3}.md` → select the one that matches this case and copy to:
       - `agent_report_iter_XXXX_case_XX.md`
     - `output/e2e_production/production_comparison_report.json` → copy to:
       - `production_comparison_iter_XXXX_case_XX.json`
4) **Judge evaluation (OpenAI)**
   - Run:
     - `python -m judge.cli batch --provider openai --output-dir <tmp_or_default>`
   - Extract the result for this `case_XX` and copy into:
     - `judge_qa_report_iter_XXXX_case_XX.json`
     - `judge_qa_summary_iter_XXXX_case_XX.json` (per-case summary)
5) **Feedback generation**
   - Generate `feedback_iter_XXXX_case_XX.json` from the judge result (normalized schema).
6) **Stop evaluation**
   - If accuracy>=9 AND composite>8 for this case, stop iterating for this case.

**Important implementation note:** `judge.cli batch` evaluates all 3 cases at once using its embedded ground truth.
For per-case iteration, orchestrator should:
- run batch once per iteration (simplest), then select the target case result, OR
- add a new judge CLI mode to evaluate a single case (optional enhancement; not required initially).

---

## 5) CKG Augmenter Usage for Per-Case Iteration

### Iteration 0001
- No feedback yet
- Start mode:
  - scratch: `--init-empty`
  - base: `--ckg <base_ckg>`

### Iteration 0002+
- Provide feedback from previous iteration:
  - `--feedback feedback_iter_0001_case_XX.json`
  - `--case caseX` (case1/case2/case3)

**Rationale**
Keeps feedback edits scoped to the case being optimized.

---

## 6) Verification Checklist (Acceptance Criteria)

### Per-case scratch bootstrap coverage
- Run orchestrator with `--start-from-scratch` and `--max-iters-per-case 1`
- Confirm each case produced:
  - `candidate_ckg_iter_0001_case_XX.json`
  - `agent_report_iter_0001_case_XX.md`
  - `judge_qa_report_iter_0001_case_XX.json`
  - `feedback_iter_0001_case_XX.json`

### No overwrites
- Run twice with different `run_id`s → both preserved.
- Try to rerun with same `run_id` → orchestrator must fail fast.

### Provider correctness
- Judge invoked with `--provider openai`
- Debug-engine uses `OPENAI_API_KEY`

### Stop criteria correctness (per case)
- Orchestrator stops iterating a case only when both conditions are met.

---

## 7) Environment Prerequisites (Real Integration)

### Required for OpenAI
- `OPENAI_API_KEY`

### Required for Neo4j
- `NEO4J_URI` (default `bolt://localhost:7687`)
- `NEO4J_USER` (default `neo4j`)
- `NEO4J_PASSWORD` (default `password`)

