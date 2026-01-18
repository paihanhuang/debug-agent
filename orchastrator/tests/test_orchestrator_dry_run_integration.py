from __future__ import annotations

import json
from pathlib import Path

from orchastrator.models import CaseSpec, RunConfig, StopCriteria
from orchastrator.orchestrator import ClosedLoopOrchestrator


def _write_min_ckg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entities": [], "relations": [], "metadata": {}}, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_dry_run_creates_full_iteration_bundle(tmp_path: Path) -> None:
    project_root = tmp_path
    out_root = project_root / "output" / "closed_loop_runs"
    base_ckg = project_root / "output" / "full_ckg.json"
    _write_min_ckg(base_ckg)

    _write_text(project_root / "data" / "first", "case1 report")
    _write_text(project_root / "data" / "second", "case2 report")
    _write_text(project_root / "data" / "third", "case3 report")

    cases = [
        CaseSpec(case_id="case1", case_num=1, human_report_path=project_root / "data" / "first"),
        CaseSpec(case_id="case2", case_num=2, human_report_path=project_root / "data" / "second"),
        CaseSpec(case_id="case3", case_num=3, human_report_path=project_root / "data" / "third"),
    ]

    cfg = RunConfig(
        run_id="dryrun",
        max_iters=1,
        dry_run=True,
        output_root=out_root,
        base_ckg_path=base_ckg,
        stop=StopCriteria(min_accuracy=9.0, min_overall=8.0),
        cases=cases,
    )

    orch = ClosedLoopOrchestrator(project_root)
    feedbacks = orch.run(cfg)
    assert len(feedbacks) == 1

    run_dir = out_root / "run_dryrun"
    iter_dir = run_dir / "iterations" / "iter_0001"

    expected = [
        iter_dir / "ckg" / "candidate_ckg_iter_0001.json",
        iter_dir / "ckg" / "augmentation_diff_iter_0001.json",
        iter_dir / "agent" / "agent_report_iter_0001_case_01.md",
        iter_dir / "agent" / "agent_report_iter_0001_case_02.md",
        iter_dir / "agent" / "agent_report_iter_0001_case_03.md",
        iter_dir / "agent" / "production_comparison_iter_0001.json",
        iter_dir / "judge" / "judge_qa_report_iter_0001.json",
        iter_dir / "judge" / "judge_qa_summary_iter_0001.json",
        iter_dir / "feedback" / "feedback_iter_0001.json",
        run_dir / "run_summary.json",
    ]

    for p in expected:
        assert p.exists(), f"missing expected artifact: {p}"

