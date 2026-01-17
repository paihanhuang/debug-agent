"""Production E2E Test: Combined CKG with Full Database Integration.

This test:
1. Loads a combined CKG from all 3 reports into Neo4j + FAISS
2. Adds historical fixes to SQLite
3. Runs DebugAgent diagnosis with test queries
4. Compares agent output against human expert ground truth
"""

from __future__ import annotations
import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add paths for imports
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "debug-engine" / "src"))

from graphrag.agent import DebugAgent
from graphrag.fix_store import HistoricalFix


# =============================================================================
# Ground Truth from Human Expert Reports
# =============================================================================

@dataclass
class TestCase:
    """Test case derived from human expert report."""
    name: str
    query: str  # Simulated user query with metrics
    expected_root_cause: list[str]  # Keywords expected in root cause
    expected_causal_elements: list[str]  # Keywords in causal chain
    ground_truth_summary: str  # Human expert summary


TEST_CASES = [
    TestCase(
        name="Case 1 (first report)",
        query="""
VCORE 725mV usage is at 82.6%, exceeding the 10% threshold.
DDR5460 and DDR6370 combined usage is 82.6%.
MMDVFS is at OPP4.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - all at ceiling.
DDR voting shows SW_REQ2 activity.
""",
        expected_root_cause=["CM", "CPU"],
        expected_causal_elements=["DDR", "CPU", "VCORE", "725"],
        ground_truth_summary="""
Root cause: CM (CPU Manager) 拉檔 causing all CPU cores at ceiling frequencies.
Causal chain: CM -> CPU at ceiling -> DDR voting SW_REQ2 -> DDR 82.6% -> VCORE 725mV @ 82.6%
MMDVFS ruled out (stays at OPP4).
""",
    ),
    TestCase(
        name="Case 2 (second report)",
        query="""
VCORE 725mV usage is at 29.32%, exceeding the 10% threshold.
DDR5460 at 3.54%, DDR6370 at 26.13%. Total DDR at 29.67%.
MMDVFS is at OPP4.
CPU shows various frequencies with high usage.
DDR voting shows SW_REQ2 and SW_REQ3 activity.
""",
        expected_root_cause=["CM", "PowerHal"],
        expected_causal_elements=["DDR", "VCORE", "SW_REQ"],
        ground_truth_summary="""
Root cause: CM (via SW_REQ2) + PowerHal (via SW_REQ3) 拉檔.
Causal chain: CM/PowerHal -> DDR voting -> DDR 29.67% -> VCORE 725mV @ 29.32%
MMDVFS ruled out (stays at OPP4).
Related to control policy (調控策略).
""",
    ),
    TestCase(
        name="Case 3 (third report)",
        query="""
VCORE 725mV usage is at 52.51%, exceeding the 10% threshold.
VCORE 600mV is the floor (should be 575mV).
MMDVFS is at OPP3 with 100% usage.
DDR5460 at 23.37%, DDR6370 at 30.77%. Total DDR at 54.14%.
CPU 大核 at 2700MHz, 中核 at 2500MHz, 小核 at 2100MHz - high usage.
No DDR voting data available, suspected CM related.
""",
        expected_root_cause=["CM", "MMDVFS"],
        expected_causal_elements=["DDR", "VCORE", "600", "725", "OPP3"],
        ground_truth_summary="""
Two issues:
1. VCORE 600mV floor caused by MMDVFS OPP3 at 100%.
2. VCORE 725mV @ 52.51% caused by DDR 54.14% from CM 拉檔.
Related to control policy (調控策略).
""",
    ),
]


# =============================================================================
# Historical Fixes (derived from reports)
# =============================================================================

HISTORICAL_FIXES = [
    HistoricalFix(
        case_id="case_001",
        root_cause="CM (CPU Manager)",
        symptom_summary="VCORE 725mV at 82.6%, DDR 82.6%",
        metrics={"VCORE_725": 82.6, "DDR_total": 82.6},
        fix_description="Review CPU frequency control policy. Consider tuning CM scheduling.",
        resolution_notes="All CPU cores at ceiling frequencies caused DDR voting spike",
    ),
    HistoricalFix(
        case_id="case_002",
        root_cause="CM (CPU Manager)",
        symptom_summary="VCORE 725mV at 29.32%, DDR 29.67%",
        metrics={"VCORE_725": 29.32, "DDR5460": 3.54, "DDR6370": 26.13},
        fix_description="Review PowerHal SW_REQ3 voting policy. Adjust CM control strategy.",
        resolution_notes="Both CM (SW_REQ2) and PowerHal (SW_REQ3) contributed to issue",
    ),
    HistoricalFix(
        case_id="case_003a",
        root_cause="MMDVFS OPP3",
        symptom_summary="VCORE 600mV floor (should be 575mV)",
        metrics={"MMDVFS_OPP3": 100},
        fix_description="Review MMDVFS OPP settings. Reduce OPP3 usage to allow lower VCORE.",
        resolution_notes="MMDVFS locked at OPP3 prevents VCORE from dropping to 575mV",
    ),
    HistoricalFix(
        case_id="case_003b",
        root_cause="CM (CPU Manager)",
        symptom_summary="VCORE 725mV at 52.51%, DDR 54.14%",
        metrics={"VCORE_725": 52.51, "DDR5460": 23.37, "DDR6370": 30.77},
        fix_description="Tune CPU scheduling to reduce DDR pressure. Review control policy.",
        resolution_notes="High CPU frequency usage driving DDR voting",
    ),
]


