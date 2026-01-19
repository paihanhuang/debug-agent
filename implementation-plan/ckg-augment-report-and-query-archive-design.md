### Revised design (v3): always store raw human report + raw debug-agent query/prompt

### Goals (hard requirements)
- **Always archive**:
  - the **raw report input** passed to `ckg-augment` (exact bytes/text)
  - the **raw debug-agent query/prompt** used for that case (exact text)
- **No overwrite**: archived artifacts are immutable.
- **Dedup** by content-hash.
- **Traceability**: each CKG/Fix DB output can be traced back to the archived raw report + raw query.

---

## What gets stored (per `ckg-augment` run)
For every invocation, store:

### A) Raw inputs (always)
- **`raw_report_input.txt`**: exact contents read from `--report` (full file, unchanged)
- **`raw_debug_query.txt`**: the exact query string that the DebugAgent should receive

Key point: `raw_debug_query.txt` is stored as its own first-class artifact, not just a parsed snippet.

### B) Parsed convenience copies (optional but useful)
If `--report` is a combined `data/<case>` file with the `E2E Test Query ...` marker:
- **`human_report.txt`**: report section (before `---`)
- **`parsed_debug_query.txt`**: the marker section (after the marker)

### C) Metadata (always)
- **`meta.json`** includes:
  - hashes:
    - `report_sha256` (hash of `raw_report_input.txt`)
    - `query_sha256` (hash of `raw_debug_query.txt`)
  - `report_id` (default: `Path(report).stem`)
  - `source_report_path`
  - `source_query_path` or `query_source` (see below)
  - `created_at`
  - run linkage: `run_id`, `case_num`, `iter_num` (if provided)
  - `llm_provider`, `case_filter`
  - `ckg_in_path`, `ckg_out_path`
  - `fix_db_in_path`, `fix_db_out_path`

### D) Optional extracted artifacts (toggleable)
- `extracted_entities.json`
- `extracted_relations.json`
- `extracted_fixes.json`

---

## How `ckg-augment` gets the “raw debug query”
Support two modes, both archiving the query:

### Mode 1 (recommended for orchestration): explicit query file
Add CLI arg:
- `--debug-query <path>`: path to a text file containing the exact prompt/query

Behavior:
- Read that file as the authoritative raw query and store verbatim to `raw_debug_query.txt`.

### Mode 2 (backward compatible): query extracted from combined `--report`
If `--debug-query` is not provided:
- Parse the query from `--report` by locating `E2E Test Query...` marker.
- Store the extracted text as `raw_debug_query.txt`.

Precedence rule:
- If both `--debug-query` and an embedded query exist, prefer `--debug-query` and also store `parsed_debug_query.txt` for comparison.

---

## Storage layout (no overwrite + dedupe)
Default root (generated): `output/report_library/`

Because there are TWO raw inputs (report + query), name the bundle using both hashes:

```
output/report_library/
  bundles/
    bundle_<report_id>_r<reportsha12>_q<querysha12>/
      raw_report_input.txt
      raw_debug_query.txt
      human_report.txt            # optional convenience
      parsed_debug_query.txt      # optional convenience
      meta.json
      extracted_entities.json     # optional
      extracted_relations.json    # optional
      extracted_fixes.json        # optional
```

No overwrite:
- If the bundle folder exists, do not modify any file contents.

Dedup:
- Same report+query pair → same bundle id → single canonical archive.
- Same report but different query → different bundle (expected).

---

## Index DB (search + linking)
SQLite DB: `output/report_library/report_index.db`

Two tables:

### 1) `bundle_index`
- `bundle_id TEXT PRIMARY KEY` (e.g., `bundle_<report_id>_r.._q..`)
- `report_sha256 TEXT`
- `query_sha256 TEXT`
- `bundle_path TEXT`
- `created_at TEXT`
- `report_id TEXT`
- `source_report_path TEXT`
- `source_query_path TEXT NULL`
- `query_source TEXT` (`explicit_file` | `parsed_from_report`)
- `run_id TEXT NULL`, `case_num INTEGER NULL`, `iter_num INTEGER NULL`
- `ckg_out_path TEXT NULL`
- `fix_db_out_path TEXT NULL`

### 2) `artifact_index` (optional, but helpful)
- `bundle_id TEXT`
- `artifact_type TEXT` (ckg, fixdb, diff, etc.)
- `artifact_path TEXT`

---

## CLI changes (ckg-augment)
Add:
- `--debug-query <path>` (optional; if absent, parse from report)
- `--archive-reports/--no-archive-reports` (default: on)
- `--report-library-root` (default: `output/report_library`)
- `--run-id --case-num --iter-num` (optional metadata)
- `--no-extracted-artifacts` (optional; does not disable raw storage)

---

## Orchestrator wiring (recommended)
Update `orchastrator/case_loop.py` to pass:
- `--debug-query <inputs/prompt_case_XX.txt>` (already written by orchestrator)
- `--run-id`, `--case-num`, `--iter-num`

This ensures the archive always contains the exact query sent to DebugAgent (no ambiguity).

---

## Git + safety
- Add `output/report_library/**` to `.gitignore` (generated + likely sensitive).
- Raw reports and prompts should not be committed.

---

## Tests (V-model)
Add tests in `ckg-augment/tests/`:
- **T1**: Archive writes both `raw_report_input.txt` and `raw_debug_query.txt`.
- **T2**: With `--debug-query`, `query_source=explicit_file` and query is stored verbatim.
- **T3**: Without `--debug-query`, query is parsed from `--report` and stored as `raw_debug_query.txt`.
- **T4**: Dedup: same report+query → same bundle folder; no overwrite.
- **T5**: Index DB contains bundle row keyed by bundle_id with correct hashes and paths.

