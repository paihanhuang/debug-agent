# Smart Anomaly Detection v2 - Implementation Plan

## Overview
Optimized hybrid approach that minimizes LLM calls through threshold-first detection and CKG-driven exclusions.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│              SMART ANOMALY DETECTION v2                       │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  User Input ──► Metric Parser ──► Threshold Check             │
│                                        │                      │
│                                        ▼                      │
│                              Candidate Anomalies              │
│                                        │                      │
│                                        ▼                      │
│                  CKG Query (patterns + exclusions)            │
│                                        │                      │
│                          ┌─────────────┴─────────────┐        │
│                          │                           │        │
│                    [Confident]                 [Ambiguous]    │
│                          │                           │        │
│                          ▼                           ▼        │
│                  Return Fast (~200ms)      LLM Refinement     │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

---

## Key Optimizations

| Optimization | Before | After | Benefit |
|--------------|--------|-------|---------|
| LLM Calls | Every detection | Ambiguous only | 80% fewer calls |
| Exclusions | Hardcoded rules | CKG edges | Data-driven |
| Latency | 2-3s | 200ms | 10x faster |
| Cost | $0.01/detection | $0.002/detection | 5x cheaper |

---

## Component Design

### 1. Threshold Detector (No LLM)

```python
THRESHOLDS = {
    "vcore_725mv_pct": {"gt": 10, "type": "VCORE_CEILING", "causes": ["rc_cm", "rc_powerhal"]},
    "vcore_floor_mv": {"gt": 575, "type": "VCORE_FLOOR", "causes": ["rc_mmdvfs"]},
    "ddr_total_pct": {"gt": 30, "type": "DDR_HIGH", "causes": ["rc_cm", "rc_powerhal"]},
    "mmdvfs_opp3_pct": {"gt": 50, "type": "MMDVFS_ABNORMAL", "causes": ["rc_mmdvfs"]},
}
```

### 2. CKG Pattern with Exclusions

```json
{
  "id": "pattern_vcore_floor",
  "type": "AnomalyPattern",
  "label": "VCORE Floor Elevated",
  "attributes": {
    "metric": "vcore_floor_mv",
    "threshold": 575,
    "indicates": ["rc_mmdvfs"],
    "exclude_when": [
      {"metric": "mmdvfs_opp", "equals": "OPP4", "reason": "OPP4 is normal"}
    ]
  }
}
```

### 3. CKG Exclusion Query

```cypher
MATCH (p:AnomalyPattern)
WHERE p.metric = $detected_metric
OPTIONAL MATCH (p)-[:EXCLUDES_WHEN]->(ex:Condition)
WITH p, COLLECT(ex) as exclusions
WHERE ALL(ex IN exclusions WHERE NOT $metrics[ex.metric] = ex.value)
RETURN p
```

### 4. Smart Detector Class

```python
class SmartAnomalyDetector:
    def __init__(self, neo4j_store, llm_client=None):
        self.neo4j = neo4j_store
        self.llm = llm_client  # Optional - only for ambiguous
    
    def detect(self, user_input: str, metrics: ExtractedMetrics):
        # Step 1: Threshold-based detection (fast)
        candidates = self._threshold_detect(metrics)
        
        # Step 2: CKG exclusion filtering
        filtered = self._apply_ckg_exclusions(candidates, metrics)
        
        # Step 3: LLM only if ambiguous
        if self._is_ambiguous(filtered, user_input):
            return self._llm_refine(filtered, user_input)
        
        return filtered
    
    def _is_ambiguous(self, anomalies, user_input):
        # LLM needed if: unknown type, conflicting signals, unusual values
        return any(a.type == "UNKNOWN" for a in anomalies)
```

---

## Data Model Changes

### CKG: Add `exclude_when` to Patterns

| Pattern | exclude_when |
|---------|--------------|
| `pattern_vcore_floor` | `mmdvfs_opp = OPP4` |
| `pattern_vcore_ceiling_sw_req2` | `sw_req = SW_REQ3_ONLY` |
| `pattern_vcore_ceiling_sw_req3` | `sw_req = SW_REQ2_ONLY` |

### New Neo4j Relationship

```cypher
(pattern:AnomalyPattern)-[:EXCLUDES_WHEN]->(condition:ExclusionCondition)
```

---

## Implementation Phases

### Phase 1: CKG Enhancement
- [ ] Add `exclude_when` attributes to existing patterns
- [ ] Add SW_REQ-specific exclusion conditions
- [ ] Test with current detector (no code change yet)

### Phase 2: Threshold Detector
- [ ] Create `SmartAnomalyDetector` class
- [ ] Implement `_threshold_detect()` with THRESHOLDS dict
- [ ] Implement `_apply_ckg_exclusions()` query

### Phase 3: Ambiguity Detection
- [ ] Define ambiguity criteria
- [ ] Implement `_is_ambiguous()` heuristic
- [ ] Keep LLM as fallback for edge cases

### Phase 4: Integration
- [ ] Replace `AnomalyDetector` with `SmartAnomalyDetector`
- [ ] Update `HybridTwoStageAgent` to use new detector
- [ ] Run full E2E regression tests

---

## Verification Plan

### Expected Results After Implementation

| Case | Current | Expected | Improvement |
|------|---------|----------|-------------|
| case1 | 8.80 (A) | 8.80+ | Maintain |
| case2 | 7.00 (B) | **8.50+** | Fix MMDVFS exclusion |
| case3 | 8.45 (A) | 8.50+ | Maintain |
| **Avg** | 8.08 | **8.60+** | +0.52 |

### Performance Metrics

| Metric | Before | After |
|--------|--------|-------|
| Avg Detection Time | 2.5s | 0.3s |
| LLM Calls per Case | 5-7 | 1-2 |
| Cost per Case | ~$0.05 | ~$0.01 |

---

## Status: PENDING APPROVAL
