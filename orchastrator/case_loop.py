from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .feedback_adapter import judge_result_to_feedback


@dataclass(frozen=True)
class CaseLoopConfig:
    run_id: str
    case_id: str  # case1|case2|case3
    case_num: int  # 1..99 used for folder naming
    data_path: Path  # points to data/<case> file containing human report + prompt
    output_root: Path
    max_iters: int
    stop_accuracy: float
    stop_overall: float
    judge_provider: str

    # Start mode
    start_from_scratch: bool
    base_ckg_path: Path | None
    base_fix_db_path: Path | None

    # Testability
    dry_run: bool = False
    dry_run_stop_iter: int = 1


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_prompt_and_human_report(data_path: Path) -> tuple[str, str]:
    raw = data_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    marker = None
    for i, l in enumerate(lines):
        if "E2E Test Query" in l:
            marker = i
            break
    if marker is None:
        raise ValueError(f"Could not find E2E Test Query marker in {data_path}")

    report_end = marker
    for j in range(marker - 1, -1, -1):
        if lines[j].strip() == "---":
            report_end = j
            break

    human_report = "\n".join(lines[:report_end]).strip()
    prompt = "\n".join(lines[marker + 1 :]).strip()
    if not human_report:
        raise ValueError(f"Human report section empty in {data_path}")
    if not prompt:
        raise ValueError(f"Prompt section empty in {data_path}")
    return prompt, human_report


