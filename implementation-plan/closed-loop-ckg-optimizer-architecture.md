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

### 2) Debug Engine (`debug-engine/`)
- **Input:** CKG JSON (recommended standard path: `output/full_ckg.json`)
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
  - current base CKG JSON (e.g., `output/full_ckg.json`)
  - (later) `feedback.json` + previous agent report(s)
- Example:
  - `python -m ckg_augment.cli --report data/first --ckg output/full_ckg.json --output output/full_ckg.json --diff output/augmentation_diff.json`

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

## Artifact Versioning (Recommended)

For each run:
- `output/closed_loop/run_<timestamp>/`
  - `inputs/human_report.md`
  - `ckg/base_ckg.json`
  - `ckg/candidate_ckg.json` (copied to `output/full_ckg.json` for debug-engine)
  - `ckg/augmentation_diff.json`
  - `agent/agent_report_case{1..3}.md`
  - `judge/judge_qa_report.json`
  - `feedback/feedback.json`
  - `summary.json` (score trend)

---

## Stopping Criteria
- Achieve score threshold (e.g., avg ≥ 9.0) OR
- No improvement after N iterations OR
- Max iterations reached

---

## Scope of Changes
- Add an orchestrator (new code) and extend `ckg-augment/` to accept feedback.
- Keep `debug-engine/` and `judge/` unchanged (except configuration/path conventions).
