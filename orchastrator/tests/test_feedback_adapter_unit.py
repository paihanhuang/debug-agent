from __future__ import annotations

from orchastrator.feedback_adapter import judge_result_to_feedback, normalize_missing_element


def test_normalize_missing_element_trims_and_canonicalizes() -> None:
    assert normalize_missing_element(" SW_REQ2 ") == "SW_REQ2"
    assert normalize_missing_element("拉檔 (frequency throttling)") == "拉檔"
    assert normalize_missing_element("frequency throttling") == "拉檔"


def test_judge_result_to_feedback_basic_mapping() -> None:
    judge_result = {
        "case_name": "case2_from_case1",
        "composite_score": 7.75,
        "grade": "B",
        "summary": "ok",
        "dimensions": [
            {
                "name": "Root Cause Accuracy",
                "score": 8,
                "weight": 0.5,
                "explanation": "x",
                "matched_elements": ["CM"],
                "missing_elements": ["拉檔 (frequency throttling)"],
            },
            {
                "name": "Causal Chain Completeness",
                "score": 7,
                "weight": 0.2,
                "missing_elements": [" SW_REQ2 ", "SW_REQ2", "SW_REQ3"],
                "matched_elements": [],
                "explanation": "",
            },
        ],
    }

    fb = judge_result_to_feedback(
        judge_result,
        run_id="r1",
        iter_num=1,
        case_id="case2",
        stop_accuracy=9.0,
        stop_overall=8.0,
    )

    assert fb["run_id"] == "r1"
    assert fb["iter_num"] == 1
    assert fb["average_score"] == 7.75
    assert fb["accuracy_score"] == 8.0
    assert fb["stop_reached"] is False
    assert "per_case" in fb and "case2" in fb["per_case"]

    dims = fb["per_case"]["case2"]["dimensions"]
    # Root Cause Accuracy canonicalized
    assert dims[0]["missing_elements"] == ["拉檔"]
    # Stable de-dup + trim
    assert dims[1]["missing_elements"] == ["SW_REQ2", "SW_REQ3"]


def test_judge_result_to_feedback_stop_criteria_overall_is_gte() -> None:
    judge_result = {
        "composite_score": 8.0,
        "grade": "A",
        "dimensions": [
            {"name": "Root Cause Accuracy", "score": 9, "weight": 0.5, "missing_elements": [], "matched_elements": []}
        ],
    }
    fb = judge_result_to_feedback(
        judge_result,
        run_id="r",
        iter_num=2,
        case_id="case2",
        stop_accuracy=9.0,
        stop_overall=8.0,
    )
    assert fb["stop_reached"] is True

