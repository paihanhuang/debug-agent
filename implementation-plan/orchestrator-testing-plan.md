# Orchestrator Testing Plan

This document describes how to test the closed-loop orchestrator before and
after the full system is connected.

---

## Test Levels

### 1) Unit Tests (Fast, No External Dependencies) — Can be done immediately
Goal: validate orchestrator behavior as a deterministic pipeline runner by
mocking external commands.

**Approach**
- Mock/patch command execution (`subprocess.run` or the orchestrator’s runner wrapper).
- In the mock, write minimal fake outputs into expected locations.

**Assertions**
- Creates a new run folder under `output/closed_loop_runs/run_<run_id>/`.
- Creates iteration folders under `iterations/iter_XXXX/`.
- Produces required iteration artifacts with correct naming:
  - `ckg/candidate_ckg_iter_XXXX.json`
  - `judge/judge_qa_report_iter_XXXX.json`
  - `feedback/feedback_iter_XXXX.json`
- Does not overwrite old runs (new run id each time).
- Stop condition logic works:
  - stops when `accuracy >= 9` AND `overall_score > 8`
  - continues otherwise.

---

### 2) Dry-Run Integration Test (No Neo4j/LLM/Judge) — Can be done immediately
Goal: validate the full filesystem contract end-to-end without wiring debug-engine
and judge yet.

**Required feature**
- Add orchestrator flag: `--dry-run`

**Dry-run behavior**
- Copy base CKG → candidate CKG for `iter_0001`
- Generate placeholder agent reports:
  - `agent_report_iter_0001_case_01.md` etc.
- Generate a synthetic judge report JSON and summary JSON
- Generate normalized `feedback_iter_0001.json`

**Assertions**
- Full run bundle is created and matches the contract (folders + filenames).
- Feedback JSON schema is stable and contains required fields.

---

### 3) Real Integration Test (Neo4j + OpenAI + Judge) — Requires full wiring
Goal: run the actual pipeline end-to-end:
`ckg-augment → debug-engine → judge → feedback`.

**Prerequisites**
- Neo4j running and reachable
- `OPENAI_API_KEY` configured

**Assertions**
- Orchestrator completes 1 iteration and produces all artifacts.
- Debug-engine E2E completes successfully.
- Judge batch produces a report, and feedback is generated.

---

### 4) Golden-File Regression (Feedback Parser) — Can be done early once schema is fixed
Goal: ensure judge-to-feedback extraction is stable and deterministic.

**Approach**
- Check in a small fixture: `judge_qa_report_fixture.json`
- Run feedback parser and compare output to a committed golden:
  - `expected_feedback_fixture.json`

---

## Recommended Testing Sequence (Before Full Wiring)
1. Implement unit tests (1)
2. Implement `--dry-run` and dry-run integration test (2)
3. Add golden-file regression for feedback parsing (4)
4. Add real integration test once wiring and environment exist (3)

