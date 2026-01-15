# VCORE Power Debugging Knowledge Graph
# LLM-Optimized Format for Automated Diagnosis

## CAUSAL RULES

RULE: IF "調控策略 (Control Policy)" THEN "CM (CPU Manager)" | Strength: 95% | Timing: immediate
RULE: IF "CM (CPU Manager)" THEN "CPU 大核 at ceiling" | Strength: 95% | Timing: immediate
RULE: IF "CM (CPU Manager)" THEN "CPU 中核 at ceiling" | Strength: 95% | Timing: immediate
RULE: IF "CM (CPU Manager)" THEN "CPU 小核 at ceiling" | Strength: 95% | Timing: immediate
RULE: IF "CPU at ceiling frequencies" THEN "DDR投票 SW_REQ2" | Strength: 90% | Timing: immediate
RULE: IF "PowerHal" THEN "DDR投票 SW_REQ3" | Strength: 70% | Timing: immediate
RULE: IF "DDR投票機制" THEN "DDR5460 elevated" | Strength: 80% | Timing: seconds
RULE: IF "DDR投票機制" THEN "DDR6370 elevated" | Strength: 90% | Timing: seconds
RULE: IF "DDR usage high" THEN "VCORE 725mV超標" | Strength: 95% | Timing: immediate
RULE: IF "MMDVFS OPP3 at 100%" THEN "VCORE 600mV floor" | Strength: 100% | Timing: immediate
RULE: IF "MMDVFS at OPP4" THEN RULES_OUT "VCORE caused by MMDVFS"

## ROOT CAUSES

1. CM (CPU Manager) - Controls CPU frequency, triggers DDR voting via SW_REQ2
2. PowerHal - Affects DDR voting via SW_REQ3
3. 調控策略 (Control Policy) - Drives CM behavior
4. MMDVFS OPP3 - Causes VCORE 600mV floor (when at 100% usage)

## OBSERVABLE SYMPTOMS

- VCORE 725mV usage exceeds 10% threshold
- VCORE 600mV floor (should be 575mV minimum)

## DIAGNOSTIC CHAINS

Chain 1 (Primary - CM Path):
  調控策略 → CM → CPU大核/中核/小核 at ceiling → DDR投票(SW_REQ2) → DDR6370 → DDR usage% → VCORE 725mV

Chain 2 (Secondary - PowerHal Path):
  PowerHal → DDR投票(SW_REQ3) → DDR frequencies → DDR usage% → VCORE 725mV

Chain 3 (MMDVFS Path):
  MMDVFS OPP3 100% → VCORE 600mV floor

## DECISION TREE FOR LLM

```
WHEN observing "VCORE異常":

├── CHECK: Is VCORE 725mV usage > 10%?
│   ├── YES → Continue to step 2
│   └── NO → Check for 600mV floor issue
│
├── CHECK: MMDVFS status
│   ├── IF OPP4 (stable) → MMDVFS RULED OUT, continue
│   └── IF OPP3 at 100% → MMDVFS is CAUSE of 600mV floor
│
├── CHECK: DDR usage (DDR5460% + DDR6370%)
│   ├── IF sum ≈ VCORE% → DDR is proximate cause
│   └── IF sum << VCORE% → Look for other causes
│
├── CHECK: DDR voting mechanism
│   ├── IF SW_REQ2 active → CM (CPU) is root cause
│   ├── IF SW_REQ3 active → PowerHal is contributing
│   └── IF both active → Multiple contributors
│
└── CONFIRM: CPU frequencies
    ├── IF 大核2700MHz/中核2500MHz/小核2100MHz at ceiling → CM confirmed
    └── IF lower frequencies → May be PowerHal only
```

## HISTORICAL CASES

Case 1: VCORE 725mV at 82.6%
- DDR: 82.6% (DDR5460 + DDR6370)
- MMDVFS: OPP4 (ruled out)
- Root Cause: CM - all CPUs at ceiling

Case 2: VCORE 725mV at 29.32%
- DDR: 29.67% (DDR5460 3.54% + DDR6370 26.13%)
- MMDVFS: OPP4 (ruled out)
- SW_REQ2 + SW_REQ3 active
- Root Cause: CM + PowerHal

Case 3: VCORE 725mV at 52.51% + 600mV floor
- DDR: 54.14% (DDR5460 23.37% + DDR6370 30.77%)
- MMDVFS: OPP3 at 100% (causes 600mV floor)
- Root Cause: CM (725mV) + MMDVFS (600mV floor)
