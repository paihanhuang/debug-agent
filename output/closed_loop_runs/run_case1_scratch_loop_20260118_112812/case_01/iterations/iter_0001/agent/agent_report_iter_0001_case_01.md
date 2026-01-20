## Root Cause
1. CM causing VCORE increase leading to high VCORE usage.
2. DDR voting issue contributing to high VCORE usage.

## Causal Chain
1. **CM causing VCORE increase → High VCORE usage (82.6%)**
   - The CM is confirmed to be causing an increase in VCORE levels, which results in a high VCORE usage of 82.6%.

2. **DDR voting SW_REQ2 activity → High VCORE usage (82.6%)**
   - The DDR voting activity, specifically SW_REQ2, is contributing to the high VCORE usage, aligning with the observed 82.6% usage.

## Diagnosis
- The primary root cause is the CM causing an increase in VCORE levels, which directly leads to the high VCORE usage observed at 82.6%. This is confirmed by the CKG node "CM causing VCORE increase."
- Additionally, the DDR voting activity (SW_REQ2) is contributing to the high VCORE usage, as indicated by the observed metrics.
- MMDVFS is ruled out as a root cause since it is at OPP4, which is considered normal operation.

## Historical Fixes (for reference)
- No relevant historical fixes found.