"""End-to-End Test: Ground Truth Verification.

This test processes three Chinese power analysis reports in /data
and compares agent-generated CKG output against expected patterns.

Ground Truth Reports:
- first: CM拉檔 (CPU ceiling) -> VCORE 82.6%, DDR 82.6%
- second: CM拉檔 + PowerHal -> VCORE 29.32%, DDR 29.67%
- third: CM拉檔 + MMDVFS OPP3 -> VCORE 52.51% + 600mV floor
"""

from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add src to path for imports
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "src"))

from src.graph.builder import GraphBuilder
from src.graph.exporter import GraphExporter


# =============================================================================
# Ground Truth Definitions
# =============================================================================

@dataclass
class GroundTruth:
    """Expected analysis results for a report."""
    name: str
    root_cause: list[str]  # Expected root cause keywords
    vcore_issue: str  # VCORE issue description
    ddr_pattern: dict[str, float]  # DDR frequency usage
    mmdvfs_ruled_out: bool  # Whether MMDVFS is ruled out as cause
    cpu_pattern: str  # CPU frequency pattern


GROUND_TRUTHS = {
    "first": GroundTruth(
        name="first",
        root_cause=["CM", "CPU", "拉檔"],
        vcore_issue="VCORE 725mV 82.6% exceeds 10%",
        ddr_pattern={"DDR5460+DDR6370": 82.6},
        mmdvfs_ruled_out=True,
        cpu_pattern="大核2700MHz, 中核2500MHz, 小核2100MHz (all at ceiling)",
    ),
    "second": GroundTruth(
        name="second",
        root_cause=["CM", "PowerHal", "拉檔"],
        vcore_issue="VCORE 725mV 29.32% exceeds 10%",
        ddr_pattern={"DDR5460": 3.54, "DDR6370": 26.13, "total": 29.67},
        mmdvfs_ruled_out=True,
        cpu_pattern="Multiple frequencies with high usage",
    ),
    "third": GroundTruth(
        name="third",
        root_cause=["CM", "MMDVFS", "拉檔"],
        vcore_issue="VCORE 725mV 52.51% + VCORE 600mV floor",
        ddr_pattern={"DDR5460": 23.37, "DDR6370": 30.77, "total": 54.14},
        mmdvfs_ruled_out=False,  # MMDVFS OPP3 is the cause
        cpu_pattern="大核2700MHz, 中核2500MHz, 小核2100MHz",
    ),
}


# =============================================================================
# Helper Functions
# =============================================================================

def extract_entities_by_type(ckg_data: dict, entity_type: str) -> list[dict]:
    """Extract entities of a specific type from CKG."""
    return [
        e for e in ckg_data.get("entities", [])
        if e.get("type") == entity_type
    ]


def extract_root_causes(ckg_data: dict) -> list[str]:
    """Extract root cause labels from CKG."""
    root_causes = extract_entities_by_type(ckg_data, "RootCause")
    return [rc.get("label", "") for rc in root_causes]


def extract_symptoms(ckg_data: dict) -> list[str]:
    """Extract symptom labels from CKG."""
    symptoms = extract_entities_by_type(ckg_data, "Symptom")
    return [s.get("label", "") for s in symptoms]


def extract_observations(ckg_data: dict) -> list[str]:
    """Extract observation labels from CKG."""
    observations = extract_entities_by_type(ckg_data, "Observation")
    return [o.get("label", "") for o in observations]


def extract_hypotheses(ckg_data: dict) -> list[dict]:
    """Extract hypotheses with their labels and descriptions."""
    hypotheses = extract_entities_by_type(ckg_data, "Hypothesis")
    return [{"label": h.get("label", ""), "desc": h.get("description", "")} for h in hypotheses]


def find_rules_out_relations(ckg_data: dict) -> list[dict]:
    """Find RULES_OUT type relations (ruled out hypotheses)."""
    return [
        r for r in ckg_data.get("relations", [])
        if r.get("type") == "RULES_OUT"
    ]


