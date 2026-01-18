# CKG Augmenter v1.1 (Feedback-Aware + Bootstrap-From-Scratch) — Detailed Plan (V-Model)

This plan revises `ckg-augment/` so it can:
- **Augment from an existing base CKG** (current behavior)
- **Bootstrap from scratch** when no base CKG exists
- Optionally consume **closed-loop feedback** (`feedback_iter_XXXX.json`) produced by the orchestrator to ensure missing elements (e.g., `SW_REQ2`) are represented in the CKG.

This plan is designed to be implementable and verifiable **before** the entire closed-loop system is wired to real debug-engine/judge runs.

---

## Objectives

### Functional goals
- Accept inputs:
  - **Human expert report text** (existing)
  - **Base CKG JSON** (optional)
  - **Closed-loop feedback JSON** (optional)
- Produce outputs:
  - **Candidate CKG JSON** (augmented or bootstrapped)
  - **Augmentation diff JSON** (audit trail)

### Non-functional goals
- **Deterministic** changes for feedback-driven augmentation (repeatable).
- **Idempotent** behavior (no duplicate nodes on re-run with the same inputs).
- **Safe / conservative** v1 behavior: add-only for feedback changes.

---

## Inputs / Outputs (Contract)

### Inputs
- `--report <path>`: expert report text file (required)
- `--ckg <path>`: base CKG JSON (optional)
- `--init-empty`: explicit flag to start from an empty CKG (required if `--ckg` not provided)
- `--feedback <path>`: orchestrator feedback JSON (optional)
- `--case <case1|case2|case3|all>`: which case’s missing elements to apply from feedback (default: `all`)

### Outputs
- `--output <path>`: candidate CKG JSON (required)
- `--diff <path>`: augmentation diff JSON (optional but strongly recommended for closed-loop)

**Versioning rule:** orchestrator is responsible for choosing iteration/case-numbered filenames.

---

## Design: Two-Phase Augmentation

### Phase A — Report extraction + merge (existing behavior)
Use existing LLM extractors:
- `EntityExtractor.extract_entities(report_text)`
- `RelationExtractor.extract_relations(report_text, entities)`

Then merge into the current graph (base or empty), with fuzzy match optional.

### Phase B — Feedback-driven “missing elements” ensure-pass (new)
If `--feedback` is provided, ensure any judge-identified missing elements exist as entities:
- For each missing label `X`:
  - If an entity with label `X` already exists (normalized), do nothing
  - Else add a new entity with:
    - deterministic ID from `(entity_type, normalized_label)` (not from report_id)
    - a safe default `EntityType` (v1 recommendation: `Observation`)
    - provenance in `attributes["provenance"]`

**v1 scope:** add entities only; do not add relations from feedback yet.

---

## Feedback Schema Dependency (Minimal v1)

The augmenter should depend only on the orchestrator-normalized feedback:
- `per_case[case_id].dimensions[].missing_elements`

If `prioritized_actions[]` exists in the feedback, it may be used preferentially,
but the required minimum is `missing_elements`.

---

## Bootstrap From Scratch (No Base CKG)

### Behavior
If no `--ckg` is provided and `--init-empty` is set:
- Create a new `CausalGraph()` in memory.
- Proceed with Phase A then Phase B.

### Why explicit `--init-empty`?
Prevents accidental runs that silently create empty graphs.

---

## Implementation Plan (V-Model)

### 1) Requirements & Interface Spec (this doc)
- Confirm CLI contract + data schemas.
- Confirm safety constraints (add-only feedback changes, idempotency).

### 2) Test Design (before coding)
Add unit tests under `ckg-augment/tests/`:

#### Test A — Bootstrap from scratch
- Given: `--init-empty` and a fake extractor returning one entity
- Expect: output graph contains that entity

#### Test B — Feedback missing-element adds entity
- Given: base graph missing `SW_REQ2`
- Given: feedback JSON referencing `SW_REQ2` missing in case1
- Expect: output graph contains label `SW_REQ2`
- Expect: diff includes this entity under a “feedback_added_entities” list (or equivalent)

#### Test C — Idempotency
- Run Phase B twice with same feedback
- Expect: no duplicates; diff shows no new adds on second pass

#### Test D — CLI validation
- No `--ckg` and no `--init-empty` => error
- `--init-empty` + `--ckg` together => error (mutually exclusive)

### 3) Implementation

#### 3.1 CLI changes (`ckg-augment/ckg_augment/cli.py`)
- Make `--ckg` optional
- Add `--init-empty`, `--feedback`, `--case`
- Keep existing flags

#### 3.2 Core changes (`ckg-augment/ckg_augment/augmenter.py`)
- Add helper: `load_or_init_ckg(ckg_path, init_empty)`
- Add helper: `extract_missing_elements(feedback_json, case_filter)`
- Add helper: `ensure_entities_for_missing_elements(graph, labels, provenance)`
- Extend `AugmentDiff` to include feedback-driven changes:
  - `feedback_added_entities: list[str]`
  - `feedback_skipped_existing: list[str]`

### 4) Verification
- Run `ckg-augment` unit tests
- Smoke-run the CLI in:
  - base-CKG mode
  - scratch mode (`--init-empty`)
  - feedback mode (`--feedback ...`)

---

## Rationale (Why this approach)

- **Safety first**: feedback-driven edges are riskier than nodes; start with add-only nodes.
- **Determinism**: feedback ensures-pass is rule-based, repeatable, and auditable.
- **Idempotency**: essential for closed-loop reruns and debugging.
- **Compatibility**: preserves existing LLM extraction path so bootstrapping from scratch works.

