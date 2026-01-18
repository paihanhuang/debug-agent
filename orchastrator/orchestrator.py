from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import os
import shutil
import subprocess

from .feedback import build_case_feedback_from_judge_report, build_feedback_from_judge_report
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
        if config.per_case:
            return self.run_per_case(config)

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

    def run_per_case(self, config: RunConfig) -> list[Feedback]:
        """Run the loop independently for each case.

        Notes:
        - Stores artifacts under `run_<run_id>/case_XX/iterations/iter_XXXX/...`
        - Stop criteria is evaluated per-case.
        """
        run_dir = config.output_root / f"run_{config.run_id}"
        if run_dir.exists():
            raise FileExistsError(f"Run folder already exists: {run_dir}")

        _ensure_dir(run_dir)
        inputs_dir = run_dir / "inputs"
        _ensure_dir(inputs_dir)

        # Snapshot human reports (all cases)
        for case in config.cases:
            _write_text(
                inputs_dir / f"human_report_case_{case.case_num:02d}.txt",
                case.human_report_path.read_text(encoding="utf-8"),
            )

        # Snapshot base CKG (or canonical empty snapshot in scratch mode)
        if config.start_from_scratch:
            _write_json(inputs_dir / "base_ckg_snapshot.json", {"entities": [], "relations": [], "metadata": {}})
        else:
            _write_text(inputs_dir / "base_ckg_snapshot.json", Path(config.base_ckg_path).read_text(encoding="utf-8"))

        max_iters_per_case = config.max_iters_per_case or config.max_iters
        run_summary: dict[str, Any] = {
            "run_id": config.run_id,
            "created_at": datetime.now().isoformat(),
            "per_case": True,
            "dry_run": config.dry_run,
            "max_iters_per_case": max_iters_per_case,
            "stop": asdict(config.stop),
            "cases": {},
        }

        all_feedback: list[Feedback] = []

        for case in config.cases:
            case_tag = f"case_{case.case_num:02d}"
            case_dir = run_dir / case_tag
            iters_dir = case_dir / "iterations"
            _ensure_dir(iters_dir)
            run_summary["cases"][case_tag] = {"case_id": case.case_id, "iterations": []}

            prev_feedback_path: Path | None = None
            for iter_num in range(1, max_iters_per_case + 1):
                iter_tag = f"iter_{iter_num:04d}"
                iter_dir = iters_dir / iter_tag
                paths = IterationPaths(
                    iter_num=iter_num,
                    iter_dir=iter_dir,
                    ckg_dir=iter_dir / "ckg",
                    agent_dir=iter_dir / "agent",
                    judge_dir=iter_dir / "judge",
                    feedback_dir=iter_dir / "feedback",
                )
                self._init_iteration_dirs(paths)

                if config.dry_run:
                    self._dry_run_iteration_per_case(config, case, paths)
                else:
                    self._real_iteration_per_case(config, case, paths, prev_feedback_path)

                judge_report_path = paths.judge_dir / f"judge_qa_report_{iter_tag}_{case_tag}.json"
                fb = build_case_feedback_from_judge_report(
                    judge_report_path=str(judge_report_path),
                    run_id=config.run_id,
                    iter_num=iter_num,
                    stop=config.stop,
                    case_id=case.case_id,
                )
                all_feedback.append(fb)

                feedback_path = paths.feedback_dir / f"feedback_{iter_tag}_{case_tag}.json"
                _write_json(feedback_path, fb.to_dict())
                prev_feedback_path = feedback_path

                run_summary["cases"][case_tag]["iterations"].append(
                    {
                        "iter": iter_tag,
                        "composite_score": fb.average_score,
                        "accuracy_score": fb.accuracy_score,
                        "stop_reached": fb.stop_reached,
                    }
                )

                if fb.stop_reached:
                    break

        _write_json(run_dir / "run_summary.json", run_summary)
        return all_feedback

    def _dry_run_iteration_per_case(self, config: RunConfig, case: CaseSpec, paths: IterationPaths) -> None:
        """Dry-run per-case bundle (for contract testing)."""
        case_tag = f"case_{case.case_num:02d}"
        iter_tag = paths.iter_tag()

        # Candidate CKG: no-op empty or base snapshot
        candidate_ckg_path = paths.ckg_dir / f"candidate_ckg_{iter_tag}_{case_tag}.json"
        if config.start_from_scratch:
            _write_json(candidate_ckg_path, {"entities": [], "relations": [], "metadata": {}})
        else:
            _write_text(candidate_ckg_path, Path(config.base_ckg_path).read_text(encoding="utf-8"))
        _write_json(paths.ckg_dir / f"augmentation_diff_{iter_tag}_{case_tag}.json", {"mode": "dry_run", "case": case_tag})

        # Agent report placeholder (single case)
        report_path = paths.agent_dir / f"agent_report_{iter_tag}_{case_tag}.md"
        _write_text(report_path, f"# Agent Report (Dry Run)\n\n- iter: {iter_tag}\n- case: {case.case_id}\n")
        _write_json(paths.agent_dir / f"production_comparison_{iter_tag}_{case_tag}.json", {"mode": "dry_run"})

        # Judge report placeholder containing all cases (but we store per-case file name)
        judge_report = {
            "test_name": "Judge Batch Evaluation (dry run)",
            "timestamp": datetime.now().isoformat(),
            "run_id": config.run_id,
            "total_cases": 1,
            "judge_model": "synthetic",
            "judge_provider": "synthetic",
            "results": [
                {
                    "case_name": case.case_id,
                    "composite_score": 8.5,
                    "grade": "A",
                    "summary": "synthetic",
                    "dimensions": [
                        {"name": "Root Cause Accuracy", "score": 9, "weight": 0.5, "missing_elements": [], "matched_elements": []},
                        {"name": "Causal Chain Completeness", "score": 8, "weight": 0.2, "missing_elements": [], "matched_elements": []},
                    ],
                }
            ],
            "summary": {"average_score": 8.5, "grades": {case.case_id: "A"}, "pass_rate": 100.0},
        }
        _write_json(paths.judge_dir / f"judge_qa_report_{iter_tag}_{case_tag}.json", judge_report)
        _write_json(paths.judge_dir / f"judge_qa_summary_{iter_tag}_{case_tag}.json", judge_report["summary"])

    def _run_cmd(self, cmd: list[str], env: dict[str, str] | None = None) -> None:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        subprocess.run(cmd, cwd=str(self._root), env=merged_env, check=True)

    def _real_iteration_per_case(
        self,
        config: RunConfig,
        case: CaseSpec,
        paths: IterationPaths,
        prev_feedback_path: Path | None,
    ) -> None:
        """Run real ckg-augment -> debug-engine -> judge for a single case/iteration.

        This is implemented for wiring and unit-tested via mocking `_run_cmd`.
        """
        case_tag = f"case_{case.case_num:02d}"
        iter_tag = paths.iter_tag()

        # 1) Generate candidate CKG
        candidate_ckg_path = paths.ckg_dir / f"candidate_ckg_{iter_tag}_{case_tag}.json"
        diff_path = paths.ckg_dir / f"augmentation_diff_{iter_tag}_{case_tag}.json"

        ckg_cmd = [str(self._root / ".venv" / "bin" / "python"), "-m", "ckg_augment.cli", "--report", str(case.human_report_path)]
        if config.start_from_scratch:
            ckg_cmd += ["--init-empty"]
        else:
            ckg_cmd += ["--ckg", str(config.base_ckg_path)]
        if prev_feedback_path:
            ckg_cmd += ["--feedback", str(prev_feedback_path), "--case", case.case_id]
        ckg_cmd += ["--output", str(candidate_ckg_path), "--diff", str(diff_path)]
        self._run_cmd(ckg_cmd)

        # 2) Run debug-engine E2E (generates all case reports; we will copy only the target case)
        e2e_cmd = [str(self._root / ".venv" / "bin" / "python"), str(self._root / "tests" / "test_e2e_production.py")]
        self._run_cmd(e2e_cmd, env={"CKG_JSON_PATH": str(candidate_ckg_path)})

        # 3) Copy agent outputs for this case into the iteration bundle
        prod_dir = self._root / "output" / "e2e_production"
        src_report = prod_dir / f"agent_report_{case.case_id}.md"
        dst_report = paths.agent_dir / f"agent_report_{iter_tag}_{case_tag}.md"
        dst_report.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_report, dst_report)
        comp_src = prod_dir / "production_comparison_report.json"
        shutil.copyfile(comp_src, paths.agent_dir / f"production_comparison_{iter_tag}_{case_tag}.json")

        # 4) Run judge batch with OpenAI and capture outputs
        judge_cmd = [str(self._root / ".venv" / "bin" / "python"), "-m", "judge.cli", "batch", "--provider", config.judge_provider]
        self._run_cmd(judge_cmd)

        # Copy latest judge report from judge/qa_results into iteration folder and filter later in feedback
        qa_dir = self._root / "judge" / "qa_results"
        reports = sorted(qa_dir.glob("judge_qa_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not reports:
            raise FileNotFoundError("No judge report found in judge/qa_results")
        latest = reports[0]
        shutil.copyfile(latest, paths.judge_dir / f"judge_qa_report_{iter_tag}_{case_tag}.json")
        latest_summary = qa_dir / "latest_qa_summary.json"
        if latest_summary.exists():
            shutil.copyfile(latest_summary, paths.judge_dir / f"judge_qa_summary_{iter_tag}_{case_tag}.json")

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

