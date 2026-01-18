# Closed-Loop CKG Optimizer - Architecture (Using Existing `debug-engine/` + `judge/`)

This document specifies a closed-loop system to iteratively improve a CKG so
that, when used by the existing debug agent, the generated report matches the
human expert report as closely as possible.

**Constraint:** reuse the existing implementations in:
- `debug-engine/` for report generation
- `judge/` for evaluation

The only learner is `ckg-augment/`.

---

## Components (As-Is)

### 1) CKG Augmenter (`ckg-augment/`)
- **Input:** human expert report text file + current CKG JSON (+ feedback in later iterations)
- **Output:** augmented CKG JSON + augmentation diff artifact

**Bootstrap support (no base CKG):**
- When starting from scratch, the augmenter must support initializing from an empty CKG
  (no `--ckg` input) and building the initial graph from the human report and/or feedback.
- Detailed v1 plan: `implementation-plan/ckg-augment-feedback-v1.md`

### 2) Debug Engine (`debug-engine/`)
- **Input:** CKG JSON (recommended standard path: `assets/ckg/full_ckg.json`)
- **Execution:** run the existing E2E driver (`tests/test_e2e_production.py`)
- **Output:** agent reports:
  - `output/e2e_production/agent_report_case1.md`
  - `output/e2e_production/agent_report_case2.md`
  - `output/e2e_production/agent_report_case3.md`
- Also produces: `output/e2e_production/production_comparison_report.json`

### 3) Judge (`judge/`)
- **Execution:** run existing batch judge:
  - `python -m judge.cli batch --output-dir judge/qa_results`
- **Output:**
  - `judge/qa_results/judge_qa_report_<timestamp>.json` (full score matrix)
  - `judge/qa_results/latest_qa_summary.json` (summary)

### 4) Orchestrator (New, Thin Glue)
- Runs the loop and manages artifacts/versioning.
- Does **not** reimplement debug or judge logic.
- Produces a normalized **feedback package** from judge outputs for the augmenter.

---

## One Iteration (Concrete Flow)

### Step A — Augment CKG
- Inputs:
  - human report text file (ground truth source)
  - current base CKG JSON (e.g., `assets/ckg/full_ckg.json`)
  - (later) `feedback.json` + previous agent report(s)
- Example:
  - `python -m ckg_augment.cli --report data/first --ckg assets/ckg/full_ckg.json --output output/full_ckg.json --diff output/augmentation_diff.json`

### Step B — Generate Agent Reports (Debug Engine)
- Run:
  - `python tests/test_e2e_production.py`
- Outputs (standardized):
  - `output/e2e_production/agent_report_case{1..3}.md`

### Step C — Judge Evaluation
- Run:
  - `python -m judge.cli batch --output-dir judge/qa_results`
- Output:
  - `judge/qa_results/judge_qa_report_<timestamp>.json`

### Step D — Build Feedback Package
- Orchestrator reads `judge_qa_report_<timestamp>.json` and produces:
  - `feedback_vN.json` (structured, deterministic)
- This becomes input to the next augmentation iteration.

---

## Feedback Contract (Judge → Augmenter)

Because `judge/` returns per-dimension scores and natural-language explanations,
the orchestrator should normalize the judge output into a stable JSON schema:

- `scores`
  - overall + per-dimension per-case
- `missing_elements`
  - missing nodes/keywords (e.g., `SW_REQ2`) per-case
- `chain_gaps`
  - causal-chain completeness gaps (e.g., missing intermediate nodes)
- `metric_issues`
  - missing or incorrect metric mentions
- `overclaim`
  - extra/unnecessary root causes or claims vs ground truth
- `priority_fixes`
  - ranked list of CKG changes to try next

This feedback is derived from:
- `judge/qa_results/judge_qa_report_<timestamp>.json`
- and optionally textual diffs between agent report markdown and ground truth strings.

---

## Artifact Versioning (Required: No Overwrites)

### Storage Root
All closed-loop artifacts MUST be written under a new folder:
- `output/closed_loop_runs/`

### Naming Rules
- Every generated artifact MUST be named with:
  - **iteration number** (e.g., `iter_0001`)
  - **case number** (e.g., `case_01`, `case_02`, `case_03`) when the artifact is case-specific
