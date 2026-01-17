# Hybrid Debug Agent - Step by Step

This document describes the current HybridTwoStageAgent pipeline in detail
(as implemented in `debug-engine/src/graphrag/hybrid_agent.py`).

---

## 0) Initialization

`HybridTwoStageAgent.__init__` wires these components:

- **Neo4jStore**: graph DB for CKG traversal
- **FixStore**: SQLite fixes DB
- **EmbeddingService + VectorStore**: initialized (vector search support)
- **MetricParser**: extracts metrics from user input
- **SmartAnomalyDetector**: deterministic rules + LLM fallback
- **Retriever**: builds per‑anomaly CKG context
- **OpenAI client**: LLM for Stage 2 + Stage 3

---

## 1) Entry Point: `diagnose(user_input)`

### Step 1.1 — Parse Metrics
`MetricParser.parse(user_input)` → `ExtractedMetrics`

Extracts values such as:
- VCORE usage %
- DDR usage %
- MMDVFS OPP / usage
- CPU frequencies
- SW_REQ2 / SW_REQ3 flags

---

## 2) Stage 1 — Anomaly Detection

Handled by `SmartAnomalyDetector`.

### Step 2.1 — Canonical Metrics
`_to_canonical(metrics)` produces normalized keys like:
- `vcore_725mv_pct`
- `ddr_total_pct`
- `mmdvfs_opp`
- `mmdvfs_opp3_pct`
- `sw_req_flags`

### Step 2.2 — Pattern Store Match (Deterministic)
`PatternStore.list_patterns()` is applied:
- e.g., `vcore_725mv_pct > 10 → VCORE_CEILING`
- creates `DetectedAnomaly` with `indicated_causes`

### Step 2.3 — Exclusion Filtering
`PatternStore.list_exclusions()` filters anomalies:
- if exclusion metrics missing → ambiguity
- if exclusion matches → anomaly removed

### Step 2.4 — LLM Fallback (Ambiguity)
If ambiguous, call `AnomalyDetector.detect_with_details` (LLM).

### Stage 1 Output
- `anomalies: list[DetectedAnomaly]`
- `has_dual_issue`
- `summary`
- `llm_calls` incremented if LLM fallback used

---

## 3) Stage 2 — Per‑Anomaly Diagnosis (LLM)

Runs once per anomaly.

### Step 3.1 — Retrieve Context
`Retriever.retrieve_for_anomaly(anomaly, metrics)`:
- Uses `anomaly.indicated_causes`
- Fetches root causes from Neo4j
- Builds causal chains (root → symptom)
- Attaches ancestry
- Retrieves subgraph + historical fixes

### Step 3.2 — Build Prompt
`PER_ANOMALY_DIAGNOSIS_PROMPT` includes:
- anomaly type, metric, value, severity
- original metrics (exact values)
- CKG context

### Step 3.3 — LLM Call
Produces an anomaly‑specific report with sections:
- Root Cause
- Causal Chain
- Explanation
- Suggested Fixes

### Step 3.4 — Parse Result
Response is parsed into `AnomalyDiagnosis`:
- `root_cause`
- `causal_chain`
- `explanation`
- `suggested_fixes`

---

## 4) Stage 3 — Synthesis (LLM)

### Step 4.1 — Build Synthesis Prompt
`SYNTHESIS_PROMPT` includes:
- all per‑anomaly diagnosis blocks
- original user input

### Step 4.2 — LLM Call
Produces a unified report:
- Root Cause(s)
- Causal Chain(s)
- Diagnosis Summary
- Recommended Actions

### Step 4.3 — Final Result
Returns `HybridDiagnosisResult`:
- `anomalies`
- `diagnoses`
- `synthesized_report`
- `has_dual_issue`
- `llm_calls`

---

## Key Data Sources Used
- **Pattern Store (SQLite)**: Stage 1 rules + exclusions
- **Neo4j CKG**: traversal for chains / subgraph / ancestry (Stage 2)
- **FixStore (SQLite)**: historical fixes (Stage 2)
- **LLM**: Stage 1 fallback, Stage 2 per‑anomaly, Stage 3 synthesis

---

## Differences vs DebugAgent
- **DebugAgent**: single‑stage (vector + Neo4j + LLM once)
- **HybridTwoStageAgent**: multi‑stage (detect → per‑anomaly → synthesize)
- Pattern store is used **only** in the hybrid flow
