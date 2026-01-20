## Root Cause
1. MMDVFS OPP3 issue causing VCORE floor to be at 600mV.
2. CM/PowerHal/DDR voting issue causing VCORE 725mV usage to be at 52.51%, with DDR5460 contributing 23.37% and DDR6370 contributing 30.77% to the overall DDR total of 54.14%.

## Causal Chain
1. **MMDVFS OPP3 Issue:**
   - MMDVFS is at OPP3 with 100% usage → VCORE floor is set at 600mV (should be 575mV) → Increased power consumption due to higher VCORE floor.

2. **CM/PowerHal/DDR Voting Issue:**
   - VCORE 725mV usage is at 52.51% (exceeds 10% threshold) → Indicates a CM/PowerHal/DDR voting issue → Results in excessive power usage at high VCORE levels, with DDR5460 and DDR6370 contributing significantly to the DDR total of 54.14%.

## Diagnosis
1. **MMDVFS OPP3 Issue:**
   - The VCORE floor is set at 600mV, which is above the normal threshold of 575mV. This is directly linked to the MMDVFS being at OPP3 with 100% usage, confirming that the MMDVFS configuration is causing the elevated VCORE floor.

2. **CM/PowerHal/DDR Voting Issue:**
   - The VCORE 725mV usage is significantly high at 52.51%, which is well above the 10% threshold. This indicates a problem with CM/PowerHal/DDR voting, leading to unnecessary high power consumption at elevated VCORE levels. The DDR5460 and DDR6370 frequencies contribute 23.37% and 30.77% respectively, to the DDR total of 54.14%.

## Historical Fixes (for reference)
- No relevant historical fixes found.