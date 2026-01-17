# Smart Anomaly Detection v2.1 - Proposed Design

## Overview
Refined design that keeps the v2 goals (fewer LLM calls, CKG-driven rules) while
adding stable metric normalization, safer exclusion semantics, and a clearer
ambiguity gate for LLM fallback.

---

## Goals
- Deterministic detection for known thresholds
- CKG-driven exclusions and pattern rules
- LLM only for ambiguous or novel cases
- Stable metric schema to prevent rule drift

---

## Architecture

```
User Input
   │
   ▼
Metric Parser (canonical schema)
   │
   ▼
Threshold Detector (fast, deterministic)
   │
   ▼
CKG Pattern + Exclusion Filter
   │
   ├── Confident → Return anomalies
   └── Ambiguous → LLM refinement
```

---

## Component Design

### 1) Metric Normalization Layer (Required)
Thresholds and exclusions must reference canonical keys. Extend `MetricParser`
to output a normalized metrics dict with presence flags.

**Canonical fields (examples):**
- `vcore_725mv_pct`
- `vcore_floor_mv`
- `ddr_total_pct`
- `mmdvfs_opp` (string)
- `mmdvfs_opp3_pct`
- `sw_req_flags` (set: `SW_REQ2`, `SW_REQ3`)
- `cpu_ceiling` (bool)
- `cpu_freqs` (dict)

Also expose `has_<metric>` presence flags to distinguish "missing" vs "0".

---

### 2) Threshold Detector (No LLM)

```python
THRESHOLDS = {
    "vcore_725mv_pct": Threshold(
        gt=10, type="VCORE_CEILING", causes=["rc_cm", "rc_powerhal"]
    ),
    "vcore_floor_mv": Threshold(
        gt=575, type="VCORE_FLOOR", causes=["rc_mmdvfs"]
    ),
    "ddr_total_pct": Threshold(
        gt=30, type="DDR_HIGH", causes=["rc_cm", "rc_powerhal"]
    ),
    "mmdvfs_opp3_pct": Threshold(
        gt=50, type="MMDVFS_ABNORMAL", causes=["rc_mmdvfs"]
    ),
}
```

Each candidate anomaly includes:
- `type`, `metric`, `value`, `severity`
- `indicated_causes`
- `confidence` (derived from distance to threshold)

---

### 3) CKG Pattern + Exclusion Rules

**Data model**
- `(:AnomalyPattern {metric, threshold, indicates[]})`
- `(:ExclusionCondition {metric, op, value})`
- `(:AnomalyPattern)-[:EXCLUDES_WHEN]->(:ExclusionCondition)`

**Semantics**
- Exclude only if **all required metrics exist** and **all exclusion conditions match**.
- If any required metric is missing → mark **ambiguous**, do not exclude.

---

### 4) Ambiguity Gate (LLM Fallback)
Call LLM only if:
- Required metrics are missing for a rule/exclusion
- Conflicting signals (e.g., both SW_REQ2 and SW_REQ3 when pattern is exclusive)
- Unknown anomaly type
- Low confidence (threshold barely exceeded)

LLM input includes:
- Raw user text
- Canonical metrics
- Candidate anomalies + applied exclusions
- Ambiguity reasons

---

## Smart Detector Class (Proposed)

```python
class SmartAnomalyDetector:
    def __init__(self, neo4j_store, llm_client=None):
        self.neo4j = neo4j_store
        self.llm = llm_client  # Optional - only for ambiguous

    def detect(self, user_input: str, metrics: ExtractedMetrics):
        candidates = self._threshold_detect(metrics)
        filtered, ambiguity = self._apply_ckg_exclusions(candidates, metrics)
        if ambiguity or self._needs_llm(filtered):
            return self._llm_refine(user_input, metrics, filtered, ambiguity)
        return filtered
```

---

## Integration
1. Replace `AnomalyDetector` with `SmartAnomalyDetector`
2. Hybrid agent uses:
   - Stage 1: Smart detection
   - Stage 2: Per-anomaly diagnosis
   - Stage 3: Synthesis

---

## Expected Outcomes
- 80% fewer LLM calls
- Lower latency and cost
- More predictable anomaly detection
- Safer behavior with partial/missing inputs

---

## Unknown Pattern Example
If an anomaly does not match any known threshold or CKG pattern, emit an
`UNKNOWN` anomaly and mark it as ambiguous for LLM refinement.

```json
{
  "anomalies": [
    {
      "id": "anomaly_1",
      "type": "UNKNOWN",
      "metric": "gpu_bw_pct",
      "value": "92%",
      "severity": "high",
      "why_abnormal": "Metric not covered by known patterns; unusually high value.",
      "indicated_causes": []
    }
  ],
  "has_dual_issue": false,
  "summary": "Unrecognized high GPU bandwidth usage; needs LLM refinement."
}
```

