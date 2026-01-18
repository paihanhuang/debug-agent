from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .feedback import build_feedback_from_judge_report
from .models import CaseSpec, Feedback, IterationPaths, RunConfig


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_case_specs(project_root: Path) -> list[CaseSpec]:
    # Uses the existing data folder as human reports.
    return [
        CaseSpec(case_id="case1", case_num=1, human_report_path=project_root / "data" / "first"),
        CaseSpec(case_id="case2", case_num=2, human_report_path=project_root / "data" / "second"),
        CaseSpec(case_id="case3", case_num=3, human_report_path=project_root / "data" / "third"),
    ]


class ClosedLoopOrchestrator:
    """Closed-loop orchestrator (v0) with dry-run support."""

    def __init__(self, project_root: Path):
        self._root = project_root

    def run(self, config: RunConfig) -> list[Feedback]:
        run_dir = config.output_root / f"run_{config.run_id}"
        if run_dir.exists():
            raise FileExistsError(f"Run folder already exists: {run_dir}")

        _ensure_dir(run_dir)
        inputs_dir = run_dir / "inputs"
        iters_dir = run_dir / "iterations"
        _ensure_dir(inputs_dir)
        _ensure_dir(iters_dir)

        # Snapshot inputs (no overwrite; this is a new run dir)
        _write_text(inputs_dir / "base_ckg.json", Path(config.base_ckg_path).read_text(encoding="utf-8"))
        for case in config.cases:
            _write_text(
                inputs_dir / f"human_report_case_{case.case_num:02d}.txt",
                case.human_report_path.read_text(encoding="utf-8"),
            )

        run_summary = {
            "run_id": config.run_id,
            "created_at": datetime.now().isoformat(),
            "max_iters": config.max_iters,
            "dry_run": config.dry_run,
            "stop": asdict(config.stop),
            "iterations": [],
        }

        feedbacks: list[Feedback] = []
        for iter_num in range(1, config.max_iters + 1):
            paths = self._iteration_paths(iters_dir, iter_num)
            self._init_iteration_dirs(paths)

            if config.dry_run:
                self._dry_run_iteration(config, paths)
            else:
                raise NotImplementedError("Non-dry-run orchestration not implemented in v0.")

            fb = build_feedback_from_judge_report(
                judge_report_path=str(paths.judge_dir / f"judge_qa_report_{paths.iter_tag()}.json"),
                run_id=config.run_id,
                iter_num=iter_num,
                stop=config.stop,
            )
            feedbacks.append(fb)
            _write_json(paths.feedback_dir / f"feedback_{paths.iter_tag()}.json", fb.to_dict())

            run_summary["iterations"].append(
                {
                    "iter": paths.iter_tag(),
                    "average_score": fb.average_score,
                    "accuracy_score": fb.accuracy_score,
                    "stop_reached": fb.stop_reached,
                }
            )

            if fb.stop_reached:
                break

        _write_json(run_dir / "run_summary.json", run_summary)
        return feedbacks

    def _iteration_paths(self, iters_dir: Path, iter_num: int) -> IterationPaths:
        iter_tag = f"iter_{iter_num:04d}"
        iter_dir = iters_dir / iter_tag
        return IterationPaths(
            iter_num=iter_num,
            iter_dir=iter_dir,
            ckg_dir=iter_dir / "ckg",
            agent_dir=iter_dir / "agent",
            judge_dir=iter_dir / "judge",
            feedback_dir=iter_dir / "feedback",
        )

    def _init_iteration_dirs(self, p: IterationPaths) -> None:
        _ensure_dir(p.ckg_dir)
        _ensure_dir(p.agent_dir)
        _ensure_dir(p.judge_dir)
        _ensure_dir(p.feedback_dir)

    def _dry_run_iteration(self, config: RunConfig, paths: IterationPaths) -> None:
        # Candidate CKG: no-op copy of base (v0 contract test)
        candidate_ckg_path = paths.ckg_dir / f"candidate_ckg_{paths.iter_tag()}.json"
        _write_text(candidate_ckg_path, Path(config.base_ckg_path).read_text(encoding="utf-8"))
        _write_json(paths.ckg_dir / f"augmentation_diff_{paths.iter_tag()}.json", {"mode": "dry_run", "changes": []})

        # Agent reports: placeholders that include iteration + case naming contract
        for case in config.cases:
            report_path = paths.agent_dir / f"agent_report_{paths.iter_tag()}_case_{case.case_num:02d}.md"
            _write_text(
                report_path,
                f"""# Agent Report (Dry Run)

- iter: {paths.iter_tag()}
- case: {case.case_id}
""",
            )

        # Production comparison placeholder
        _write_json(
            paths.agent_dir / f"production_comparison_{paths.iter_tag()}.json",
            {"mode": "dry_run", "iter": paths.iter_tag()},
        )

        # Judge report placeholder (synthetic but compatible with feedback parser)
        judge_report = {
            "test_name": "Judge Batch Evaluation (dry run)",
            "timestamp": datetime.now().isoformat(),
            "run_id": config.run_id,
            "total_cases": len(config.cases),
            "judge_model": "synthetic",
            "judge_provider": "synthetic",
            "results": [],
            "summary": {"average_score": 0.0, "grades": {}, "pass_rate": 0.0},
        }

        # Simple synthetic scores for deterministic testing; can be overridden by tests later
        for case in config.cases:
            composite = 8.5
            dims = [
                {"name": "Root Cause Accuracy", "score": 9, "weight": 0.5, "missing_elements": [], "matched_elements": []},
                {"name": "Causal Chain Completeness", "score": 8, "weight": 0.2, "missing_elements": [], "matched_elements": []},
                {"name": "Metric Precision", "score": 8, "weight": 0.15, "missing_elements": [], "matched_elements": []},
                {"name": "Reasoning Quality", "score": 9, "weight": 0.1, "missing_elements": [], "matched_elements": []},
                {"name": "Actionability", "score": 8, "weight": 0.05, "missing_elements": [], "matched_elements": []},
            ]
            judge_report["results"].append(
                {
                    "case_name": case.case_id,
                    "composite_score": composite,
                    "grade": "A",
                    "summary": "synthetic",
                    "dimensions": dims,
                    "human_report_path": str(case.human_report_path),
                    "agent_report_path": str(paths.agent_dir / f"agent_report_{paths.iter_tag()}_case_{case.case_num:02d}.md"),
                    "timestamp": judge_report["timestamp"],
                }
            )
            judge_report["summary"]["grades"][case.case_id] = "A"

        judge_report["summary"]["average_score"] = round(
            sum(r["composite_score"] for r in judge_report["results"]) / len(judge_report["results"]), 2
        )
        judge_report["summary"]["pass_rate"] = 100.0

        _write_json(paths.judge_dir / f"judge_qa_report_{paths.iter_tag()}.json", judge_report)
        _write_json(paths.judge_dir / f"judge_qa_summary_{paths.iter_tag()}.json", judge_report["summary"])

