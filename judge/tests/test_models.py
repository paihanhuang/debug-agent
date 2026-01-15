"""Unit tests for Judge module - Models."""

import pytest
from judge.models import (
    DimensionScore,
    EvaluationResult,
    ScoreLevel,
    DEFAULT_WEIGHTS,
)


class TestDimensionScore:
    """Tests for DimensionScore dataclass."""
    
    def test_dimension_score_creation(self):
        """Test basic dimension score creation."""
        score = DimensionScore(
            name="Root Cause Accuracy",
            score=4,
            weight=0.50,
            explanation="Correctly identified CM as root cause",
            matched_elements=["CM", "CPU Manager"],
            missing_elements=["拉檔"],
        )
        
        assert score.name == "Root Cause Accuracy"
        assert score.score == 4
        assert score.weight == 0.50
        assert "CM" in score.matched_elements
    
    def test_weighted_score_calculation(self):
        """Test weighted score calculation."""
        score = DimensionScore(
            name="Test",
            score=4,
            weight=0.50,
            explanation="",
        )
        
        assert score.weighted_score() == 2.0  # 4 * 0.50
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        score = DimensionScore(
            name="Test",
            score=5,
            weight=0.20,
            explanation="Perfect",
            matched_elements=["A", "B"],
            missing_elements=[],
        )
        
        result = score.to_dict()
        assert result["name"] == "Test"
        assert result["score"] == 5
        assert result["weighted_score"] == 1.0


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""
    
    def test_calculate_composite(self):
        """Test composite score calculation with user weights."""
        dimensions = [
            DimensionScore("Root Cause Accuracy", 9, 0.50, ""),
            DimensionScore("Causal Chain Completeness", 8, 0.20, ""),
            DimensionScore("Metric Precision", 8, 0.15, ""),
            DimensionScore("Reasoning Quality", 7, 0.10, ""),
            DimensionScore("Actionability", 7, 0.05, ""),
        ]
        
        composite = EvaluationResult.calculate_composite(dimensions)
        # Expected: (9*0.50 + 8*0.20 + 8*0.15 + 7*0.10 + 7*0.05) / 1.0
        # = (4.5 + 1.6 + 1.2 + 0.7 + 0.35) / 1.0 = 8.35
        assert composite == 8.35
    
    def test_grade_a(self):
        """Test A grade (>= 8.0 on 1-10 scale)."""
        result = EvaluationResult(
            case_name="test",
            dimensions=[],
            composite_score=8.5,
            summary="",
            human_report_path="",
            agent_report_path="",
        )
        assert result.grade() == "A"
    
    def test_grade_b(self):
        """Test B grade (7.0 - 7.99 on 1-10 scale)."""
        result = EvaluationResult(
            case_name="test",
            dimensions=[],
            composite_score=7.5,
            summary="",
            human_report_path="",
            agent_report_path="",
        )
        assert result.grade() == "B"
    
    def test_grade_c(self):
        """Test C grade (6.0 - 6.99 on 1-10 scale)."""
        result = EvaluationResult(
            case_name="test",
            dimensions=[],
            composite_score=6.5,
            summary="",
            human_report_path="",
            agent_report_path="",
        )
        assert result.grade() == "C"
    
    def test_to_dict(self):
        """Test full dictionary conversion."""
        dimensions = [
            DimensionScore("Test", 4, 0.50, "Good"),
        ]
        result = EvaluationResult(
            case_name="Case 1",
            dimensions=dimensions,
            composite_score=8.0,
            summary="Overall good",
            human_report_path="/path/human",
            agent_report_path="/path/agent",
        )
        
        d = result.to_dict()
        assert d["case_name"] == "Case 1"
        assert d["composite_score"] == 8.0
        assert d["grade"] == "A"
        assert len(d["dimensions"]) == 1


class TestDefaultWeights:
    """Tests for default weight configuration."""
    
    def test_weights_sum_to_one(self):
        """Verify weights sum to 1.0."""
        total = sum(DEFAULT_WEIGHTS.values())
        assert total == 1.0
    
    def test_root_cause_has_highest_weight(self):
        """Root cause accuracy should have highest weight (50%)."""
        assert DEFAULT_WEIGHTS["root_cause_accuracy"] == 0.50
    
    def test_actionability_has_lowest_weight(self):
        """Actionability should have lowest weight (5%)."""
        assert DEFAULT_WEIGHTS["actionability"] == 0.05
