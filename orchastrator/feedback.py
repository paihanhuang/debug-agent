from __future__ import annotations

import json
from typing import Any

from .models import Feedback, StopCriteria


def _find_root_cause_accuracy(case_result: dict[str, Any]) -> float:
    for dim in case_result.get("dimensions", []):
        if dim.get("name") == "Root Cause Accuracy":
            return float(dim.get("score", 0))
    return 0.0


def build_feedback_from_judge_report(
    judge_report_path: str,
    run_id: str,
    iter_num: int,
    stop: StopCriteria,
) -> Feedback:
    data = json.loads(open(judge_report_path, "r", encoding="utf-8").read())

    results = data.get("results", [])
    per_case: dict[str, dict[str, Any]] = {}
    scores: list[float] = []
    acc_scores: list[float] = []

    for r in results:
        case_name = r.get("case_name", "unknown")
        composite = float(r.get("composite_score", 0))
        acc = _find_root_cause_accuracy(r)
        scores.append(composite)
        acc_scores.append(acc)
        per_case[case_name] = {
            "composite_score": composite,
            "grade": r.get("grade", ""),
            "dimensions": [
                {
                    "name": d.get("name", ""),
                    "score": d.get("score", 0),
                    "weight": d.get("weight", 0),
                    "missing_elements": d.get("missing_elements", []),
                    "matched_elements": d.get("matched_elements", []),
                }
                for d in r.get("dimensions", [])
            ],
        }

    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    avg_acc = round(sum(acc_scores) / len(acc_scores), 2) if acc_scores else 0.0

    stop_reached = (avg_acc >= stop.min_accuracy) and (avg_score > stop.min_overall)

    return Feedback(
        run_id=run_id,
        iter_num=iter_num,
        average_score=avg_score,
        accuracy_score=avg_acc,
        per_case=per_case,
        stop_reached=stop_reached,
    )


def build_case_feedback_from_judge_report(
    judge_report_path: str,
    run_id: str,
    iter_num: int,
    stop: StopCriteria,
    case_id: str,
) -> Feedback:
    """Per-case feedback: compute stop criteria using only the requested case."""
    data = json.loads(open(judge_report_path, "r", encoding="utf-8").read())
    results = data.get("results", [])
    match = None
    for r in results:
        if r.get("case_name") == case_id:
            match = r
            break
    if match is None:
        return Feedback(
            run_id=run_id,
            iter_num=iter_num,
            average_score=0.0,
            accuracy_score=0.0,
            per_case={},
            stop_reached=False,
        )

    composite = float(match.get("composite_score", 0))
    acc = float(_find_root_cause_accuracy(match))
    per_case = {
        case_id: {
            "composite_score": composite,
            "grade": match.get("grade", ""),
            "dimensions": [
                {
                    "name": d.get("name", ""),
                    "score": d.get("score", 0),
                    "weight": d.get("weight", 0),
                    "missing_elements": d.get("missing_elements", []),
                    "matched_elements": d.get("matched_elements", []),
                }
                for d in match.get("dimensions", [])
            ],
        }
    }
    stop_reached = (acc >= stop.min_accuracy) and (composite > stop.min_overall)
    return Feedback(
        run_id=run_id,
        iter_num=iter_num,
        average_score=round(composite, 2),
        accuracy_score=round(acc, 2),
        per_case=per_case,
        stop_reached=stop_reached,
    )