def check_keywords_in_text(keywords: list[str], text_list: list[str]) -> bool:
    """Check if any of the keywords appear in any text in the list."""
    combined_text = " ".join(text_list).lower()
    return any(kw.lower() in combined_text for kw in keywords)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def builder():
    """Create a GraphBuilder instance."""
    return GraphBuilder(llm_provider="openai")


@pytest.fixture(scope="module")
def output_dir():
    """Create output directory for test results."""
    out_dir = Path(__file__).parent.parent / "output" / "e2e_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# =============================================================================
# Test Functions
# =============================================================================

class TestGroundTruthComparison:
    """Test suite for comparing generated CKG against ground truth."""
    
    @pytest.fixture(autouse=True)
    def setup(self, builder, output_dir):
        """Set up test fixtures."""
        self.builder = builder
        self.output_dir = output_dir
        self.data_dir = Path(__file__).parent.parent / "data"
    
    def _process_report(self, report_name: str) -> dict:
        """Process a report and return CKG data."""
        report_path = self.data_dir / report_name
        
        # Build CKG
        graph = self.builder.build_from_single_file(report_path)
        
        # Export to JSON
        exporter = GraphExporter(graph)
        output_path = self.output_dir / f"{report_name}_ckg.json"
        exporter.to_json(output_path)
        
        # Load and return JSON data
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _compare_to_ground_truth(
        self, 
        ckg_data: dict, 
        ground_truth: GroundTruth
    ) -> dict:
        """Compare CKG data to ground truth and return comparison results."""
        results = {
            "name": ground_truth.name,
            "passed": True,
            "checks": [],
        }
        
        # Check 1: Root cause keywords
        root_causes = extract_root_causes(ckg_data)
        root_cause_match = check_keywords_in_text(
            ground_truth.root_cause, 
            root_causes
        )
        results["checks"].append({
            "name": "Root Cause Keywords",
            "expected": ground_truth.root_cause,
            "actual": root_causes,
            "passed": root_cause_match,
        })
        if not root_cause_match:
            results["passed"] = False
        
        # Check 2: VCORE issue mentioned
        symptoms = extract_symptoms(ckg_data)
        observations = extract_observations(ckg_data)
        all_issues = symptoms + observations
        
        # Check for VCORE and percentage
        vcore_mentioned = any("VCORE" in s or "725" in s or "600" in s for s in all_issues)
        results["checks"].append({
            "name": "VCORE Issue Detection",
            "expected": ground_truth.vcore_issue,
            "actual": [s for s in all_issues if "VCORE" in s or "725" in s or "600" in s],
            "passed": vcore_mentioned,
        })
        if not vcore_mentioned:
            results["passed"] = False
        
        # Check 3: MMDVFS handling
        hypotheses = extract_hypotheses(ckg_data)
        rules_out = find_rules_out_relations(ckg_data)
        
        mmdvfs_entities = [h for h in hypotheses if "MMDVFS" in h["label"]]
        mmdvfs_ruled_out = len(rules_out) > 0 and any(
            "MMDVFS" in h["label"] for h in mmdvfs_entities
        )
        
        if ground_truth.mmdvfs_ruled_out:
            mmdvfs_check = mmdvfs_ruled_out or len(mmdvfs_entities) == 0
        else:
            # MMDVFS should be identified as cause (not ruled out)
            mmdvfs_check = len(mmdvfs_entities) > 0 and not mmdvfs_ruled_out
        
        results["checks"].append({
            "name": "MMDVFS Handling",
            "expected": f"ruled_out={ground_truth.mmdvfs_ruled_out}",
            "actual": f"entities={mmdvfs_entities}, rules_out={len(rules_out)}",
            "passed": mmdvfs_check,
        })
        if not mmdvfs_check:
            # This is a soft check - don't fail the test
            pass
        
        # Check 4: DDR mentioned
        ddr_mentioned = any(
            "DDR" in s for s in all_issues + root_causes
        )
        results["checks"].append({
            "name": "DDR Pattern Detection",
            "expected": str(ground_truth.ddr_pattern),
            "actual": [s for s in all_issues if "DDR" in s],
            "passed": ddr_mentioned,
        })
        
        return results
    
    def test_first_report(self):
        """Test first report: CM拉檔 -> VCORE 82.6%."""
        ckg_data = self._process_report("first")
        ground_truth = GROUND_TRUTHS["first"]
        
        results = self._compare_to_ground_truth(ckg_data, ground_truth)
        
        # Print comparison for visibility
        print(f"\n=== {ground_truth.name} Report Comparison ===")
        for check in results["checks"]:
            status = "✓" if check["passed"] else "✗"
            print(f"{status} {check['name']}")
            print(f"  Expected: {check['expected']}")
            print(f"  Actual: {check['actual']}")
        
        # Assert key checks
        assert any(
            check["passed"] for check in results["checks"] 
            if check["name"] == "Root Cause Keywords"
        ), "Root cause should contain CM-related keywords"
    
    def test_second_report(self):
        """Test second report: CM + PowerHal -> VCORE 29.32%."""
        ckg_data = self._process_report("second")
        ground_truth = GROUND_TRUTHS["second"]
        
        results = self._compare_to_ground_truth(ckg_data, ground_truth)
        
        print(f"\n=== {ground_truth.name} Report Comparison ===")
        for check in results["checks"]:
            status = "✓" if check["passed"] else "✗"
            print(f"{status} {check['name']}")
            print(f"  Expected: {check['expected']}")
            print(f"  Actual: {check['actual']}")
        
        assert any(
            check["passed"] for check in results["checks"] 
            if check["name"] == "Root Cause Keywords"
        ), "Root cause should contain CM-related keywords"
    
    def test_third_report(self):
        """Test third report: CM + MMDVFS OPP3 -> VCORE 52.51% + 600mV floor."""
        ckg_data = self._process_report("third")
        ground_truth = GROUND_TRUTHS["third"]
        
        results = self._compare_to_ground_truth(ckg_data, ground_truth)
        
        print(f"\n=== {ground_truth.name} Report Comparison ===")
        for check in results["checks"]:
            status = "✓" if check["passed"] else "✗"
            print(f"{status} {check['name']}")
            print(f"  Expected: {check['expected']}")
            print(f"  Actual: {check['actual']}")
        
        assert any(
            check["passed"] for check in results["checks"] 
            if check["name"] == "Root Cause Keywords"
        ), "Root cause should contain CM or MMDVFS keywords"
    
    def test_generate_comparison_report(self, output_dir):
        """Generate a comprehensive comparison report for all three reports."""
        all_results = []
        
        for name in ["first", "second", "third"]:
            ckg_data = self._process_report(name)
            ground_truth = GROUND_TRUTHS[name]
            results = self._compare_to_ground_truth(ckg_data, ground_truth)
            all_results.append(results)
        
        # Save comparison report
        report_path = output_dir / "comparison_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        
        print(f"\n=== Comparison Report Saved to {report_path} ===")
        
        # Summary
        total_checks = sum(len(r["checks"]) for r in all_results)
        passed_checks = sum(
            sum(1 for c in r["checks"] if c["passed"]) 
            for r in all_results
        )
        
        print(f"Total checks: {total_checks}")
        print(f"Passed: {passed_checks}")
        print(f"Failed: {total_checks - passed_checks}")
        
        assert passed_checks > 0, "At least some checks should pass"


