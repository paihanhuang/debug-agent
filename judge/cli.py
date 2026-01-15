"""Report Quality Judge - Command Line Interface.

Provides CLI for running judge evaluations and generating QA reports.

Usage:
    python3 -m judge.cli --help
    python3 -m judge.cli run --human-report path/to/human.md --agent-report path/to/agent.md
    python3 -m judge.cli batch --output-dir judge/qa_results
    python3 -m judge.cli refine --input "VCORE at 82.6%..." --threshold 8.0
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .llm_judge import LLMReportJudge, LLMProvider
from .models import EvaluationResult


def run_single_evaluation(args) -> int:
    """Run evaluation on a single report pair."""
    # Use specified provider or default to Claude
    provider = args.provider if hasattr(args, 'provider') and args.provider else "anthropic"
    judge = LLMReportJudge(provider=provider)
    
    print(f"Using Judge: {judge._model} ({judge._provider.value})")
    
    result = judge.evaluate_from_files(
        human_report_path=args.human_report,
        agent_report_path=args.agent_report,
        case_name=args.case_name,
    )
    
    print(f"\n{'='*60}")
    print(f"Evaluation Result: {result.case_name}")
    print(f"{'='*60}")
    print(f"Composite Score: {result.composite_score}/10.0 (Grade: {result.grade()})")
    print(f"Summary: {result.summary}")
    print("\nDimension Scores:")
    for dim in result.dimensions:
        status = "✓" if dim.score >= 8 else "○" if dim.score >= 6 else "✗"
        print(f"  {status} {dim.name}: {dim.score}/10 (weight: {int(dim.weight*100)}%)")
        if dim.explanation:
            print(f"      → {dim.explanation}")
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\nSaved to: {output_path}")
    
    return 0


def run_batch_evaluation(args) -> int:
    """Run evaluation on all production cases using Claude Judge."""
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")
    
    # Paths
    output_dir = project_root / "output" / "e2e_production"
    qa_dir = Path(args.output_dir) if args.output_dir else project_root / "judge" / "qa_results"
    qa_dir.mkdir(parents=True, exist_ok=True)
    
    # Ground truth reports (human expert)
    human_reports = {
        "case1": """
Root cause: CM (CPU Manager) 拉檔 causing all CPU cores at ceiling frequencies.
Causal chain: CM -> CPU at ceiling -> DDR voting SW_REQ2 -> DDR 82.6% -> VCORE 725mV @ 82.6%
MMDVFS ruled out (stays at OPP4).

Details:
- VCORE 725mV usage: 82.6% (exceeds 10% threshold)
- DDR5460 + DDR6370 combined: 82.6%
- CPU 大核: 2700MHz, 中核: 2500MHz, 小核: 2100MHz (all at ceiling)
- MMDVFS at OPP4 - not the cause
""",
        "case2": """
Root cause: CM (via SW_REQ2) + PowerHal (via SW_REQ3) 拉檔.
Causal chain: CM/PowerHal -> DDR voting -> DDR 29.67% -> VCORE 725mV @ 29.32%
MMDVFS ruled out (stays at OPP4).
Related to control policy (調控策略).

Details:
- VCORE 725mV usage: 29.32% (exceeds 10% threshold)
- DDR5460: 3.54%, DDR6370: 26.13%, Total: 29.67%
- SW_REQ2 (CM) and SW_REQ3 (PowerHal) both contribute
""",
        "case3": """
Two issues:
1. VCORE 600mV floor caused by MMDVFS OPP3 at 100%.
2. VCORE 725mV @ 52.51% caused by DDR 54.14% from CM 拉檔.
Related to control policy (調控策略).