def run_case_loop(cfg: CaseLoopConfig) -> Path:
    """Run a single-case closed-loop iteration bundle and return the run directory."""
    run_dir = cfg.output_root / f"run_{cfg.run_id}"
    if run_dir.exists():
        raise FileExistsError(f"Run folder already exists: {run_dir}")
    if cfg.start_from_scratch and cfg.base_fix_db_path is not None:
        raise ValueError("base_fix_db_path must be None when start_from_scratch=True")

    case_tag = f"case_{cfg.case_num:02d}"
    iters_dir = run_dir / case_tag / "iterations"
    inputs_dir = run_dir / "inputs"
    _ensure_dir(iters_dir)
    _ensure_dir(inputs_dir)

    prompt, human_report = _extract_prompt_and_human_report(cfg.data_path)
    _write_text(inputs_dir / f"human_report_{case_tag}.txt", human_report)
    _write_text(inputs_dir / f"prompt_{case_tag}.txt", prompt)
    _write_text(inputs_dir / "data_source.txt", str(cfg.data_path))

    # Snapshot base CKG (or canonical empty snapshot)
    if cfg.start_from_scratch:
        _write_json(inputs_dir / "base_ckg_snapshot.json", {"entities": [], "relations": [], "metadata": {}})
        base_ckg_path = None
        # Snapshot empty fix DB (schema-only) for traceability
        base_fix_db_path = None
        _init_empty_fix_db(inputs_dir / "base_fix_db_snapshot.db")
    else:
        if not cfg.base_ckg_path:
            raise ValueError("base_ckg_path required when start_from_scratch=False")
        _write_text(inputs_dir / "base_ckg_snapshot.json", cfg.base_ckg_path.read_text(encoding="utf-8"))
        base_ckg_path = cfg.base_ckg_path
        base_fix_db_path = cfg.base_fix_db_path
        if base_fix_db_path:
            (inputs_dir / "base_fix_db_snapshot.db").write_bytes(base_fix_db_path.read_bytes())

    prev_feedback_path: Path | None = None
    prev_ckg_path: Path | None = base_ckg_path
    prev_fix_db_path: Path | None = base_fix_db_path

    for iter_num in range(1, cfg.max_iters + 1):
        iter_tag = f"iter_{iter_num:04d}"
        iter_dir = iters_dir / iter_tag
        ckg_dir = iter_dir / "ckg"
        agent_dir = iter_dir / "agent"
        judge_dir = iter_dir / "judge"
        feedback_dir = iter_dir / "feedback"
        fix_dir = iter_dir / "fix"
        for d in (ckg_dir, agent_dir, judge_dir, feedback_dir, fix_dir):
            _ensure_dir(d)

        candidate_ckg = ckg_dir / f"candidate_ckg_{iter_tag}_{case_tag}.json"
        diff_path = ckg_dir / f"augmentation_diff_{iter_tag}_{case_tag}.json"
        agent_report = agent_dir / f"agent_report_{iter_tag}_{case_tag}.md"
        judge_result = judge_dir / f"judge_result_{iter_tag}_{case_tag}.json"
        feedback_path = feedback_dir / f"feedback_{iter_tag}_{case_tag}.json"
        fix_db_path = fix_dir / f"fixes_{iter_tag}_{case_tag}.db"
        fix_db_diff = fix_dir / f"fix_db_diff_{iter_tag}_{case_tag}.json"

        if cfg.dry_run:
            # Deterministic synthetic artifacts for tests.
            # Candidate CKG: minimal placeholder; feedback iteration is what matters for contract tests.
            _write_json(
                candidate_ckg,
                {
                    "entities": [],
                    "relations": [],
                    "metadata": {"mode": "dry_run", "iter": iter_tag, "case": cfg.case_id},
                },
            )
            _write_json(diff_path, {"mode": "dry_run", "iter": iter_tag, "case": cfg.case_id})
            _write_text(agent_report, f"# Agent Report (dry-run)\n\n- iter: {iter_tag}\n- case: {cfg.case_id}\n")
            _init_empty_fix_db(fix_db_path)
            _write_json(fix_db_diff, {"mode": "dry_run", "iter": iter_tag, "case": cfg.case_id})

            # Synthetic judge result: below threshold until dry_run_stop_iter
            reached = iter_num >= int(cfg.dry_run_stop_iter)
            acc = cfg.stop_accuracy if reached else max(0.0, cfg.stop_accuracy - 1.0)
            overall = cfg.stop_overall if reached else max(0.0, cfg.stop_overall - 1.0)
            judge_payload = {
                "case_name": f"{cfg.case_id}_{iter_tag}",
                "composite_score": round(float(overall), 2),
                "grade": "A" if overall >= 8 else "B",
                "summary": "synthetic",
                "dimensions": [
                    {
                        "name": "Root Cause Accuracy",
                        "score": int(round(acc)),
                        "weight": 0.5,
                        "explanation": "synthetic",
                        "matched_elements": [],
                        "missing_elements": [],
                    }
                ],
                "human_report_path": str(inputs_dir / f"human_report_{case_tag}.txt"),
                "agent_report_path": str(agent_report),
                "timestamp": datetime.now().isoformat(),
            }
            _write_json(judge_result, judge_payload)

            feedback = judge_result_to_feedback(
                judge_payload,
                run_id=cfg.run_id,
                iter_num=iter_num,
                case_id=cfg.case_id,
                stop_accuracy=float(cfg.stop_accuracy),
                stop_overall=float(cfg.stop_overall),
            )
            _write_json(feedback_path, feedback)

            prev_feedback_path = feedback_path
            prev_ckg_path = candidate_ckg
            prev_fix_db_path = fix_db_path

            if feedback["stop_reached"]:
                break
            continue

        # ----------------------------
        # Real mode: run the full loop
        # ----------------------------
        # 1) ckg-augment: base is previous candidate (or provided base for iter_0001)
        ckg_cmd = [str(Path(sys_exe())), "-m", "ckg_augment.cli", "--report", str(cfg.data_path)]
        if prev_ckg_path is None:
            ckg_cmd += ["--init-empty"]
        else:
            ckg_cmd += ["--ckg", str(prev_ckg_path)]
        if prev_feedback_path is not None:
            ckg_cmd += ["--feedback", str(prev_feedback_path)]
        if prev_fix_db_path is not None:
            ckg_cmd += ["--fix-db", str(prev_fix_db_path)]
        ckg_cmd += ["--case", cfg.case_id, "--output", str(candidate_ckg), "--diff", str(diff_path)]
        ckg_cmd += ["--fix-db-out", str(fix_db_path), "--fix-db-diff", str(fix_db_diff)]
        _run_cmd(ckg_cmd, cwd=Path.cwd())

        # 2) DebugAgent: load ckg + diagnose prompt
        _run_debug_agent(
            project_root=Path.cwd(),
            ckg_path=candidate_ckg,
            prompt=prompt,
            agent_report_path=agent_report,
            fix_db_path=fix_db_path,
        )

        # 3) Judge (single-case) → JSON
        judge_cmd = [
            str(Path(sys_exe())),
            "-m",
            "judge.cli",
            "run",
            "--provider",
            cfg.judge_provider,
            "--human-report",
            str(inputs_dir / f"human_report_{case_tag}.txt"),
            "--agent-report",
            str(agent_report),
            "--case-name",
            f"{cfg.case_id}_{iter_tag}",
            "--output",
            str(judge_result),
        ]
        _run_cmd(judge_cmd, cwd=Path.cwd())

        # 4) Convert judge → feedback (ckg-augment schema)
        judge_obj = json.loads(judge_result.read_text(encoding="utf-8"))
        fb = judge_result_to_feedback(
            judge_obj,
            run_id=cfg.run_id,
            iter_num=iter_num,
            case_id=cfg.case_id,
            stop_accuracy=float(cfg.stop_accuracy),
            stop_overall=float(cfg.stop_overall),
        )
        _write_json(feedback_path, fb)

        prev_feedback_path = feedback_path
        prev_ckg_path = candidate_ckg
        prev_fix_db_path = fix_db_path

        if fb["stop_reached"]:
            break

    # Always visualize the final candidate CKG for convenience (HTML, vis-network).
    try:
        last_iter = sorted(iters_dir.glob("iter_*"))[-1]
        last_ckg = next((last_iter / "ckg").glob("candidate_ckg_*.json"))
        out_html = last_iter / "ckg" / f"ckg_visualization_{last_iter.name}_{case_tag}.html"
        _write_ckg_visualization(last_ckg, out_html, title=f"CKG Visualization ({cfg.case_id} {last_iter.name})")
    except Exception:
        pass

    return run_dir


