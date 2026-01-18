### Goal
Extend `ckg-augment` to also build/maintain a **Fix DB** (SQLite) alongside the augmented CKG, so `DebugAgent` can retrieve **historical fixes** and improve the judge’s **Actionability** score.

---

### High-level architecture
- **Input**
  - Human expert report text (e.g., `data/second`)
  - Base CKG JSON (optional; or `--init-empty`)
  - Optional closed-loop feedback JSON (judge → adapter → feedback schema)
  - Optional base fix DB (prior iteration)
- **Outputs (per iteration)**
  - `candidate_ckg_*.json` (existing)
  - `augmentation_diff_*.json` (existing)
  - `fixes_iter_XXXX_case_YY.db` (new)
  - `fix_db_diff_iter_XXXX_case_YY.json` (new: inserted/updated audit)

Dataflow:
`ckg-augment(report + base_ckg + base_fix_db + feedback) -> (candidate_ckg + fixes.db)`

Debug-engine uses:
`DebugAgent(fix_db_path=<iteration_fixes.db>)`

---

### Fix DB design (SQLite)
**v1 constraint**: keep schema compatible with `debug-engine/src/graphrag/fix_store.py` (so DebugAgent can use it with no code changes).

Existing schema:
- `historical_fixes(case_id TEXT UNIQUE, root_cause TEXT, symptom_summary TEXT, metrics_json TEXT, fix_description TEXT, resolution_notes TEXT, created_at TEXT)`

**Design choice**: reuse exactly in v1; add schema extensions only in v2 if needed.

---

### Fix extraction (ckg-augment)
Add a `FixExtractor` stage in `ckg-augment`, parallel to entity/relation extraction.

#### Fix record model (v1)
Each extracted fix maps to `FixStore.HistoricalFix`:
- **case_id**: deterministic, e.g. `fix_<report_id>_<sha1(root_cause + fix_description)[:10]>`
- **root_cause**: canonical root cause label (`CM`, `PowerHal`, `MMDVFS`, …)
- **symptom_summary**: short symptom summary (no invented thresholds)
- **metrics_json**: include only metrics explicitly present in report/prompt; `{}` allowed
- **fix_description**: actionable recommendation(s)
- **resolution_notes**: optional deeper notes / verification steps

#### Extraction method
- **Primary**: LLM-based structured extraction returning JSON list of fixes
- **Deterministic post-processing**
  - Normalize root cause labels (e.g., `CPU Manager` → `CM`)
  - De-duplicate by `(root_cause, fix_description)` hash
  - Enforce “no invention”: drop metrics not present in report text

---

### Fix DB build/update behavior (ckg-augment)
Add a new module, e.g. `ckg_augment/fix_db.py`, that:
- `load_or_init_fix_db(base_db_path, init_empty_db)`
- `apply_fixes(db_path, extracted_fixes, diff_out)`
  - Use `INSERT OR REPLACE` (same as `FixStore.add_fix`)
  - Default: add-only semantics via deterministic IDs (idempotent)

#### Provenance strategy (v1)
Since schema is fixed, store provenance inside `metrics_json` or `resolution_notes`, e.g.:
- `metrics_json["provenance"] = {"source":"ckg-augment", "report_id":..., "iter":..., "run_id":...}`

---

### CLI / contract changes
Extend `ckg-augment` CLI:
- `--fix-db <path>`: base fix DB to read from (optional)
- `--fix-db-out <path>`: output fix DB path (optional but recommended in orchestration)
- `--fix-db-diff <path>`: optional diff JSON
- `--no-fix-db`: disable fix extraction/DB writing

Recommended orchestrator naming:
- `fixes_iter_000X_case_YY.db`

---

### DebugAgent integration (minimal)
No debug-engine code changes required if we:
- pass the iteration DB path into `DebugAgent(fix_db_path=...)`

Optional improvement (later):
- make FixStore root cause lookup more tolerant (case-insensitive / partial match).

---

### Closed-loop interaction (judge → fix db)
When judge feedback includes missing `historical fixes` / `recommendations`:
- `ckg-augment` may ensure at least one fix exists for the inferred root cause(s)
- Still tag as feedback-derived in provenance

---

### Testing plan (V-model)
#### Unit tests (ckg-augment)
- **T1**: create DB from scratch (`--fix-db-out`) and verify table/rows
- **T2**: merge into existing DB (base DB + new fixes → union)
- **T3**: idempotency (apply twice, row count unchanged)
- **T4**: deterministic `case_id`
- **T5**: metrics safety: metrics_json contains only values present in report/prompt

#### Integration test (dry-run / fake extractor)
- Use a fake FixExtractor returning known fixes
- Build DB and verify `FixStore.get_all_fixes()` returns expected

---

### Suggested implementation order
1. Add `FixExtractor` interface + fake extractor for tests
2. Implement `fix_db.py` (create/update sqlite using FixStore schema)
3. Extend `ckg-augment` CLI with `--fix-db/--fix-db-out/--fix-db-diff`
4. Add orchestrator wiring later (set `DebugAgent(fix_db_path=iter_fix_db)`)

