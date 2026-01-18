### Goal
Extend `ckg-augment` feedback handling so closed-loop feedback can add **relations** (not just entities) in a **safe** way to improve:
- **Causal Chain Completeness**
- **Metric Precision**
without degrading:
- **Root Cause Accuracy**

This complements the existing feedback behavior which is currently **entity-add-only**.

---

### Safety constraints (must-haves)
- **Non-causal edges only** (default):
  - Use `RelationType.INDICATES`, `RelationType.ASSOCIATED_WITH`, `RelationType.LEADS_TO`, `RelationType.CONFIRMS`
  - Never use `RelationType.CAUSES` for feedback-derived edges in v1.
- **Low confidence** for feedback-derived edges:
  - default: `confidence=0.2–0.4` (v1 will use `0.3`).
- **Provenance tagging** on every feedback-derived relation:
  - `attributes.provenance[]` includes `{source:"closed_loop_feedback_relation", report_id, reason, rule_id}`
- **Idempotent**:
  - Re-applying the same feedback must not create duplicate relations.
- **DebugAgent traversal remains safe**:
  - Debug-engine should ignore non-causal edges when finding root causes / causal chains (already enforced by causal-only traversal).

---

### Inputs / outputs
- **Input**: feedback JSON in the schema consumed by `ckg-augment --feedback`:
  - `per_case[case_id].dimensions[].missing_elements[]`
- **Output**: augmented CKG with:
  - feedback-added entities (existing behavior)
  - **feedback-added relations** (new)

---

### v1 rules (deterministic, no LLM)

#### Rule A: SW_REQ mapping
If missing includes:
- `SW_REQ2`:
  - ensure entity `SW_REQ2` exists
  - add edge: `SW_REQ2 INDICATES CM`
- `SW_REQ3`:
  - ensure entity `SW_REQ3` exists
  - add edge: `SW_REQ3 INDICATES PowerHal`

Notes:
- `CM` target resolution should prefer existing nodes whose label contains `"CM"` (case-insensitive), prioritizing `RootCause` entities (e.g. `"CM causing ..."`).
- `PowerHal` target resolution should match label contains `"PowerHal"`; if absent, create a `Component` entity.

#### Rule B: 拉檔 (frequency throttling)
If missing includes `拉檔` or `frequency throttling`:
- ensure entity `拉檔` exists
- add edge: `拉檔 INDICATES CM`

#### Rule C: metric precision anchors
If missing includes:
- strings containing `DDR5460` or `DDR6370`:
  - ensure a `Metric` entity with that label exists
  - add edge: `<metric> INDICATES DDR`
- `CPU frequencies`:
  - ensure a `Metric` entity exists
  - add edge: `CPU frequencies INDICATES CPU`

#### Rule D: chain phrase parsing (weak reasoning chain)
If missing includes a chain-like string (contains `->` or `→`):
- parse tokens (e.g. `CM`, `CPU`, `DDR`, `VCORE`)
- ensure entities exist for tokens as `Component` (if no better match)
- add `LEADS_TO` edges between consecutive tokens

All Rule D edges are non-causal and low-confidence.

---

### Implementation plan (V-model)

#### Tests (first)
Add unit tests in `ckg-augment/tests/`:
- **T1**: feedback adds relation `SW_REQ2 INDICATES CM` (target can be `RootCause` label containing `CM`)
- **T2**: feedback adds relation `SW_REQ3 INDICATES PowerHal`
- **T3**: `拉檔 (frequency throttling)` normalizes to `拉檔` and adds `拉檔 INDICATES CM`
- **T4**: chain parsing adds `LEADS_TO` edges and is idempotent
- **T5**: idempotency: second run adds **0** feedback relations

#### Implementation
Update `ckg-augment/ckg_augment/augmenter.py`:
- Extend `AugmentDiff` to track:
  - `feedback_added_relations`
  - `feedback_skipped_existing_relations`
- After `_ensure_missing_entities`, add `_ensure_missing_relations(...)` that:
  - normalizes missing strings
  - resolves/creates entities
  - adds safe relations if missing

#### Verification
Run:
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q ckg-augment/tests`