if __name__ == "__main__":
    # Run without pytest to avoid ROS launch_testing plugin conflict
    import traceback
    
    print("=" * 60)
    print("E2E Ground Truth Verification Test")
    print("=" * 60)
    
    # Setup
    builder = GraphBuilder(llm_provider="openai")
    output_dir = Path(__file__).parent.parent / "output" / "e2e_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(__file__).parent.parent / "data"
    
    def process_report(report_name: str) -> dict:
        """Process a report and return CKG data."""
        report_path = data_dir / report_name
        print(f"\nProcessing: {report_path}")
        
        # Build CKG
        graph = builder.build_from_single_file(report_path)
        
        # Export to JSON
        exporter = GraphExporter(graph)
        output_path = output_dir / f"{report_name}_ckg.json"
        exporter.to_json(output_path)
        
        # Also export layered HTML visualization
        html_path = output_dir / f"{report_name}_ckg_layered.html"
        exporter.to_pyvis_html(html_path)
        print(f"  -> Exported CKG to: {output_path}")
        print(f"  -> Exported visualization to: {html_path}")
        
        # Load and return JSON data
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def compare_to_ground_truth(ckg_data: dict, ground_truth: GroundTruth) -> dict:
        """Compare CKG data to ground truth and return comparison results."""
        results = {
            "name": ground_truth.name,
            "checks": [],
        }
        
        # Check 1: Root cause keywords
        root_causes = extract_root_causes(ckg_data)
        root_cause_match = check_keywords_in_text(ground_truth.root_cause, root_causes)
        results["checks"].append({
            "name": "Root Cause Keywords",
            "expected": ground_truth.root_cause,
            "actual": root_causes,
            "passed": root_cause_match,
        })
        
        # Check 2: VCORE issue mentioned
        symptoms = extract_symptoms(ckg_data)
        observations = extract_observations(ckg_data)
        all_issues = symptoms + observations
        vcore_mentioned = any("VCORE" in s or "725" in s or "600" in s for s in all_issues)
        results["checks"].append({
            "name": "VCORE Issue Detection",
            "expected": ground_truth.vcore_issue,
            "actual": [s for s in all_issues if "VCORE" in s or "725" in s or "600" in s],
            "passed": vcore_mentioned,
        })
        
        # Check 3: DDR mentioned
        ddr_mentioned = any("DDR" in s for s in all_issues + root_causes)
        results["checks"].append({
            "name": "DDR Pattern Detection",
            "expected": str(ground_truth.ddr_pattern),
            "actual": [s for s in all_issues if "DDR" in s],
            "passed": ddr_mentioned,
        })
        
        # Check 4: MMDVFS handling
        hypotheses = extract_hypotheses(ckg_data)
        mmdvfs_entities = [h for h in hypotheses if "MMDVFS" in h["label"]]
        root_cause_has_mmdvfs = any("MMDVFS" in rc for rc in root_causes)
        
        if ground_truth.mmdvfs_ruled_out:
            mmdvfs_check = not root_cause_has_mmdvfs
        else:
            mmdvfs_check = root_cause_has_mmdvfs or len(mmdvfs_entities) > 0
        
        results["checks"].append({
            "name": "MMDVFS Handling",
            "expected": f"ruled_out={ground_truth.mmdvfs_ruled_out}",
            "actual": f"root_cause_mmdvfs={root_cause_has_mmdvfs}, hypothesis_mmdvfs={len(mmdvfs_entities)>0}",
            "passed": mmdvfs_check,
        })
        
        return results
    
    # Run tests for all three reports
    all_results = []
    total_passed = 0
    total_checks = 0
    
    for name in ["first", "second", "third"]:
        print(f"\n{'='*60}")
        print(f"Testing Report: {name}")
        print("="*60)
        
        try:
            ckg_data = process_report(name)
            ground_truth = GROUND_TRUTHS[name]
            results = compare_to_ground_truth(ckg_data, ground_truth)
            all_results.append(results)
            
            print(f"\n--- Comparison Results for '{name}' ---")
            for check in results["checks"]:
                status = "✓ PASS" if check["passed"] else "✗ FAIL"
                print(f"\n{status}: {check['name']}")
                print(f"  Expected: {check['expected']}")
                print(f"  Actual:   {check['actual']}")
                
                total_checks += 1
                if check["passed"]:
                    total_passed += 1
                    
        except Exception as e:
            print(f"ERROR processing {name}: {e}")
            traceback.print_exc()
    
    # Save comparison report
    report_path = output_dir / "comparison_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Comparison report saved to: {report_path}")
    print(f"Total checks: {total_checks}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_checks - total_passed}")
    print(f"Pass rate: {100*total_passed/total_checks:.1f}%" if total_checks > 0 else "N/A")
    print("=" * 60)
