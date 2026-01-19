### DebugAgent anti-hallucination plan: abstain gate + observation/hypothesis schema + low-coverage verifier

### Goal
Prevent `DebugAgent` from hallucinating when it encounters **unseen anomalies** or **insufficient CKG coverage**, by adding:
- A deterministic **coverage gate** that can **abstain** (hard stop)
- A strict output schema separating **Observations vs CKG-grounded facts vs Hypotheses**
- An LLM-based **verifier pass**, triggered **only when coverage is low**

---

## 1) Abstain mode (hard stop when coverage is low)

### Inputs
- `input_text` (raw user prompt / metrics)
- `DiagnosisContext` from `Retriever.retrieve()`

### Coverage signals (deterministic)
Compute `CoverageReport`:
- `matched_entities_count = len(context.matched_entities)`
- `root_causes_count = len(context.root_causes)`
- `causal_chains_count = len(context.causal_chains)`
- `required_nodes_count = number of unique node labels across all causal chains`
- `relevant_fixes_count = len(context.relevant_fixes)`
- Optional (if vector store exposes): `top_similarity`

### Default abstain rule (v1)
Hard abstain if any:
- `root_causes_count == 0`
- `causal_chains_count == 0`
(Optional: also if `matched_entities_count == 0`)

### Abstain output (structured)
Return a structured response indicating the system cannot produce a grounded diagnosis:

```json
{
  "mode": "ABSTAIN",
  "reason": "Insufficient CKG coverage to support grounded diagnosis",
  "coverage": {
    "matched_entities_count": 0,
    "root_causes_count": 0,
    "causal_chains_count": 0,
    "relevant_fixes_count": 0
  },
  "observations": ["...quoted input lines..."],
  "missing_knowledge": ["...what information is needed..."],
  "action": {
    "next_step": "REQUEST_MORE_DATA_OR_AUGMENT_CKG",
    "suggested_ckg_augment_inputs": ["raw_report", "raw_debug_query", "agent_output", "judge_feedback"]
  }
}
```

### Benefits / tradeoffs
- **Pros**: strongest hallucination prevention, deterministic, testable
- **Cons**: more “no answer” responses; requires follow-up flow for data/augmentation

---

## 2) Output schema: separate Observations vs Hypotheses (always-on)

### Goal
Make the report’s epistemic status explicit:
- **Observations**: must be grounded in input
- **CKG-grounded facts**: must cite traversal nodes
- **Hypotheses**: explicitly marked as unverified
- **Conclusion**: confidence-limited by coverage

### Recommended internal JSON schema (then render to markdown)
```json
{
  "observations": [
    { "text": "VCORE 725mV usage is 29.32%", "source": "input" }
  ],
  "ckg_grounded_facts": [
    { "text": "SW_REQ2 indicates CM involvement", "source": "ckg", "nodes": ["SW_REQ2", "CM"] }
  ],
  "hypotheses": [
    {
      "text": "CM voting is raising VCORE ceiling",
      "confidence": "low|medium|high",
      "why": ["reasons referencing observations/ckg facts"],
      "what_would_confirm": ["missing evidence to collect"]
    }
  ],
  "conclusion": {
    "root_cause": "CM|PowerHal|MMDVFS|UNKNOWN",
    "confidence": "low|medium|high",
    "justification": ["must cite observations + ckg facts"]
  },
  "next_steps": ["..."],
  "historical_fixes": [
    { "case_id": "fix_x", "fix": "..." }
  ]
}
```

### Enforcement rules
- Observations must be **verbatim grounded** (no invented numbers).
- CKG-grounded facts must include `nodes` references (labels used).
- Hypotheses must not introduce new numeric metrics.
- Conclusion **cannot be high-confidence** unless `root_causes_count>0` and `causal_chains_count>0`.

---

## 3) Verifier pass only when coverage is low

### Goal
When the context is weak, run a second-pass verifier that removes/softens unsupported claims.

### Trigger condition (coverage-low)
Run verifier if any:
- `root_causes_count == 0` OR `causal_chains_count == 0`
- OR `required_nodes_count < MIN_REQUIRED_NODES` (e.g., < 3)
- OR `matched_entities_count == 0`

### Verifier inputs
- draft report (model output)
- extracted observations (verbatim)
- CKG context summary: root causes, causal chains, traversal nodes
- `CoverageReport`

### Verifier output contract
Return JSON:
```json
{
  "status": "OK|NEEDS_REWRITE|ABSTAIN",
  "problems": [
    { "type": "UNSUPPORTED_METRIC", "span": "...", "fix": "remove" },
    { "type": "UNGROUNDED_ROOT_CAUSE", "span": "...", "fix": "downgrade_to_hypothesis" }
  ],
  "rewritten_report": "..."
}
```

### Verifier rules
- If draft asserts a specific root cause but `root_causes_count==0`, verifier must either:
  - return `ABSTAIN`, or
  - rewrite conclusion to `UNKNOWN` + hypotheses.
- If draft includes a metric not in observations, remove it.
- If draft asserts traversal nodes not present in traversal nodes list, convert to hypothesis.

### Benefits / tradeoffs
- **Pros**: reduces confident hallucinations; cost only on low coverage.
- **Cons**: extra latency/cost in low-coverage cases; needs prompt + tests.

---

## Implementation notes

### Where to implement
- Compute `CoverageReport` after `Retriever.retrieve()` in `DebugAgent.diagnose()` (or in `Retriever`).
- Add feature flags (env vars):
  - `ENABLE_ABSTAIN_GATE=true`
  - `ENABLE_LOW_COVERAGE_VERIFIER=true`
  - Thresholds: `ABSTAIN_MIN_ROOT_CAUSES`, `ABSTAIN_MIN_CHAINS`, `MIN_REQUIRED_NODES`
- Implement verifier similarly to existing “metric rewrite” pass: only execute on low coverage.

### Suggested testing (V-model)
- Unit tests for `CoverageReport` and abstain decision logic (no LLM).
- Unit tests for schema enforcement (e.g., no invented metrics).
- Unit tests for verifier trigger/skip logic.
- Verifier pass tests with mocked LLM returning: `OK`, `NEEDS_REWRITE`, `ABSTAIN`.

