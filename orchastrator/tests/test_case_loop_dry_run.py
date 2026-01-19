from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_case_loop_dry_run_stops_at_iter_1(tmp_path: Path) -> None:
    from orchastrator.case_loop import CaseLoopConfig, run_case_loop

    data = tmp_path / "data_case2.txt"
    data.write_text(
        "human report line\n---\nE2E Test Query (judgement-free):\nVCORE 725mV usage is at 29.32%.\n",
        encoding="utf-8",
    )

    cfg = CaseLoopConfig(
        run_id="t_run_1",
        case_id="case2",
        case_num=2,
        data_path=data,
        output_root=tmp_path / "out",
        max_iters=5,
        stop_accuracy=9.0,
        stop_overall=8.0,
        stop_chain=8.0,
        dry_run=True,
        dry_run_stop_iter=1,
        start_from_scratch=True,
        base_ckg_path=None,
        base_fix_db_path=None,
        judge_provider="openai",
    )

    run_dir = run_case_loop(cfg)
    iters = sorted((run_dir / "case_02" / "iterations").glob("iter_*"))
    assert len(iters) == 1

    fb_path = iters[0] / "feedback" / "feedback_iter_0001_case_02.json"
    fb = json.loads(fb_path.read_text(encoding="utf-8"))
    assert fb["stop_reached"] is True
    assert (iters[0] / "fix" / "fixes_iter_0001_case_02.db").exists()


def test_case_loop_dry_run_stops_at_iter_3(tmp_path: Path) -> None:
    from orchastrator.case_loop import CaseLoopConfig, run_case_loop

    data = tmp_path / "data_case2.txt"
    data.write_text(
        "human report line\n---\nE2E Test Query (judgement-free):\nVCORE 725mV usage is at 29.32%.\n",
        encoding="utf-8",
    )

    cfg = CaseLoopConfig(
        run_id="t_run_3",
        case_id="case2",
        case_num=2,
        data_path=data,
        output_root=tmp_path / "out",
        max_iters=5,
        stop_accuracy=9.0,
        stop_overall=8.0,
        stop_chain=8.0,
        dry_run=True,
        dry_run_stop_iter=3,
        start_from_scratch=True,
        base_ckg_path=None,
        base_fix_db_path=None,
        judge_provider="openai",
    )

    run_dir = run_case_loop(cfg)
    iters = sorted((run_dir / "case_02" / "iterations").glob("iter_*"))
    assert len(iters) == 3

    fb2 = json.loads((iters[1] / "feedback" / "feedback_iter_0002_case_02.json").read_text(encoding="utf-8"))
    assert fb2["stop_reached"] is False
    fb3 = json.loads((iters[2] / "feedback" / "feedback_iter_0003_case_02.json").read_text(encoding="utf-8"))
    assert fb3["stop_reached"] is True
    assert (iters[2] / "fix" / "fixes_iter_0003_case_02.db").exists()


def test_case_loop_no_overwrite(tmp_path: Path) -> None:
    from orchastrator.case_loop import CaseLoopConfig, run_case_loop

    data = tmp_path / "data_case2.txt"
    data.write_text(
        "human report line\n---\nE2E Test Query (judgement-free):\nVCORE 725mV usage is at 29.32%.\n",
        encoding="utf-8",
    )

    cfg = CaseLoopConfig(
        run_id="t_run_no_overwrite",
        case_id="case2",
        case_num=2,
        data_path=data,
        output_root=tmp_path / "out",
        max_iters=1,
        stop_accuracy=9.0,
        stop_overall=8.0,
        stop_chain=8.0,
        dry_run=True,
        dry_run_stop_iter=1,
        start_from_scratch=True,
        base_ckg_path=None,
        base_fix_db_path=None,
        judge_provider="openai",
    )

    run_dir = cfg.output_root / f"run_{cfg.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileExistsError):
        run_case_loop(cfg)


def test_case_loop_base_ckg_snapshot_written(tmp_path: Path) -> None:
    from orchastrator.case_loop import CaseLoopConfig, run_case_loop

    data = tmp_path / "data_case2.txt"
    data.write_text(
        "human report line\n---\nE2E Test Query (judgement-free):\nVCORE 725mV usage is at 29.32%.\n",
        encoding="utf-8",
    )

    base_ckg = tmp_path / "base_ckg.json"
    base_ckg.write_text(json.dumps({"entities": [], "relations": [], "metadata": {"x": 1}}), encoding="utf-8")

    cfg = CaseLoopConfig(
        run_id="t_run_base",
        case_id="case2",
        case_num=2,
        data_path=data,
        output_root=tmp_path / "out",
        max_iters=1,
        stop_accuracy=9.0,
        stop_overall=8.0,
        stop_chain=8.0,
        dry_run=True,
        dry_run_stop_iter=1,
        start_from_scratch=False,
        base_ckg_path=base_ckg,
        base_fix_db_path=None,
        judge_provider="openai",
    )

    run_dir = run_case_loop(cfg)
    snap = json.loads((run_dir / "inputs" / "base_ckg_snapshot.json").read_text(encoding="utf-8"))
    assert snap.get("metadata", {}).get("x") == 1