def sys_exe() -> str:
    # Prefer the venv python when available (repo standard), else fall back.
    venv = Path.cwd() / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else "python3"


def _run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(cmd, cwd=str(cwd), env=merged, check=True)


def _run_debug_agent(
    *,
    project_root: Path,
    ckg_path: Path,
    prompt: str,
    agent_report_path: Path,
    fix_db_path: Path,
) -> None:
    # Load .env so OPENAI_API_KEY is available.
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(project_root / ".env")
    except Exception:
        pass

    # debug-engine isn't installed; extend sys.path.
    import sys

    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "debug-engine" / "src"))

    from graphrag.agent import DebugAgent  # type: ignore

    ckg = json.loads(ckg_path.read_text(encoding="utf-8"))
    agent = DebugAgent(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        fix_db_path=str(fix_db_path),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    with agent:
        agent.load_ckg(ckg)
        res = agent.diagnose(prompt)
        agent_report_path.write_text(res.raw_response, encoding="utf-8")


def _init_empty_fix_db(path: Path) -> None:
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_fixes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                root_cause TEXT NOT NULL,
                symptom_summary TEXT,
                metrics_json TEXT,
                fix_description TEXT NOT NULL,
                resolution_notes TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_root_cause
            ON historical_fixes(root_cause)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _write_ckg_visualization(ckg_json: Path, out_html: Path, title: str) -> None:
    data = json.loads(ckg_json.read_text(encoding="utf-8"))
    entities = data.get("entities", []) or []
    relations = data.get("relations", []) or []

    type_colors = {
        "RootCause": "#ff6b6b",
        "Symptom": "#ffa94d",
        "Component": "#74c0fc",
        "Metric": "#69db7c",
        "Hypothesis": "#ffd43b",
        "Action": "#adb5bd",
        "Observation": "#f1f3f5",
        "Conclusion": "#f783ac",
    }

    nodes = []
    for e in entities:
        eid = e.get("id")
        etype = e.get("type") or e.get("entity_type") or "Unknown"
        label = e.get("label") or eid
        desc = e.get("description") or ""
        src = e.get("source_text") or ""
        tip = (desc + ("\n\nsource_text: " + src if src else "")).strip() or label
        nodes.append(
            {
                "id": eid,
                "label": f"{label}\n({etype})",
                "group": etype,
                "color": type_colors.get(etype, "#e9ecef"),
                "title": tip,
            }
        )

    edges = []
    for r in relations:
        s = r.get("source") or r.get("source_id")
        t = r.get("target") or r.get("target_id")
        rel_type = r.get("type") or r.get("relation_type") or ""
        is_causal = bool(r.get("is_causal"))
        edges.append({"from": s, "to": t, "label": rel_type, "arrows": "to", "dashes": (not is_causal)})

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; }}
    #topbar {{ padding: 10px 14px; border-bottom: 1px solid #eee; }}
    #network {{ width: 100%; height: calc(100vh - 52px); }}
    .meta {{ color: #666; font-size: 12px; }}
  </style>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.css" />
  <script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"></script>
</head>
<body>
  <div id="topbar">
    <div><b>{title}</b></div>
    <div class="meta">Source JSON: {ckg_json}</div>
    <div class="meta">Nodes: {len(nodes)} | Edges: {len(edges)} (dashed = non-causal / weak)</div>
  </div>
  <div id="network"></div>

  <script>
    const nodes = new vis.DataSet({json.dumps(nodes, ensure_ascii=False)});
    const edges = new vis.DataSet({json.dumps(edges, ensure_ascii=False)});

    const container = document.getElementById('network');
    const data = {{ nodes, edges }};
    const options = {{
      layout: {{ improvedLayout: true }},
      interaction: {{ hover: true, navigationButtons: true }},
      physics: {{ stabilization: true }},
      nodes: {{ shape: 'box', margin: 10, font: {{ multi: 'html', size: 13 }} }},
      edges: {{ smooth: {{ type: 'dynamic' }}, font: {{ align: 'middle' }} }}
    }};

    new vis.Network(container, data, options);
  </script>
</body>
</html>
"""

    out_html.write_text(html, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(prog="orchastrator.case_loop")
    p.add_argument("--data", required=True, help="Path to data/<case> file containing report + E2E query")
    p.add_argument("--case-id", required=True, choices=["case1", "case2", "case3"])
    p.add_argument("--case-num", type=int, required=True, help="Case number for folder naming (e.g. 2)")
    p.add_argument("--run-id", default=None, help="Run id (default: timestamp)")
    p.add_argument("--output-root", default="output/closed_loop_runs")
    p.add_argument("--max-iters", type=int, default=5)
    p.add_argument("--stop-accuracy", type=float, default=9.0)
    p.add_argument("--stop-overall", type=float, default=8.0)
    p.add_argument("--judge-provider", choices=["openai", "anthropic"], default="openai")

    start = p.add_mutually_exclusive_group(required=True)
    start.add_argument("--start-from-scratch", action="store_true")
    start.add_argument("--base-ckg", type=str, default=None)
    p.add_argument("--base-fix-db", type=str, default=None, help="Base fixes sqlite DB (used when --base-ckg is set)")

    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dry-run-stop-iter", type=int, default=1)
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = project_root / args.output_root

    cfg = CaseLoopConfig(
        run_id=run_id,
        case_id=str(args.case_id),
        case_num=int(args.case_num),
        data_path=project_root / args.data,
        output_root=out_root,
        max_iters=int(args.max_iters),
        stop_accuracy=float(args.stop_accuracy),
        stop_overall=float(args.stop_overall),
        judge_provider=str(args.judge_provider),
        start_from_scratch=bool(args.start_from_scratch),
        base_ckg_path=(Path(args.base_ckg) if args.base_ckg else None),
        base_fix_db_path=(Path(args.base_fix_db) if args.base_fix_db else None),
        dry_run=bool(args.dry_run),
        dry_run_stop_iter=int(args.dry_run_stop_iter),
    )

    run_dir = run_case_loop(cfg)
    print(f"Run written to: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

