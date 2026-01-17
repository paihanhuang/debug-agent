# DebugAgent - Step by Step

This document describes the current DebugAgent pipeline as implemented in
`debug-engine/src/graphrag/agent.py` and related components.

---

## 0) Initialization

`DebugAgent.__init__` wires the following:

- **EmbeddingService** (OpenAI embeddings)
- **VectorStore** (FAISS index; may be loaded from disk)
- **Neo4jStore** (graph database for CKG traversal)
- **FixStore** (SQLite historical fixes)
- **Retriever** (vector + graph traversal)
- **OpenAI client** for LLM generation
- **MetricParser** for extracting metrics from input

---

## 1) Entry Point: `diagnose(input_text)`

### Step 1.1 — Retrieve Context
`Retriever.retrieve(input_text)`

Inside `Retriever.retrieve`:
1. **Parse Metrics**
   - `MetricParser.parse(input_text)` → `ExtractedMetrics`
2. **Vector Search**
   - Build query string from metrics (`metrics.to_query_string()`)
   - Embed query
   - Search FAISS for top‑K entity matches
3. **Graph Traversal**
   - For each matched entity, find upstream root causes in Neo4j
   - Build causal chains (root cause → matched entity)
4. **Subgraph**
   - Fetch a local subgraph around matched entities
5. **Historical Fixes**
   - Look up relevant fixes by root cause label

Outputs a `DiagnosisContext`:
- `metrics`
- `matched_entities`
- `root_causes`
- `causal_chains`
- `subgraph`
- `relevant_fixes`

---

### Step 1.2 — Build Prompt
`DebugAgent._build_prompt(input_text, context)`

The prompt includes:
- **User Observation**
- **Observed Metrics**
- **Root Causes (from CKG)**
- **Causal Chains**
- **CKG Traversal Nodes (must include)**
- **Historical Fixes**

---

### Step 1.3 — LLM Call (Primary Diagnosis)
`OpenAI.chat.completions.create(...)`

Inputs:
- `SYSTEM_PROMPT`
- User prompt built above

Output:
- A structured report with sections:
  - Root Cause
  - Causal Chain
  - Diagnosis
  - Historical Fixes

---

### Step 1.4 — LLM Post‑Processing (Traversal Node Coverage)
`DebugAgent._ensure_traversal_nodes(...)`

If any required CKG traversal nodes are missing:
- Calls a second LLM pass to revise the report
- Preserves metrics and structure
- Inserts missing nodes into the Causal Chain section

---

### Step 1.5 — Parse Response
`DebugAgent._parse_response(...)`

Splits by section headers:
- `Root Cause`
- `Causal Chain`
- `Diagnosis`
- `Historical Fixes`

Returns `DiagnosisResult`.

---

## 2) Optional: `refine(...)`

`DebugAgent.refine(previous_result, feedback, original_input)`

Uses judge feedback to revise the report via an LLM call.

---

## Key Data Sources
- **VectorStore (FAISS)**: similarity matching of entities
- **Neo4j CKG**: root causes + causal chains
- **FixStore (SQLite)**: historical fixes
- **LLM**: report generation + traversal node coverage

---

## Notes
- DebugAgent is **single‑stage** (one primary LLM call + optional post‑processing).
- It does **not** use the pattern store.
