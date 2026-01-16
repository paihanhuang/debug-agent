"""CKG Validation Module - Automated correctness verification for Causal Knowledge Graphs."""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .models import CausalGraph, EntityType


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        status = "✓" if self.passed else "✗"
        return f"{status} {self.name}: {self.message}"


@dataclass  
class ValidationReport:
    """Complete validation report for a CKG."""
    graph_name: str
    results: list[ValidationResult] = field(default_factory=list)
    
    @property
    def passed(self) -> bool:
        """True if all critical validations passed."""
        return all(r.passed for r in self.results)
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)
    
    def add(self, result: ValidationResult) -> None:
        self.results.append(result)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_name": self.graph_name,
            "overall_passed": self.passed,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            f"# CKG Validation Report: {self.graph_name}",
            "",
            f"**Overall Status**: {'✅ PASSED' if self.passed else '❌ FAILED'}",
            f"**Checks Passed**: {self.passed_count}/{len(self.results)}",
            "",
            "## Validation Results",
            "",
            "| Check | Status | Message |",
            "|-------|--------|---------|",
        ]
        
        for r in self.results:
            status = "✅" if r.passed else "❌"
            lines.append(f"| {r.name} | {status} | {r.message} |")
        
        # Add details for failures
        failures = [r for r in self.results if not r.passed]
        if failures:
            lines.extend(["", "## Issues Found", ""])
            for r in failures:
                lines.append(f"### {r.name}")
                for detail in r.details:
                    lines.append(f"- {detail}")
                lines.append("")
        
        return "\n".join(lines)
    
    def print_summary(self) -> None:
        """Print validation summary to console."""
        print("=" * 60)
        print(f"VALIDATION REPORT: {self.graph_name}")
        print("=" * 60)
        print()
        
        for result in self.results:
            print(result)
            for detail in result.details[:3]:  # Show first 3 details
                print(f"    {detail}")
        
        print()
        print("-" * 60)
        status = "✅ ALL CHECKS PASSED" if self.passed else "❌ SOME CHECKS FAILED"
        print(f"Result: {status} ({self.passed_count}/{len(self.results)})")
        print("-" * 60)