Details:
- VCORE 725mV usage: 52.51% (exceeds 10% threshold)
- VCORE 600mV floor (should be 575mV) - MMDVFS issue
- DDR5460: 23.37%, DDR6370: 30.77%, Total: 54.14%
- CPU 大核: 2700MHz, 中核: 2500MHz, 小核: 2100MHz (high usage)
- MMDVFS at OPP3 100% - causes 600mV floor
""",
    }
    
    print("=" * 70)
    print("Judge Batch Evaluation - Production E2E Cases")
    print("=" * 70)
    
    # Initialize judge - default to Claude
    provider = args.provider if hasattr(args, 'provider') and args.provider else "anthropic"
    print(f"\n[1] Initializing LLM Report Judge ({provider})...")
    
    try:
        judge = LLMReportJudge(provider=provider)
        print(f"    Model: {judge._model}")
    except Exception as e:
        print(f"    ⚠ Failed to init {provider}: {e}")
        print("    Falling back to OpenAI...")
        judge = LLMReportJudge(provider="openai")
    
    # Evaluate each case
    results = []
    cases = [
        ("case1", "agent_report_case1.md"),
        ("case2", "agent_report_case2.md"),
        ("case3", "agent_report_case3.md"),
    ]
    
    for case_key, agent_file in cases:
        print(f"\n{'='*70}")
        print(f"Evaluating: {case_key}")
        print("=" * 70)
        
        # Load agent report
        agent_path = output_dir / agent_file
        if not agent_path.exists():
            print(f"  ⚠ Warning: {agent_path} not found, skipping...")
            continue
            
        agent_report = agent_path.read_text(encoding="utf-8")
        human_report = human_reports[case_key]
        
        # Evaluate
        result = judge.evaluate(
            human_report=human_report,
            agent_report=agent_report,
            case_name=case_key,
            human_report_path=f"ground_truth/{case_key}",
            agent_report_path=str(agent_path),
        )
        results.append(result)
        
        # Print results
        print(f"\nComposite Score: {result.composite_score}/10.0 (Grade: {result.grade()})")
        print(f"Summary: {result.summary}")
        print("\nDimension Scores:")
        for dim in result.dimensions:
            status = "✓" if dim.score >= 8 else "○" if dim.score >= 6 else "✗"
            print(f"  {status} {dim.name}: {dim.score}/10 (weight: {int(dim.weight*100)}%)")
            if dim.matched_elements:
                print(f"      Matched: {dim.matched_elements[:3]}")
            if dim.missing_elements:
                print(f"      Missing: {dim.missing_elements[:3]}")
    
    if not results:
        print("\n⚠ No cases evaluated!")
        return 1
    
    # Save QA results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    qa_report = {
        "test_name": "Judge Batch Evaluation",
        "timestamp": results[0].timestamp,
        "run_id": timestamp,
        "total_cases": len(results),
        "judge_model": judge._model,
        "judge_provider": judge._provider.value,
        "results": [r.to_dict() for r in results],
        "summary": {
            "average_score": round(sum(r.composite_score for r in results) / len(results), 2),
            "grades": {r.case_name: r.grade() for r in results},
            "pass_rate": sum(1 for r in results if r.composite_score >= 7.0) / len(results) * 100,
        },
    }
    
    qa_path = qa_dir / f"judge_qa_report_{timestamp}.json"
    with open(qa_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    
    # Also save a summary file
    summary_path = qa_dir / "latest_qa_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(qa_report["summary"], f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        print(f"  {r.case_name}: {r.composite_score}/10.0 ({r.grade()})")
    avg = sum(r.composite_score for r in results) / len(results)
    print(f"\n  Average: {avg:.2f}/10.0")
    print(f"  Pass Rate: {qa_report['summary']['pass_rate']:.0f}%")
    print(f"\n  Judge: {judge._model} ({judge._provider.value})")
    print(f"  QA Results saved to: {qa_path}")
    print("=" * 70)
    
    return 0 if avg >= 7.0 else 1


def run_refinement(args) -> int:
    """Run diagnosis with iterative refinement using closed-loop system."""
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")
    
    # Add debug-engine to path
    sys.path.insert(0, str(project_root / "debug-engine" / "src"))
    
    print("=" * 70)
    print("Closed-Loop Refinement - GPT-4o Agent + Claude Judge")
    print("=" * 70)
    
    # Load input
    input_text = args.input
    if Path(input_text).exists():
        input_text = Path(input_text).read_text(encoding="utf-8")
    
    ground_truth = None
    if args.ground_truth:
        if Path(args.ground_truth).exists():
            ground_truth = Path(args.ground_truth).read_text(encoding="utf-8")
        else:
            ground_truth = args.ground_truth
    
    print(f"\n[1] Input: {input_text[:100]}...")
    print(f"[2] Max Iterations: {args.max_iterations}")
    print(f"[3] Score Threshold: {args.threshold}/10")
    
    # Initialize components
    print("\n[4] Initializing components...")
    
    try:
        from graphrag.agent import DebugAgent
        from graphrag.refinement_loop import RefinementLoop
    except ImportError as e:
        print(f"    ⚠ Import error: {e}")
        print("    Make sure you're running from the project root.")
        return 1
    
    # Initialize Judge (Claude)
    judge = LLMReportJudge(provider="anthropic")
    print(f"    Judge: {judge._model} ({judge._provider.value})")
    
    # Initialize Agent (GPT-4o) - requires Neo4j
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    
    try:
        agent = DebugAgent(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
        )
        print(f"    Agent: {agent._llm_model}")
    except Exception as e:
        print(f"    ⚠ Failed to initialize Agent: {e}")
        print("    Make sure Neo4j is running.")
        return 1
    
    # Create refinement loop
    loop = RefinementLoop(
        agent=agent,
        judge=judge,
        max_iterations=args.max_iterations,
        score_threshold=args.threshold,
        verbose=True,
    )
    
    # Run refinement
    print("\n[5] Running refinement loop...")
    print("-" * 70)
    
    with agent:
        result = loop.diagnose_with_refinement(
            input_text=input_text,
            ground_truth=ground_truth,
        )
    
    # Print results
    print("\n" + "=" * 70)
    print("REFINEMENT COMPLETE")
    print("=" * 70)
    print(f"  Final Score: {result.final_score}/10.0 ({result.final_grade})")
    print(f"  Iterations: {result.iterations}")
    print(f"\n  Improvement History:")
    for h in result.improvement_history:
        print(f"    Iteration {h['iteration']}: {h['score']}/10 ({h['grade']})")
    
    if result.final_diagnosis:
        print(f"\n  Root Cause: {result.final_diagnosis.root_cause[:100]}...")
    
    # Save output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        output_data = result.to_dict()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n  Saved to: {output_path}")
    
    print("=" * 70)
    
    return 0 if result.final_score >= args.threshold else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Report Quality Judge - Evaluate agent reports against human expert ground truth"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Run single evaluation
    run_parser = subparsers.add_parser("run", help="Evaluate a single report pair")
    run_parser.add_argument("--human-report", "-r", required=True, help="Path to human expert report")
    run_parser.add_argument("--agent-report", "-a", required=True, help="Path to agent generated report")
    run_parser.add_argument("--case-name", "-n", default="unnamed", help="Name for this case")
    run_parser.add_argument("--output", "-o", help="Path to save JSON result")
    run_parser.add_argument("--provider", "-p", choices=["openai", "anthropic"], default="anthropic", help="LLM provider")
    
    # Batch evaluation
    batch_parser = subparsers.add_parser("batch", help="Run batch evaluation on all production cases")
    batch_parser.add_argument("--output-dir", "-o", help="Directory for QA results")
    batch_parser.add_argument("--provider", "-p", choices=["openai", "anthropic"], default="anthropic", help="LLM provider")
    
    # Refinement command (closed-loop)
    refine_parser = subparsers.add_parser("refine", help="Run diagnosis with iterative refinement")
    refine_parser.add_argument("--input", "-i", required=True, help="Input metrics/observation text or file path")
    refine_parser.add_argument("--ground-truth", "-g", help="Optional ground truth for comparison")
    refine_parser.add_argument("--max-iterations", "-m", type=int, default=3, help="Maximum refinement iterations")
    refine_parser.add_argument("--threshold", "-t", type=float, default=8.0, help="Score threshold to stop (1-10)")
    refine_parser.add_argument("--output", "-o", help="Output file for final result")
    
    # Hybrid two-stage diagnosis command
    hybrid_parser = subparsers.add_parser("hybrid", help="Run hybrid two-stage diagnosis")
    hybrid_parser.add_argument("--input", "-i", required=True, help="Input metrics/observation text or file path")
    hybrid_parser.add_argument("--output", "-o", help="Output file for result")
    hybrid_parser.add_argument("--case-name", "-n", default="hybrid_diagnosis", help="Case name for output")
    
    args = parser.parse_args()
    
    if args.command == "run":
        return run_single_evaluation(args)
    elif args.command == "batch":
        return run_batch_evaluation(args)
    elif args.command == "refine":
        return run_refinement(args)
    elif args.command == "hybrid":
        return run_hybrid_diagnosis(args)
    else:
        parser.print_help()
        return 1


def run_hybrid_diagnosis(args) -> int:
    """Run hybrid two-stage diagnosis."""
    import tempfile
    
    # Add paths for imports
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "debug-engine" / "src"))
    
    print("=" * 70)
    print("Hybrid Two-Stage Diagnosis")
    print("=" * 70)
    
    # Get input
    if os.path.isfile(args.input):
        with open(args.input, "r") as f:
            user_input = f.read()
        print(f"\nInput file: {args.input}")
    else:
        user_input = args.input
    
    print(f"\nInput:\n{user_input[:200]}...")
    
    # Load CKG
    ckg_path = project_root / "output" / "full_ckg.json"
    if not ckg_path.exists():
        print(f"\n❌ CKG not found at: {ckg_path}")
        return 1
    
    with open(ckg_path, "r") as f:
        ckg_data = json.load(f)
    
    print(f"\n[1] Loading CKG (Entities: {ckg_data['metadata']['num_entities']}, Relations: {ckg_data['metadata']['num_relations']})")
    
    # Import hybrid agent
    try:
        from graphrag.hybrid_agent import HybridTwoStageAgent
    except ImportError as e:
        print(f"\n❌ Failed to import HybridTwoStageAgent: {e}")
        return 1
    
    # Initialize agent
    print("\n[2] Initializing Hybrid Two-Stage Agent...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        fix_db_path = Path(tmpdir) / "fixes.db"
        
        try:
            agent = HybridTwoStageAgent(
                neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
                neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
                fix_db_path=str(fix_db_path),
                openai_api_key=os.getenv("OPENAI_API_KEY"),
            )
        except Exception as e:
            print(f"\n❌ Failed to initialize agent: {e}")
            return 1
        
        with agent:
            # Load CKG
            agent.load_ckg(ckg_data)
            print("    ✓ CKG loaded")
            
            # Add historical fixes
            from graphrag.fix_store import HistoricalFix
            agent.add_historical_fix(
                case_id="case_001",
                root_cause="CM (CPU Manager)",
                symptom_summary="VCORE 725mV at 82.6%",
                metrics={"VCORE_725": 82.6},
                fix_description="Review CPU frequency control policy.",
            )
            agent.add_historical_fix(
                case_id="case_003a",
                root_cause="MMDVFS OPP3",
                symptom_summary="VCORE 600mV floor",
                metrics={"MMDVFS_OPP3": 100},
                fix_description="Review MMDVFS OPP settings.",
            )
            print("    ✓ Historical fixes added")
            
            # Run diagnosis
            print("\n[3] Running 3-stage diagnosis pipeline...")
            result = agent.diagnose(user_input)
            
            # Display results
            print("\n" + "=" * 70)
            print("RESULTS")
            print("=" * 70)
            
            print(f"\n📊 Anomalies Detected: {len(result.anomalies)}")
            for a in result.anomalies:
                print(f"   - {a.type}: {a.metric} = {a.value} ({a.severity})")
            
            print(f"\n🔍 Dual Issue: {'Yes' if result.has_dual_issue else 'No'}")
            print(f"📞 LLM Calls: {result.llm_calls}")
            
            print(f"\n📝 Synthesized Report:")
            print("-" * 50)
            print(result.synthesized_report)
            print("-" * 50)
            
            # Save output
            if args.output:
                output_data = result.to_dict()
                with open(args.output, "w") as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
                print(f"\n✓ Results saved to: {args.output}")
            
            print("\n" + "=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

