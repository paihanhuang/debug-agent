"""Hybrid Two-Stage Agent - End-to-End Production Test.

Tests the hybrid agent on all 3 production cases and compares results.
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

from graphrag.hybrid_agent import HybridTwoStageAgent


# Test cases from production
TEST_CASES = [
    {
        "name": "Case 1",
        "query": """VCORE 725mV usage is at 82.6%, exceeding the 10% threshold.
DDR5460 and DDR6370 combined usage is 82.6%.
MMDVFS is at OPP4.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - all at ceiling.
DDR voting shows SW_REQ2 activity.""",
        "expected_root_causes": ["CM"],
        "expected_mmdvfs": "ruled_out",  # OPP4 = normal
    },
    {
        "name": "Case 2",
        "query": """VCORE 725mV usage is at 29.32%, exceeding the 10% threshold.
DDR5460 at 3.54%, DDR6370 at 26.13%. Total DDR at 29.67%.
MMDVFS is at OPP4.
CPU shows various frequencies with high usage.
DDR voting shows SW_REQ2 and SW_REQ3 activity.""",
        "expected_root_causes": ["CM", "PowerHal"],
        "expected_mmdvfs": "ruled_out",  # OPP4 = normal
    },
    {
        "name": "Case 3 (DUAL ISSUE)",
        "query": """VCORE 725mV usage is at 52.51%, exceeding the 10% threshold.
VCORE 600mV is the floor (should be 575mV).
MMDVFS is at OPP3 with 100% usage.
DDR5460 at 23.37%, DDR6370 at 30.77%. Total DDR at 54.14%.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - high usage.
No DDR voting data available, suspected CM related.""",
        "expected_root_causes": ["CM", "MMDVFS"],
        "expected_mmdvfs": "confirmed",  # OPP3 @ 100% = issue
        "expected_dual_issue": True,
    },
]


def run_hybrid_e2e_test():
    """Run E2E test with hybrid agent."""
    print("=" * 70)
    print("Hybrid Two-Stage Agent - End-to-End Production Test")
    print("=" * 70)
    
    # Load CKG
    ckg_path = _project_root / "output" / "full_ckg.json"
    with open(ckg_path, "r", encoding="utf-8") as f:
        ckg_data = json.load(f)
    
    print(f"\n[1] Loading CKG: {ckg_data['metadata']['num_entities']} entities, {ckg_data['metadata']['num_relations']} relations")
    
    # Initialize agent
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
            
            print("[2] Agent initialized with CKG and historical fixes\n")
            
            # Run each test case
            results = []
            total_llm_calls = 0
            
            for i, case in enumerate(TEST_CASES, 1):
                print("=" * 70)
                print(f"TEST {i}: {case['name']}")
                print("=" * 70)
                
                # Run diagnosis
                result = agent.diagnose(case["query"])
                total_llm_calls += result.llm_calls
                
                # Display results
                print(f"\n📊 Anomalies Detected: {len(result.anomalies)}")
                for a in result.anomalies:
                    print(f"   - {a.type}: {a.metric} = {a.value} ({a.severity})")
                
                print(f"\n🔍 Dual Issue: {'Yes' if result.has_dual_issue else 'No'}")
                print(f"📞 LLM Calls: {result.llm_calls}")
                
                # Check expected root causes
                found_causes = [d.root_cause.lower() for d in result.diagnoses]
                all_found = " ".join(found_causes)
                
                expected_found = []
                expected_missing = []
                for exp in case["expected_root_causes"]:
                    if exp.lower() in all_found.lower():
                        expected_found.append(exp)
                    else:
                        expected_missing.append(exp)
                
                print(f"\n✅ Expected Root Causes Found: {expected_found}")
                if expected_missing:
                    print(f"❌ Expected Root Causes Missing: {expected_missing}")
                
                # Check dual issue expectation
                if case.get("expected_dual_issue"):
                    if result.has_dual_issue:
                        print("✅ Dual Issue Correctly Identified")
                    else:
                        print("❌ Dual Issue NOT Identified (expected)")
                
                # Store result
                case_result = {
                    "name": case["name"],
                    "anomalies_detected": len(result.anomalies),
                    "anomaly_types": [a.type for a in result.anomalies],
                    "has_dual_issue": result.has_dual_issue,
                    "llm_calls": result.llm_calls,
                    "expected_found": expected_found,
                    "expected_missing": expected_missing,
                    "passed": len(expected_missing) == 0,
                    "synthesized_report": result.synthesized_report,
                }
                results.append(case_result)
                
                print("\n" + "-" * 50)
                print("SYNTHESIZED REPORT:")
                print("-" * 50)
                # Print first 500 chars
                print(result.synthesized_report[:800] + "..." if len(result.synthesized_report) > 800 else result.synthesized_report)
                print()
            
            # Summary
            print("\n" + "=" * 70)
            print("SUMMARY")
            print("=" * 70)
            
            passed = sum(1 for r in results if r["passed"])
            print(f"\n📊 Tests Passed: {passed}/{len(results)}")
            print(f"📞 Total LLM Calls: {total_llm_calls}")
            
            for r in results:
                status = "✅ PASS" if r["passed"] else "❌ FAIL"
                dual = "DUAL" if r["has_dual_issue"] else ""
                print(f"   {r['name']}: {status} | {r['anomalies_detected']} anomalies | {r['llm_calls']} LLM calls {dual}")
            
            # Save results
            output_path = _project_root / "output" / "hybrid_e2e_results.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            print(f"\n📁 Results saved to: {output_path}")
            print("=" * 70)
            
            return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run_hybrid_e2e_test())
