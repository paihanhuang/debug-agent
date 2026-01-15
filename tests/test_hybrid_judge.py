"""Hybrid Two-Stage Agent - Full E2E Test with Judge Evaluation.

Runs hybrid agent on all 3 cases and evaluates against human expert reports using LLM Judge.
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add paths
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "debug-engine" / "src"))


# Test cases with human report paths
TEST_CASES = [
    {
        "name": "case1",
        "query": """VCORE 725mV usage is at 82.6%, exceeding the 10% threshold.
DDR5460 and DDR6370 combined usage is 82.6%.
MMDVFS is at OPP4.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - all at ceiling.
DDR voting shows SW_REQ2 activity.""",
        "human_report": _project_root / "data" / "first",
    },
    {
        "name": "case2",
        "query": """VCORE 725mV usage is at 29.32%, exceeding the 10% threshold.
DDR5460 at 3.54%, DDR6370 at 26.13%. Total DDR at 29.67%.
MMDVFS is at OPP4.
CPU shows various frequencies with high usage.
DDR voting shows SW_REQ2 and SW_REQ3 activity.""",
        "human_report": _project_root / "data" / "second",
    },
    {
        "name": "case3",
        "query": """VCORE 725mV usage is at 52.51%, exceeding the 10% threshold.
VCORE 600mV is the floor (should be 575mV).
MMDVFS is at OPP3 with 100% usage.
DDR5460 at 23.37%, DDR6370 at 30.77%. Total DDR at 54.14%.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - high usage.
No DDR voting data available, suspected CM related.""",
        "human_report": _project_root / "data" / "third",
    },
]


def run_hybrid_with_judge():
    """Run hybrid agent and evaluate with Judge."""
    from graphrag.hybrid_agent import HybridTwoStageAgent
    from judge.llm_judge import LLMReportJudge
    
    print("=" * 70)
    print("Hybrid Two-Stage Agent - E2E Test with Judge Evaluation")
    print("=" * 70)
    
    # Load CKG
    ckg_path = _project_root / "output" / "full_ckg.json"
    with open(ckg_path, "r", encoding="utf-8") as f:
        ckg_data = json.load(f)
    
    print(f"\n[1] Loading CKG: {ckg_data['metadata']['num_entities']} entities")
    
    # Output directory
    output_dir = _project_root / "output" / "hybrid_e2e"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize Judge
    print("[2] Initializing LLM Judge (OpenAI gpt-4o)...")
    judge = LLMReportJudge(provider="openai")
    
    # Initialize Hybrid Agent
    with tempfile.TemporaryDirectory() as tmpdir:
        fix_db_path = Path(tmpdir) / "fixes.db"
        
        agent = HybridTwoStageAgent(
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
            fix_db_path=str(fix_db_path),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
        
        with agent:
            agent.load_ckg(ckg_data)
            
            # Add historical fixes
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
            
            print("[3] Running hybrid diagnosis on all 3 cases...\n")
            
            results = []
            
            for case in TEST_CASES:
                print("=" * 70)
                print(f"Case: {case['name']}")
                print("=" * 70)
                
                # Run hybrid diagnosis
                result = agent.diagnose(case["query"])
                
                print(f"📊 Anomalies: {len(result.anomalies)}")
                for a in result.anomalies:
                    print(f"   - {a.type}: {a.value}")
                print(f"🔍 Dual Issue: {result.has_dual_issue}")
                print(f"📞 LLM Calls: {result.llm_calls}")
                
                # Save agent report
                agent_report_path = output_dir / f"hybrid_report_{case['name']}.md"
                with open(agent_report_path, "w", encoding="utf-8") as f:
                    f.write(f"# Hybrid Agent Report - {case['name']}\n\n")
                    f.write(result.synthesized_report)
                
                # Read human report
                with open(case["human_report"], "r", encoding="utf-8") as f:
                    human_report = f.read()
                
                # Run Judge evaluation
                print(f"\n[Judge] Evaluating against human report...")
                eval_result = judge.evaluate(
                    human_report=human_report,
                    agent_report=result.synthesized_report,
                    case_name=case["name"],
                )
                
                print(f"\n📊 Score: {eval_result.composite_score:.2f}/10 ({eval_result.grade()})")
                print(f"📝 Summary: {eval_result.summary[:100]}...")
                
                print("\nDimension Scores:")
                for dim in eval_result.dimensions:
                    status = "✓" if dim.score >= 8 else "○"
                    print(f"  {status} {dim.name}: {dim.score}/10 (weight: {int(dim.weight*100)}%)")
                
                results.append({
                    "case": case["name"],
                    "anomalies": len(result.anomalies),
                    "has_dual_issue": result.has_dual_issue,
                    "llm_calls": result.llm_calls,
                    "score": eval_result.composite_score,
                    "grade": eval_result.grade(),
                    "dimensions": {d.name: d.score for d in eval_result.dimensions},
                })
                
                print()
            
            # Summary
            print("\n" + "=" * 70)
            print("FINAL SUMMARY")
            print("=" * 70)
            
            avg_score = sum(r["score"] for r in results) / len(results)
            
            print(f"\n{'Case':<25} {'Score':>10} {'Grade':>8} {'Anomalies':>10} {'Dual Issue':>12}")
            print("-" * 70)
            for r in results:
                dual = "Yes" if r["has_dual_issue"] else "No"
                print(f"{r['case']:<25} {r['score']:>10.2f} {r['grade']:>8} {r['anomalies']:>10} {dual:>12}")
            print("-" * 70)
            print(f"{'AVERAGE':<25} {avg_score:>10.2f}")
            
            # Save results
            summary_path = output_dir / "hybrid_judge_results.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump({
                    "results": results,
                    "average_score": avg_score,
                    "total_llm_calls": sum(r["llm_calls"] for r in results),
                }, f, indent=2)
            
            print(f"\n📁 Results saved to: {summary_path}")
            print("=" * 70)
            
            return 0


if __name__ == "__main__":
    sys.exit(run_hybrid_with_judge())