- No files in `output/closed_loop_runs/` may be overwritten.
- Each loop execution creates a new run directory.

### Run Folder Layout
For each run:
- `output/closed_loop_runs/run_<run_id>/`
  - `inputs/`
    - `base_ckg.json`
    - `human_report_case_01.txt`
    - `human_report_case_02.txt`
    - `human_report_case_03.txt`
  - `iterations/`
    - `iter_0001/`
      - `ckg/`
        - `candidate_ckg_iter_0001.json`
        - `augmentation_diff_iter_0001.json`
      - `agent/`
        - `agent_report_iter_0001_case_01.md`
        - `agent_report_iter_0001_case_02.md`
        - `agent_report_iter_0001_case_03.md`
        - `production_comparison_iter_0001.json`
      - `judge/`
        - `judge_qa_report_iter_0001.json`
        - `judge_qa_summary_iter_0001.json`
      - `feedback/`
        - `feedback_iter_0001.json`
    - `iter_0002/`
      - (same structure)
  - `run_summary.json` (score trend across iterations, best iter, etc.)

---

## Working Copy Rule (No Overwrites)

To avoid overwriting `output/full_ckg.json` (or any old artifacts), the orchestrator
should run the debug stage against the iteration-specific CKG path.

**Recommended approach (contract):**
- Debug step MUST accept a CKG path (e.g., via a CLI arg or env var like `CKG_PATH`)
- Orchestrator passes:
  - `CKG_PATH=output/closed_loop_runs/run_<run_id>/iterations/iter_000k/ckg/candidate_ckg_iter_000k.json`

This keeps the existing `debug-engine/` logic, while making the orchestrator
fully non-destructive.

---

## Stopping Criteria
- Achieve score threshold (e.g., avg ≥ 9.0) OR
- No improvement after N iterations OR
- Max iterations reached

---

## Scope of Changes
- Add an orchestrator (new code) and extend `ckg-augment/` to accept feedback.
- Keep `debug-engine/` and `judge/` unchanged (except configuration/path conventions).

---

## Suggested Next Steps (Lowest Risk, Fastest Learning)

### 1) Lock down the loop contract (before coding)
Define precisely:
- **Per-iteration inputs/outputs**
  - Inputs: `human_report_case{1..3}.md`, `base_ckg.json`, optional `feedback.json`
  - Outputs: `candidate_ckg.json`, `agent_report_case{1..3}.md`, `judge_report.json`, `feedback.json`, `summary.json`
- **Feedback JSON schema** (judge → augmenter)
  - Include: per-case score matrix + missing elements + expected chain fragments + evidence quotes

This prevents thrash and keeps the loop reproducible.

### 2) Build orchestrator v0 (plumbing only, no learning)
Create a thin orchestrator command that runs:
- `ckg-augment` (initially in “no-op” mode: copy base CKG → candidate CKG)
- `python tests/test_e2e_production.py`
- `python -m judge.cli batch --output-dir judge/qa_results`
- Extract latest `judge_qa_report_*.json` into a normalized `feedback.json`
- Save all artifacts under `output/closed_loop/run_<timestamp>/`

Goal: validate end-to-end wiring and artifact paths without changing the CKG.

### 3) Revise `ckg-augment` to accept feedback (safe minimal behavior first)
Add a feedback-aware mode:
- `--feedback output/closed_loop/.../feedback.json`
- optional `--agent-reports output/e2e_production/`

Conservative v1 behavior:
- If feedback says “missing node X”, add entity (with provenance) only when evidence exists.
- If feedback says “missing edge A->B”, add it with evidence attached.
- Avoid aggressive rewrites until tests are in place.

### 4) Add regression tests around the loop
- Orchestrator unit test: creates run folder, copies artifacts, produces `feedback.json`
- Augmenter unit test: given “missing SW_REQ2”, adds it deterministically

### 5) Iterate on optimization strategy later
After v0 is stable, choose a selection policy:
- greedy accept-if-score-improves
- keep top-K candidates
- limit “edit budget” per iteration to avoid CKG drift