class CKGValidator:
    """Validates Causal Knowledge Graphs for correctness."""
    
    def __init__(self, graph: CausalGraph, name: str = "CKG"):
        """Initialize validator with a graph.
        
        Args:
            graph: The CausalGraph to validate.
            name: Name for the validation report.
        """
        self._graph = graph
        self._name = name
    
    @classmethod
    def from_json_file(cls, path: str | Path) -> "CKGValidator":
        """Load graph from JSON file and create validator."""
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        graph = CausalGraph.from_dict(data)
        return cls(graph, name=path.stem)
    
    def validate_all(self) -> ValidationReport:
        """Run all validation checks."""
        report = ValidationReport(graph_name=self._name)
        
        # Structural validations
        report.add(self._check_dag())
        report.add(self._check_no_self_loops())
        report.add(self._check_no_isolated_entities())
        
        # Semantic validations
        report.add(self._check_root_causes_exist())
        report.add(self._check_symptoms_exist())
        report.add(self._check_symptoms_traceable())
        report.add(self._check_root_causes_have_effects())
        
        # Causal quality checks
        report.add(self._check_causal_effects_present())
        report.add(self._check_causal_strength_range())
        
        return report
    
    def _check_dag(self) -> ValidationResult:
        """Check that graph is a valid DAG (no cycles)."""
        is_dag = self._graph.is_valid_dag()
        if is_dag:
            return ValidationResult(
                name="DAG Structure",
                passed=True,
                message="Graph is a valid Directed Acyclic Graph",
            )
        else:
            import networkx as nx
            cycles = list(nx.simple_cycles(self._graph.networkx_graph))
            return ValidationResult(
                name="DAG Structure",
                passed=False,
                message=f"Graph contains {len(cycles)} cycle(s)",
                details=[f"Cycle: {' → '.join(c)}" for c in cycles[:5]],
            )
    
    def _check_no_self_loops(self) -> ValidationResult:
        """Check that no entity has a relation to itself."""
        self_loops = []
        for rel in self._graph.get_relations():
            if rel.source_id == rel.target_id:
                self_loops.append(rel.source_id)
        
        if not self_loops:
            return ValidationResult(
                name="No Self-Loops",
                passed=True,
                message="No self-referential relations found",
            )
        else:
            return ValidationResult(
                name="No Self-Loops",
                passed=False,
                message=f"Found {len(self_loops)} self-loop(s)",
                details=[f"Entity {e} has self-loop" for e in self_loops],
            )
    
    def _check_no_isolated_entities(self) -> ValidationResult:
        """Check that all entities participate in at least one relation."""
        import networkx as nx
        isolated = list(nx.isolates(self._graph.networkx_graph))
        
        if not isolated:
            return ValidationResult(
                name="No Isolated Entities",
                passed=True,
                message="All entities connected",
            )
        else:
            entity_labels = []
            for eid in isolated:
                e = self._graph.get_entity(eid)
                entity_labels.append(f"{eid}: {e.label if e else 'Unknown'}")
            return ValidationResult(
                name="No Isolated Entities",
                passed=False,
                message=f"Found {len(isolated)} isolated entit(ies)",
                details=entity_labels,
            )
    
    def _check_root_causes_exist(self) -> ValidationResult:
        """Check that at least one root cause is identified."""
        root_causes = self._graph.get_root_causes()
        
        if root_causes:
            return ValidationResult(
                name="Root Causes Exist",
                passed=True,
                message=f"Found {len(root_causes)} root cause(s)",
                details=[rc.label for rc in root_causes],
            )
        else:
            return ValidationResult(
                name="Root Causes Exist",
                passed=False,
                message="No root causes identified",
            )
    
    def _check_symptoms_exist(self) -> ValidationResult:
        """Check that at least one symptom is identified."""
        symptoms = self._graph.get_entities(EntityType.SYMPTOM)
        
        if symptoms:
            return ValidationResult(
                name="Symptoms Exist",
                passed=True,
                message=f"Found {len(symptoms)} symptom(s)",
                details=[s.label for s in symptoms],
            )
        else:
            return ValidationResult(
                name="Symptoms Exist",
                passed=False,
                message="No symptoms identified",
            )
    
    def _check_symptoms_traceable(self) -> ValidationResult:
        """Check that all symptoms can be traced back to a root cause."""
        symptoms = self._graph.get_entities(EntityType.SYMPTOM)
        untraceable = []
        
        for symptom in symptoms:
            upstream = self._graph.get_upstream_causes(symptom.id)
            has_root = any(e.entity_type == EntityType.ROOT_CAUSE for e in upstream)
            if not has_root:
                untraceable.append(symptom.label)
        
        if not untraceable:
            return ValidationResult(
                name="Symptoms Traceable",
                passed=True,
                message="All symptoms traceable to root cause(s)",
            )
        else:
            return ValidationResult(
                name="Symptoms Traceable",
                passed=False,
                message=f"{len(untraceable)} symptom(s) not traceable to root cause",
                details=untraceable,
            )
    
    def _check_root_causes_have_effects(self) -> ValidationResult:
        """Check that all root causes lead to at least one symptom."""
        root_causes = self._graph.get_root_causes()
        ineffective = []
        
        for rc in root_causes:
            downstream = self._graph.get_downstream_effects(rc.id)
            has_symptom = any(e.entity_type == EntityType.SYMPTOM for e in downstream)
            if not has_symptom:
                ineffective.append(rc.label)
        
        if not ineffective:
            return ValidationResult(
                name="Root Causes Effective",
                passed=True,
                message="All root causes lead to symptom(s)",
            )
        else:
            return ValidationResult(
                name="Root Causes Effective",
                passed=False,
                message=f"{len(ineffective)} root cause(s) have no path to symptoms",
                details=ineffective,
            )
    
    def _check_causal_effects_present(self) -> ValidationResult:
        """Check that causal relations have causal_effect specified."""
        causal_rels = self._graph.get_causal_relations_only()
        missing = []
        
        for rel in causal_rels:
            if rel.causal_effect is None:
                src = self._graph.get_entity(rel.source_id)
                tgt = self._graph.get_entity(rel.target_id)
                missing.append(f"{src.label if src else rel.source_id} → {tgt.label if tgt else rel.target_id}")
        
        if not missing:
            return ValidationResult(
                name="Causal Effects Specified",
                passed=True,
                message="All causal relations have effect quantification",
            )
        else:
            return ValidationResult(
                name="Causal Effects Specified",
                passed=False,
                message=f"{len(missing)} causal relation(s) missing effect",
                details=missing[:5],
            )
    
    def _check_causal_strength_range(self) -> ValidationResult:
        """Check that causal strengths are in valid range [-1.0, 1.0]."""
        invalid = []
        
        for rel in self._graph.get_causal_relations_only():
            if rel.causal_effect:
                strength = rel.causal_effect.strength
                if not (-1.0 <= strength <= 1.0):
                    invalid.append(f"Strength {strength} out of range")
        
        if not invalid:
            return ValidationResult(
                name="Causal Strength Range",
                passed=True,
                message="All causal strengths in valid range [-1.0, 1.0]",
            )
        else:
            return ValidationResult(
                name="Causal Strength Range",
                passed=False,
                message=f"{len(invalid)} invalid strength value(s)",
                details=invalid,
            )


def validate_ckg(graph_or_path: CausalGraph | str | Path, name: str = None) -> ValidationReport:
    """Convenience function to validate a CKG.
    
    Args:
        graph_or_path: Either a CausalGraph object or path to JSON file.
        name: Optional name for the report.
        
    Returns:
        ValidationReport with all check results.
    """
    if isinstance(graph_or_path, (str, Path)):
        validator = CKGValidator.from_json_file(graph_or_path)
    else:
        validator = CKGValidator(graph_or_path, name=name or "CKG")
    
    return validator.validate_all()


# CLI entry point
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.graph.validator <ckg.json>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    report = validate_ckg(json_path)
    report.print_summary()
    
    # Exit with error code if validation failed
    sys.exit(0 if report.passed else 1)
