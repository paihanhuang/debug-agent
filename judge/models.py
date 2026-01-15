"""Report Quality Judge - Data Models.

Defines the data structures for evaluation results.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ScoreLevel(Enum):
    """Score levels for evaluation dimensions (1-10 scale)."""
    PERFECT = 10      # Exceeds human expert
    EXCELLENT = 9     # Fully matches human expert
    VERY_GOOD = 8     # Minor details missing
    GOOD = 7          # Correct overall, some omissions
    SATISFACTORY = 6  # Core elements present
    ADEQUATE = 5      # Basic understanding shown
    MARGINAL = 4      # Significant gaps
    POOR = 3          # Major errors or omissions
    VERY_POOR = 2     # Fundamentally flawed
    FAIL = 1          # Completely incorrect or missing


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""
    name: str
    score: int  # 1-10
    weight: float  # 0.0-1.0
    explanation: str
    matched_elements: list[str] = field(default_factory=list)
    missing_elements: list[str] = field(default_factory=list)
    
    def weighted_score(self) -> float:
        """Calculate weighted score contribution."""
        return self.score * self.weight
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "explanation": self.explanation,
            "matched_elements": self.matched_elements,
            "missing_elements": self.missing_elements,
            "weighted_score": self.weighted_score(),
        }


@dataclass
class EvaluationResult:
    """Complete evaluation result for a single report comparison (1-10 scale)."""
    case_name: str
    dimensions: list[DimensionScore]
    composite_score: float  # 1.0-5.0 weighted average
    summary: str
    human_report_path: str
    agent_report_path: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    @classmethod
    def calculate_composite(cls, dimensions: list[DimensionScore]) -> float:
        """Calculate weighted average composite score."""
        if not dimensions:
            return 0.0
        total_weight = sum(d.weight for d in dimensions)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(d.weighted_score() for d in dimensions)
        return round(weighted_sum / total_weight, 2)
    
    def grade(self) -> str:
        """Get letter grade based on composite score (1-10 scale)."""
        if self.composite_score >= 9.0:
            return "A+"
        elif self.composite_score >= 8.0:
            return "A"
        elif self.composite_score >= 7.0:
            return "B"
        elif self.composite_score >= 6.0:
            return "C"
        elif self.composite_score >= 5.0:
            return "D"
        else:
            return "F"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "case_name": self.case_name,
            "composite_score": self.composite_score,
            "grade": self.grade(),
            "summary": self.summary,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "human_report_path": self.human_report_path,
            "agent_report_path": self.agent_report_path,
            "timestamp": self.timestamp,
        }


# Default dimension weights (user-adjusted)
DEFAULT_WEIGHTS = {
    "root_cause_accuracy": 0.50,
    "causal_chain_completeness": 0.20,
    "metric_precision": 0.15,
    "reasoning_quality": 0.10,
    "actionability": 0.05,
}
