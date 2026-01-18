from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .models import RunConfig, StopCriteria
from .orchestrator import ClosedLoopOrchestrator, build_case_specs


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="orchastrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run closed-loop orchestration")
    run.add_argument("--run-id", type=str, default=None, help="Run id (default: timestamp)")
    run.add_argument("--max-iters", type=int, default=1, help="Max iterations to run")
    run.add_argument("--dry-run", action="store_true", help="Write synthetic outputs; do not call debug-engine/judge")
    run.add_argument("--output-root", type=str, default="output/closed_loop_runs", help="Root folder for run bundles")
    run.add_argument("--base-ckg", type=str, default="output/full_ckg.json", help="Base CKG JSON path")
    run.add_argument("--per-case", action="store_true", help="Run per-case iterations (case_01..case_03 folders)")
    run.add_argument("--max-iters-per-case", type=int, default=None, help="Max iterations per case (defaults to --max-iters)")
    run.add_argument("--start-from-scratch", action="store_true", help="Start each case from empty CKG (no base CKG)")
    run.add_argument("--judge-provider", choices=["openai", "anthropic"], default="openai", help="Judge provider")
    run.add_argument("--stop-accuracy", type=float, default=9.0, help="Stop when accuracy >= this value")
    run.add_argument("--stop-overall", type=float, default=8.0, help="Stop when overall > this value")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]

    if args.cmd == "run":
        orch = ClosedLoopOrchestrator(project_root)
        run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        stop = StopCriteria(min_accuracy=args.stop_accuracy, min_overall=args.stop_overall)
        cases = build_case_specs(project_root)
        cfg = RunConfig(
            run_id=run_id,
            max_iters=args.max_iters,
            dry_run=bool(args.dry_run),
            output_root=project_root / args.output_root,
            base_ckg_path=project_root / args.base_ckg,
            stop=stop,
            cases=cases,
            per_case=bool(args.per_case),
            max_iters_per_case=args.max_iters_per_case,
            start_from_scratch=bool(args.start_from_scratch),
            judge_provider=str(args.judge_provider),
        )
        orch.run(cfg)
        return 0

    raise RuntimeError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

