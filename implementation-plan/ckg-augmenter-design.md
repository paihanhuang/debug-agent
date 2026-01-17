# CKG Augmenter - Design Proposal

## Goal
Enrich an existing CKG with new entities/relations extracted from a new expert
report, while preserving existing structure and avoiding duplication.

---

## Inputs / Outputs

**Inputs**
- `report_path`: text file (human expert report)
- `ckg_path`: existing CKG JSON

**Outputs**
- `augmented_ckg.json` (merged graph)
- Optional: `augmentation_diff.json` (what was added/updated)

---

## High-Level Pipeline

1. **Load Base CKG**
   - Parse existing CKG JSON into in-memory graph objects.

2. **Extract New Knowledge from Report**
   - Reuse existing extractors:
     - `EntityExtractor` for entities
     - `RelationExtractor` for relations
   - Output: `extracted_entities`, `extracted_relations`

3. **Normalize / Canonicalize**
   - Normalize labels (case, language variants, synonyms)
   - Map terms like “拉檔” ↔ “frequency throttling”

4. **Match & Merge**
   - **Entity matching**
     - Exact match on normalized label + type
     - Canonical label match
     - Fuzzy match (optional): vector similarity or string similarity
   - **Relation matching**
     - Match by `(source, relation_type, target)`
   - Merge logic:
     - If match exists → update confidence / add evidence
     - If new → create entity/relation with new ID

5. **Attach Provenance**
   - Each added/updated item includes:
     - `source_text`, `report_id`, `confidence`, `timestamp`
   - Keep existing provenance untouched.

6. **Export Augmented CKG**
   - Write merged JSON
   - Optional diff report (for review)

---

## Key Design Decisions

### Entity Merge Strategy
- **Priority order**
  1. Exact label + type match
  2. Canonical label match
  3. Fuzzy similarity (optional, thresholded)

### Relation Merge Strategy
- Keep relations unique by `(source_id, relation_type, target_id)`
- Merge evidence lists and confidence

### New Node IDs
- Use deterministic IDs (hash of normalized label + type + report_id)
- Prevent duplication on repeat augment runs

---

## Optional Enhancements
- **Augmentation Diff Report**
  - Added entities
  - Added relations
  - Updated confidence/evidence

- **Conflict Detection**
  - Flag if new relation contradicts existing (e.g., RULES_OUT vs CAUSES)
  - Output conflicts for manual review

---

## Example Flow

Input report:
“SW_REQ2 activity indicates CM causes DDR voting spike.”

Output:
- Add (if missing) entity: `SW_REQ2`
- Add relation: `CM -> SW_REQ2` (CAUSES / INDICATES)
- Add relation: `SW_REQ2 -> DDR voting` (CAUSES / INDICATES)
- Preserve existing CKG relations

---

## API Sketch (No Implementation Yet)

```python
augment_ckg(
  report_path: str,
  ckg_path: str,
  output_path: str,
  diff_path: str | None = None,
  llm_provider: str = "openai",
  fuzzy_match: bool = True,
) -> None
```
