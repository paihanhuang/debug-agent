"""Single-case closed-loop runner.

This is a pragmatic E2E harness to iterate CKG optimization for ONE case:
- Read human expert report + appended prompt from a single data file (e.g. data/first)
- Start from an empty CKG (scratch)
- Iterate:
  1) ckg-augment (optionally with feedback from previous iteration)
  2) DebugAgent diagnosis using the iteration CKG
  3) judge single-case evaluation (detailed JSON)
  4) Convert judge result into orchestrator-style feedback for the next augmentation

Stop when:
- Root Cause Accuracy >= stop_accuracy AND Overall (composite) >= stop_overall
  OR
- max_iters reached

Artifacts are written under output/closed_loop_runs/ and are git-ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _extract_case1_prompt_and_report(data_path: Path) -> tuple[str, str]:
    """Return (prompt_query, human_report_text) extracted from data/first-like files."""
    raw = data_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Find the query marker.
    marker_idx = None
    for i, line in enumerate(lines):
        if "E2E Test Query" in line:
            marker_idx = i
            break
    if marker_idx is None:
        raise ValueError(f"Could not find E2E query marker in: {data_path}")

    # Human report: everything before a separator line preceding the marker (best effort).
    # In our data files, '---' exists right before the marker.
    report_end = marker_idx
    for j in range(marker_idx - 1, -1, -1):
        if lines[j].strip() == "---":
            report_end = j
            break
    human_report = "\n".join(lines[:report_end]).strip()

    # Prompt: everything after the marker line.
    prompt = "\n".join(lines[marker_idx + 1 :]).strip()
    if not prompt:
        raise ValueError(f"E2E query section is empty in: {data_path}")
    if not human_report:
        raise ValueError(f"Human report section is empty in: {data_path}")
    return prompt, human_report


def _judge_to_feedback(
    *,
    judge_result: dict[str, Any],
    run_id: str,
    iter_num: int,
    case_id: str,
    stop_accuracy: float,
    stop_overall: float,
) -> dict[str, Any]:
    dims = judge_result.get("dimensions", []) or []
    accuracy = 0.0
    for d in dims:
        if d.get("name") == "Root Cause Accuracy":
            accuracy = float(d.get("score", 0))
            break
    composite = float(judge_result.get("composite_score", 0.0))

    # IMPORTANT: user requested overall >= threshold (not strictly >).
    stop_reached = (accuracy >= stop_accuracy) and (composite >= stop_overall)

    # Shape this as orchestrator Feedback so ckg-augment can consume it.
    per_case = {
        case_id: {
            "composite_score": composite,
            "grade": judge_result.get("grade", ""),
            "dimensions": [
                {
                    "name": d.get("name", ""),
                    "score": d.get("score", 0),
                    "weight": d.get("weight", 0),
                    "missing_elements": d.get("missing_elements", []),
                    "matched_elements": d.get("matched_elements", []),
                    "explanation": d.get("explanation", ""),
                }
                for d in dims
            ],
        }
    }

    return {
        "run_id": run_id,
        "iter_num": iter_num,
        "average_score": round(composite, 2),
        "accuracy_score": round(accuracy, 2),
        "per_case": per_case,
        "stop_reached": stop_reached,
        "stop": {"min_accuracy": stop_accuracy, "min_overall": stop_overall},
    }


def _run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(cmd, cwd=str(cwd), env=merged, check=True)


def main() -> int:
    p = argparse.ArgumentParser(prog="single-case-loop")
    p.add_argument("--data", default="data/first", help="Path to data file containing human report + E2E query")
    p.add_argument("--case-id", default="case1", help="Case id used in feedback/judge")
    p.add_argument("--max-iters", type=int, default=5)
    p.add_argument("--stop-accuracy", type=float, default=9.0)
    p.add_argument("--stop-overall", type=float, default=8.0)
    p.add_argument("--judge-provider", choices=["openai", "anthropic"], default="openai")
    p.add_argument("--run-id", default=None, help="Run id (default: timestamp)")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    # Best-effort load of `.env` so OPENAI_API_KEY can live there.
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(project_root / ".env")
    except Exception:
        pass

    # Import DebugAgent in-process (debug-engine isn't installed as a package).
    import sys

    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "debug-engine" / "src"))
    from graphrag.agent import DebugAgent  # type: ignore
    data_path = (project_root / args.data).resolve()

    prompt, human_report = _extract_case1_prompt_and_report(data_path)

    run_id = args.run_id or f"case1_scratch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = project_root / "output" / "closed_loop_runs" / f"run_{run_id}"
    if run_dir.exists():
        raise FileExistsError(f"Run folder already exists: {run_dir}")

    # Folder contract: keep consistent with per-case orchestrator layout
    case_tag = "case_01"
    iters_dir = run_dir / case_tag / "iterations"
    inputs_dir = run_dir / "inputs"
    _ensure_dir(iters_dir)
    _ensure_dir(inputs_dir)

    _write_text(inputs_dir / "data_source.txt", str(data_path))
    _write_text(inputs_dir / "human_report_case_01.txt", human_report)
    _write_text(inputs_dir / "prompt_case_01.txt", prompt)

    prev_feedback_path: Path | None = None

    final_judge_path: Path | None = None
    for iter_num in range(1, int(args.max_iters) + 1):
        iter_tag = f"iter_{iter_num:04d}"
        iter_dir = iters_dir / iter_tag
        ckg_dir = iter_dir / "ckg"
        agent_dir = iter_dir / "agent"
        judge_dir = iter_dir / "judge"
        feedback_dir = iter_dir / "feedback"
        for d in (ckg_dir, agent_dir, judge_dir, feedback_dir):
            _ensure_dir(d)

        # 1) Augment CKG (scratch) with optional feedback.
        candidate_ckg = ckg_dir / f"candidate_ckg_{iter_tag}_{case_tag}.json"
        diff_path = ckg_dir / f"augmentation_diff_{iter_tag}_{case_tag}.json"

        ckg_cmd = [
            str(project_root / ".venv" / "bin" / "python"),
            "-m",
            "ckg_augment.cli",
            "--report",
            str(data_path),
            "--init-empty",
            "--output",
            str(candidate_ckg),
            "--diff",
            str(diff_path),
            "--case",
            args.case_id,
        ]
        if prev_feedback_path:
            ckg_cmd += ["--feedback", str(prev_feedback_path)]
        _run_cmd(ckg_cmd, cwd=project_root)

        # 2) Run DebugAgent for this single prompt (write a per-iter agent report).
        agent_report_path = agent_dir / f"agent_report_{iter_tag}_{case_tag}.md"
        ckg_data = json.loads(candidate_ckg.read_text(encoding="utf-8"))
        agent = DebugAgent(
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
            fix_db_path=str(agent_dir / "fixes.db"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
        with agent:
            agent.load_ckg(ckg_data)
            # Keep fixes empty for a clean scratch simulation.
            res = agent.diagnose(prompt)
            agent_report_path.write_text(res.raw_response, encoding="utf-8")

        # 3) Judge the agent report vs the extracted human report (single-case detailed JSON).
        judge_out = judge_dir / f"judge_result_{iter_tag}_{case_tag}.json"
        _run_cmd(
            [
                str(project_root / ".venv" / "bin" / "python"),
                "-m",
                "judge.cli",
                "run",
                "--provider",
                args.judge_provider,
                "--human-report",
                str(inputs_dir / "human_report_case_01.txt"),
                "--agent-report",
                str(agent_report_path),
                "--case-name",
                f"{args.case_id}_{iter_tag}",
                "--output",
                str(judge_out),
            ],
            cwd=project_root,
        )
        final_judge_path = judge_out

        judge_result = json.loads(judge_out.read_text(encoding="utf-8"))
        feedback = _judge_to_feedback(
            judge_result=judge_result,
            run_id=run_id,
            iter_num=iter_num,
            case_id=args.case_id,
            stop_accuracy=float(args.stop_accuracy),
            stop_overall=float(args.stop_overall),
        )

        feedback_path = feedback_dir / f"feedback_{iter_tag}_{case_tag}.json"
        feedback_path.write_text(json.dumps(feedback, indent=2, ensure_ascii=False), encoding="utf-8")
        prev_feedback_path = feedback_path

        # Console progress (high-signal)
        print(
            f"[{iter_tag}] composite={feedback['average_score']} "
            f"accuracy={feedback['accuracy_score']} stop={feedback['stop_reached']}\n"
        )

        if feedback["stop_reached"]:
            break

    # Print final judge detailed comments (dimensions explanations + missing elements)
    if final_judge_path:
        final = json.loads(final_judge_path.read_text(encoding="utf-8"))
        print("\n" + "=" * 70)
        print("FINAL JUDGE COMMENTS")
        print("=" * 70)
        print(
            f"Case: {final.get('case_name')}\n"
            f"Composite: {final.get('composite_score')}/10 (Grade: {final.get('grade')})"
        )
        print(f"Summary: {final.get('summary')}\n")
        for d in final.get("dimensions", []) or []:
            print(f"- {d.get('name')}: {d.get('score')}/10 (weight: {int(float(d.get('weight', 0)) * 100)}%)")
            if d.get("explanation"):
                print(f"  Explanation: {d.get('explanation')}")
            if d.get("matched_elements"):
                print(f"  Matched: {d.get('matched_elements')}")
            if d.get("missing_elements"):
                print(f"  Missing: {d.get('missing_elements')}")
        print(f"\nRun folder: {run_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

