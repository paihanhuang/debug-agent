"""Integration test for LLM Judge - Evaluates the 3 production cases."""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Setup paths
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

load_dotenv(_project_root / ".env")

from judge.llm_judge import LLMReportJudge
from judge.models import EvaluationResult


# Ground truth reports (human expert)
HUMAN_REPORTS = {
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


def run_evaluation():
    """Run evaluation on all 3 production cases."""
    print("=" * 70)
    print("Judge Evaluation - Production E2E Cases")
    print("=" * 70)
    
    # Paths
    output_dir = _project_root / "output" / "e2e_production"
    qa_dir = _project_root / "judge" / "qa_results"
    qa_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize judge
    print("\n[1] Initializing LLM Report Judge...")
    judge = LLMReportJudge()
    
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
        agent_report = agent_path.read_text(encoding="utf-8")
        human_report = HUMAN_REPORTS[case_key]
        
        # Evaluate
        result = judge.evaluate(
            human_report=human_report,
            agent_report=agent_report,
            case_name=case_key,
            human_report_path=f"data/{case_key.replace('case', '')}",
            agent_report_path=str(agent_path),
        )
        results.append(result)
        
        # Print results
        print(f"\nComposite Score: {result.composite_score}/10.0 (Grade: {result.grade()})")
        print(f"Summary: {result.summary}")
        print("\nDimension Scores:")
        for dim in result.dimensions:
            status = "✓" if dim.score >= 7 else "○" if dim.score >= 5 else "✗"
            print(f"  {status} {dim.name}: {dim.score}/10 (weight: {int(dim.weight*100)}%)")
            if dim.matched_elements:
                print(f"      Matched: {dim.matched_elements[:3]}")
            if dim.missing_elements:
                print(f"      Missing: {dim.missing_elements[:3]}")
    
    # Save QA results
    qa_report = {
        "test_name": "Judge Integration Test",
        "timestamp": results[0].timestamp if results else "",
        "total_cases": len(results),
        "results": [r.to_dict() for r in results],
        "summary": {
            "average_score": round(sum(r.composite_score for r in results) / len(results), 2),
            "grades": {r.case_name: r.grade() for r in results},
        },
    }
    
    qa_path = qa_dir / "judge_integration_test.json"
    with open(qa_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        print(f"  {r.case_name}: {r.composite_score}/10.0 ({r.grade()})")
    avg = sum(r.composite_score for r in results) / len(results)
    print(f"\n  Average: {avg:.2f}/10.0")
    print(f"\n  QA Results saved to: {qa_path}")
    print("=" * 70)
    
    return results


if __name__ == "__main__":
    run_evaluation()
