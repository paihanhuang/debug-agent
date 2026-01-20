## Mode
ABSTAIN

## Reason
Insufficient CKG coverage to support grounded diagnosis

## Coverage
{
  "matched_entities_count": 5,
  "root_causes_count": 0,
  "causal_chains_count": 0,
  "relevant_fixes_count": 0,
  "required_nodes_count": 0
}

## Observations (verbatim input)
- VCORE 725mV usage is at 82.6%.
- DDR5460 and DDR6370 combined usage is 82.6%.
- MMDVFS is at OPP4.
- CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz.
- DDR voting shows SW_REQ2 activity.

## Missing Knowledge / Next Data Needed
- CKG grounding missing: root causes and/or causal chains were not found for this input.
- Provide DDR voting signals (SW_REQ2/SW_REQ3) for the same window if available.
- Provide CPU ceiling breakdown by cluster (big/mid/small) and their usage ratios.
- Provide MMDVFS OPP level and its usage distribution.

## Action
{
  "next_step": "REQUEST_MORE_DATA_OR_AUGMENT_CKG",
  "suggested_ckg_augment_inputs": [
    "raw_report",
    "raw_debug_query",
    "agent_output",
    "judge_feedback"
  ]
}
