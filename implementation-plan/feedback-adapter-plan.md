### Goal
Implement a **tiny feedback adapter** that converts **single-case judge output** (from `python -m judge.cli run`) into the **feedback JSON schema** consumed by `ckg-augment --feedback`.

This enables a clean closed-loop iteration:
`ckg-augment → debug-agent → judge → (adapter) → ckg-augment …`

---

### Requirements (V-model: requirements → tests → implementation)

- **R1: Input compatibility**
  - Accept a judge JSON produced by `judge.cli run` (example: `judge_result_case2.json`).
  - Key fields used:
    - `case_name` (optional)
    - `composite_score`
    - `grade`
    - `summary`
    - `dimensions[]` where each includes:
      - `name`
      - `score`
      - `weight`
      - `explanation`
      - `matched_elements`
      - `missing_elements`

- **R2: Output compatibility with `ckg-augment`**
  - Produce a JSON object that works with:
    - `ckg-augment/ckg_augment/augmenter.py::extract_missing_elements(feedback, case_filter)`
  - Therefore output must include:
    - top-level `per_case` dict
    - `per_case[case_id].dimensions[]`
    - each dimension has `missing_elements` list (strings)

- **R3: Normalization**
  - Normalize missing elements to prevent churn / bad entity names:
    - Trim whitespace
    - De-duplicate while preserving order
    - Optional canonicalization rules:
      - `"拉檔 (frequency throttling)"` → `"拉檔"`
      - `"frequency throttling"` → `"拉檔"` (optional v1)

- **R4: Stop criteria computation**
  - Compute:
    - `accuracy_score` from dimension named **`Root Cause Accuracy`**
    - `average_score` from `composite_score`
  - Compute `stop_reached` using **user thresholds**:
    - \(accuracy \ge min\_accuracy\) AND \(overall \ge min\_overall\)

- **R5: Deterministic, no-LLM**
  - Adapter must be pure JSON transform; no external calls.

- **R6: CLI usability**
  - Provide a small CLI for piping:
    - `--judge <path>` input
    - `--out <path>` output
    - `--case-id case2`
    - `--iter-num 1`
    - `--run-id ...` (optional)
    - `--stop-accuracy 9 --stop-overall 8`

---

### Interface / contract

- **Library function**
  - `judge_result_to_feedback(judge_result: dict, *, run_id: str, iter_num: int, case_id: str, stop_accuracy: float, stop_overall: float) -> dict`

- **Output schema (minimum)**
```json
{
  "run_id": "r1",
  "iter_num": 1,
  "average_score": 7.75,
  "accuracy_score": 8.0,
  "per_case": {
    "case2": {
      "composite_score": 7.75,
      "grade": "B",
      "dimensions": [
        {
          "name": "Root Cause Accuracy",
          "score": 8,
          "weight": 0.5,
          "missing_elements": ["拉檔"],
          "matched_elements": ["CM", "PowerHal"],
          "explanation": "..."
        }
      ]
    }
  },
  "stop_reached": false,
  "stop": { "min_accuracy": 9.0, "min_overall": 8.0 }
}
```

---

### Verification plan (V-model)

#### Unit tests (orchastrator)
- **T1: Basic mapping**
  - Given a judge JSON with 5 dimensions, adapter produces:
    - correct `per_case[case_id].dimensions` length
    - `missing_elements` copied through

- **T2: Normalization**
  - Missing elements include duplicates and whitespace variants:
    - `[" SW_REQ2 ", "SW_REQ2", "拉檔 (frequency throttling)"]`
  - Output becomes:
    - `["SW_REQ2", "拉檔"]`

- **T3: Stop criteria**
  - With `Root Cause Accuracy=9` and `composite_score=8.0`:
    - stop is **True** (uses `>=` overall)

#### Integration check (manual / smoke)
- Run:
  - `python -m orchastrator.feedback_adapter --judge judge.json --out feedback.json --case-id case2 --iter-num 1`
  - `python -m ckg_augment.cli --feedback feedback.json --case case2 ...`
- Confirm `ckg-augment` adds entities for the missing elements.

