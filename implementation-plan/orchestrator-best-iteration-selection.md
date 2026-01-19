# Orchestrator: Best-Iteration Selection (Accuracy → Overall → Chain)

## Goal
During a single-case closed-loop run (up to `max_iters`), select the **best** iteration’s artifacts as the “final” outputs to:

- carry forward as the base CKG/FixDB for the next case
- report to the user as the run’s best result

This prevents a “bad last iteration” from poisoning the next case.

## Definition of “Best”
We define a strict, deterministic total order using a lexicographic rank key:

\[
( \textbf{accuracy},\ \textbf{overall},\ \textbf{causal\_chain\_completeness} )
\]

- **Primary**: Root Cause Accuracy (higher is better)
- **Secondary**: Overall composite score (higher is better)
- **Tertiary**: Causal Chain Completeness (higher is better)

### Tie-breakers (deterministic)
If the rank tuple is equal:

- **Tie-break 1**: earlier iteration wins (smaller `iter_num`) to reduce churn
- **Tie-break 2 (optional)**: smaller augmentation diff wins (fewer added entities + relations) for stability

## Where to Implement
Implement in `orchastrator/case_loop.py` (single-case runner), since it owns:

- iteration lifecycle and folders
- judge evaluation
- stop criteria
- carry-forward outputs

## Artifact Contract
Per-iteration artifacts remain unchanged under:

`case_XX/iterations/iter_000k/...`

Add a “best” bundle under:

`case_XX/best/iter_000k/...`

And write a pointer file:

`case_XX/best/best.json`

### best.json schema
```json
{
  "best_iter": 3,
  "ranking": {"accuracy": 9, "overall": 8.75, "causal_chain_completeness": 8},
  "tie_break": {"prefer_earlier_iter": true, "prefer_smaller_diff": true},
  "paths": {
    "ckg": ".../best/iter_0003/ckg/best_ckg.json",
    "fix_db": ".../best/iter_0003/fix/best_fixdb.db",
    "judge": ".../best/iter_0003/judge/best_judge.json",
    "feedback": ".../best/iter_0003/feedback/best_feedback.json",
    "agent_report": ".../best/iter_0003/agent/best_agent_report.md"
  }
}
```

### No-overwrite guarantee
Because each run has a unique `run_id`, `case_XX/best/` is safe to create once. If it exists, the runner must fail fast.

## Runtime Algorithm
Maintain an in-memory `best_candidate`:

For each iteration:

1. Augment CKG (+ diff)
2. Run DebugAgent
3. Judge
4. Extract scores:
   - accuracy = score("Root Cause Accuracy")
   - overall = judge.composite_score
   - chain = score("Causal Chain Completeness")
5. Compute rank = `(accuracy, overall, chain)`
6. Compare against best:
   - if rank is better → update best
   - if rank ties → apply tie-breakers
7. Evaluate stop criteria (accuracy/overall/chain thresholds) — stop may trigger early

At the end, persist the best bundle by copying the best iteration’s artifacts into `case_XX/best/...`, then use those paths as the case’s final outputs.

### Important behavioral choice
- **Within-case iteration** continues from previous iteration’s CKG (exploration).
- **End-of-case export/carry-forward** uses **best iteration**.

## CLI / Config
Add flags to `orchastrator.case_loop`:

- `--select-best/--no-select-best` (default: select best)
- `--best-order accuracy,overall,chain` (default as required; keep future-proof)
- `--best-tiebreak earlier_iter,smaller_diff` (default: earlier_iter)

## Tests (V-model)
Use dry-run mode to drive deterministic judge scores, validate:

- Accuracy dominates overall/chain
- Overall breaks ties on accuracy
- Chain breaks ties on accuracy+overall
- Tie-breaker selects earlier iteration on exact ties
- (Optional) smaller diff wins if earlier-iter tie-break disabled

