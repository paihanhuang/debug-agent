from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def normalize_missing_element(s: str) -> str:
    """Normalize judge 'missing_elements' strings for stable CKG augmentation.

    This avoids creating noisy entity labels like "拉檔 (frequency throttling)".
    """
    s = (s or "").strip()
    if not s:
        return ""

    # Canonicalize common bilingual variants.
    lower = s.lower()
    if "拉檔" in s:
        return "拉檔"
    if "frequency throttling" in lower:
        return "拉檔"

    # Trim parenthetical clarifiers when they are likely just explanations.
    # e.g. "DDR5460 percentage" should remain; only strip if it's a trailing parenthetical.
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    return s


def _dedup_stable(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def judge_result_to_feedback(
    judge_result: dict[str, Any],
    *,
    run_id: str,
    iter_num: int,
    case_id: str,
    stop_accuracy: float,
    stop_overall: float,
    stop_chain_completeness: float = 0.0,
) -> dict[str, Any]:
    """Convert `judge.cli run` JSON into the feedback schema consumed by `ckg-augment`.

    Output schema is intentionally aligned with:
      ckg-augment/ckg_augment/augmenter.py::extract_missing_elements()
    """
    composite = float(judge_result.get("composite_score", 0.0))
    grade = str(judge_result.get("grade", ""))
    dims_in = judge_result.get("dimensions", []) or []

    accuracy = 0.0
    chain = 0.0
    for d in dims_in:
        if d.get("name") == "Root Cause Accuracy":
            accuracy = float(d.get("score", 0.0))
        if d.get("name") == "Causal Chain Completeness":
            chain = float(d.get("score", 0.0))

    # Use user-specified semantics: overall >= threshold.
    stop_reached = (
        (accuracy >= stop_accuracy)
        and (composite >= stop_overall)
        and (chain >= float(stop_chain_completeness))
    )

    dims_out: list[dict[str, Any]] = []
    for d in dims_in:
        missing_raw = d.get("missing_elements", []) or []
        missing_norm = []
        for m in missing_raw:
            if not isinstance(m, str):
                continue
            nm = normalize_missing_element(m)
            if nm:
                missing_norm.append(nm)
        missing_norm = _dedup_stable(missing_norm)

        dims_out.append(
            {
                "name": d.get("name", ""),
                "score": d.get("score", 0),
                "weight": d.get("weight", 0),
                "explanation": d.get("explanation", ""),
                "matched_elements": d.get("matched_elements", []) or [],
                "missing_elements": missing_norm,
            }
        )

    return {
        "run_id": run_id,
        "iter_num": int(iter_num),
        "average_score": round(composite, 2),
        "accuracy_score": round(accuracy, 2),
        "per_case": {
            case_id: {
                "composite_score": round(composite, 2),
                "grade": grade,
                "dimensions": dims_out,
            }
        },
        "stop_reached": bool(stop_reached),
        "stop": {
            "min_accuracy": float(stop_accuracy),
            "min_overall": float(stop_overall),
            "min_causal_chain_completeness": float(stop_chain_completeness),
        },
        "source": {"type": "judge_cli_run", "case_name": judge_result.get("case_name", ""), "timestamp": judge_result.get("timestamp", "")},
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="orchastrator.feedback_adapter")
    p.add_argument("--judge", required=True, help="Path to judge.cli run JSON output")
    p.add_argument("--out", required=True, help="Path to write feedback JSON for ckg-augment")
    p.add_argument("--case-id", required=True, help="Case id key to use in feedback per_case (e.g. case2)")
    p.add_argument("--iter-num", type=int, required=True, help="Iteration number to store in feedback")
    p.add_argument("--run-id", default=None, help="Run id (default: timestamp)")
    p.add_argument("--stop-accuracy", type=float, default=9.0)
    p.add_argument("--stop-overall", type=float, default=8.0)
    p.add_argument("--stop-chain", type=float, default=0.0, help="Minimum Causal Chain Completeness score to stop (default: 0)")
    args = p.parse_args()

    judge_path = Path(args.judge)
    out_path = Path(args.out)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    judge_result = json.loads(judge_path.read_text(encoding="utf-8"))
    feedback = judge_result_to_feedback(
        judge_result,
        run_id=run_id,
        iter_num=int(args.iter_num),
        case_id=str(args.case_id),
        stop_accuracy=float(args.stop_accuracy),
        stop_overall=float(args.stop_overall),
        stop_chain_completeness=float(args.stop_chain),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(feedback, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote feedback: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