# =============================================================================
# Main Test Runner
# =============================================================================

def check_keywords(text: str, keywords: list[str]) -> tuple[bool, list[str]]:
    """Check if keywords appear in text, return match status and found keywords."""
    text_lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in text_lower]
    return len(found) > 0, found


def run_production_test():
    """Run the production E2E test."""
    print("=" * 70)
    print("Production E2E Test: Combined CKG with Full Database Integration")
    print("=" * 70)
    
    # Paths
    ckg_path = _project_root / "output" / "full_ckg.json"
    output_dir = _project_root / "output" / "e2e_production"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load combined CKG
    print(f"\n[1] Loading combined CKG from: {ckg_path}")
    with open(ckg_path, "r", encoding="utf-8") as f:
        ckg_data = json.load(f)
    print(f"    Entities: {ckg_data['metadata']['num_entities']}")
    print(f"    Relations: {ckg_data['metadata']['num_relations']}")
    
    fix_db_path = output_dir / "fixes.db"
    vector_store_path = output_dir / "vectors"
    
    # Check Neo4j availability
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    
    print(f"\n[2] Initializing DebugAgent")
    print(f"    Neo4j URI: {neo4j_uri}")
    print(f"    Fix DB: {fix_db_path}")
    
    try:
        agent = DebugAgent(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            fix_db_path=str(fix_db_path),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
    except Exception as e:
        print(f"\n❌ Failed to initialize DebugAgent: {e}")
        print("\nMake sure Neo4j is running:")
        print("  docker run -d --name neo4j-test -p 7474:7474 -p 7687:7687 \\")
        print("    -e NEO4J_AUTH=neo4j/password neo4j:latest")
        return
    
    with agent:
        # Load CKG into databases
        print("\n[3] Loading CKG into Neo4j and FAISS vector store...")
        try:
            agent.load_ckg(ckg_data)
            print("    ✓ CKG loaded successfully")
        except Exception as e:
            print(f"    ❌ Failed to load CKG: {e}")
            traceback.print_exc()
            return
        
        # Add historical fixes
        print("\n[4] Adding historical fixes to SQLite...")
        for fix in HISTORICAL_FIXES:
            agent.add_historical_fix(
                case_id=fix.case_id,
                root_cause=fix.root_cause,
                symptom_summary=fix.symptom_summary,
                metrics=fix.metrics,
                fix_description=fix.fix_description,
                resolution_notes=fix.resolution_notes,
            )
        print(f"    ✓ Added {len(HISTORICAL_FIXES)} historical fixes")
        
        # Save vector store
        agent.save_vector_store(str(vector_store_path))
        print(f"    ✓ Vector store saved to: {vector_store_path}")
        
        # Run diagnosis for each test case
        print("\n[5] Running diagnosis for each test case...")
        results = []
        
        for test_case in TEST_CASES:
            print(f"\n{'='*70}")
            print(f"Test: {test_case.name}")
            print("="*70)
            print(f"Query:\n{test_case.query.strip()}")
            
            try:
                diagnosis = agent.diagnose(test_case.query)
                
                # Check results
                rc_match, rc_found = check_keywords(
                    diagnosis.root_cause, 
                    test_case.expected_root_cause
                )
                chain_match, chain_found = check_keywords(
                    diagnosis.causal_chain + diagnosis.diagnosis,
                    test_case.expected_causal_elements
                )
                
                result = {
                    "name": test_case.name,
                    "root_cause_match": rc_match,
                    "root_cause_found": rc_found,
                    "root_cause_expected": test_case.expected_root_cause,
                    "causal_match": chain_match,
                    "causal_found": chain_found,
                    "causal_expected": test_case.expected_causal_elements,
                    "agent_response": {
                        "root_cause": diagnosis.root_cause,
                        "causal_chain": diagnosis.causal_chain,
                        "diagnosis": diagnosis.diagnosis,
                        "historical_fixes": diagnosis.historical_fixes,
                    },
                    "ground_truth": test_case.ground_truth_summary.strip(),
                }
                results.append(result)
                
                # Print comparison
                print(f"\n--- Agent Response ---")
                print(f"Root Cause: {diagnosis.root_cause[:200]}...")
                print(f"Causal Chain: {diagnosis.causal_chain[:200]}...")
                
                print(f"\n--- Ground Truth ---")
                print(test_case.ground_truth_summary.strip())
                
                print(f"\n--- Comparison ---")
                rc_status = "✓ PASS" if rc_match else "✗ FAIL"
                chain_status = "✓ PASS" if chain_match else "✗ FAIL"
                print(f"{rc_status} Root Cause: expected {test_case.expected_root_cause}, found {rc_found}")
                print(f"{chain_status} Causal Elements: expected {test_case.expected_causal_elements}, found {chain_found}")
                
            except Exception as e:
                print(f"❌ Diagnosis failed: {e}")
                traceback.print_exc()
                results.append({
                    "name": test_case.name,
                    "error": str(e),
                })
        
        # Save results
        report_path = output_dir / "production_comparison_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        
        passed_rc = sum(1 for r in results if r.get("root_cause_match", False))
        passed_causal = sum(1 for r in results if r.get("causal_match", False))
        total = len(results)
        
        print(f"Root Cause Detection: {passed_rc}/{total} passed")
        print(f"Causal Element Detection: {passed_causal}/{total} passed")
        print(f"Overall: {passed_rc + passed_causal}/{total * 2} checks passed")
        print(f"\nComparison report saved to: {report_path}")
        print("=" * 70)


if __name__ == "__main__":
    run_production_test()
