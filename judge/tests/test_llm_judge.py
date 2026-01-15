"""Unit tests for LLM Judge module - Multi-Provider Support."""

from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest

from judge.models import DimensionScore, EvaluationResult


class TestLLMReportJudge:
    """Tests for LLMReportJudge class with mocked LLM calls."""
    
    @patch("judge.llm_judge.Anthropic")
    def test_judge_initialization_anthropic_default(self, mock_anthropic):
        """Test judge initializes with Claude as default (since Phase 2 update)."""
        from judge.llm_judge import LLMReportJudge, LLMProvider
        
        judge = LLMReportJudge(api_key="test-key")
        assert judge._model == "claude-3-5-sonnet-20241022"
        assert judge._provider == LLMProvider.ANTHROPIC
        mock_anthropic.assert_called_once_with(api_key="test-key")
    
    @patch("judge.llm_judge.OpenAI")
    def test_judge_initialization_openai_explicit(self, mock_openai):
        """Test judge initializes with OpenAI when explicitly requested."""
        from judge.llm_judge import LLMReportJudge, LLMProvider
        
        judge = LLMReportJudge(provider="openai", api_key="test-key")
        assert judge._model == "gpt-4o"
        assert judge._provider == LLMProvider.OPENAI
        mock_openai.assert_called_once_with(api_key="test-key")
    
    @patch("judge.llm_judge.OpenAI")
    def test_evaluate_returns_result(self, mock_openai):
        """Test evaluate returns EvaluationResult with OpenAI provider."""
        from judge.llm_judge import LLMReportJudge
        
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "root_cause_accuracy": {
                "score": 5,
                "explanation": "Correctly identified CM",
                "matched_elements": ["CM", "CPU Manager"],
                "missing_elements": [],
            },
            "causal_chain_completeness": {
                "score": 4,
                "explanation": "Good causal chain",
                "matched_elements": ["CM → CPU"],
                "missing_elements": ["拉檔 terminology"],
            },
            "metric_precision": {
                "score": 4,
                "explanation": "Metrics correct",
                "matched_elements": ["VCORE 82.6%"],
                "missing_elements": [],
            },
            "reasoning_quality": {
                "score": 4,
                "explanation": "Logical reasoning",
                "matched_elements": [],
                "missing_elements": [],
            },
            "actionability": {
                "score": 3,
                "explanation": "Some suggestions",
                "matched_elements": [],
                "missing_elements": [],
            },
            "summary": "Good overall match",
        })
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client
        
        judge = LLMReportJudge(provider="openai", api_key="test-key")
        
        result = judge.evaluate(
            human_report="Human expert report content",
            agent_report="Agent report content",
            case_name="test_case",
        )
        
        assert isinstance(result, EvaluationResult)
        assert result.case_name == "test_case"
        assert len(result.dimensions) == 5
        assert result.composite_score > 0
    
    @patch("judge.llm_judge.OpenAI")
    def test_evaluate_calculates_weighted_score(self, mock_openai):
        """Test composite score calculation."""
        from judge.llm_judge import LLMReportJudge
        
        # All dimensions score 4
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "root_cause_accuracy": {"score": 7, "explanation": "", "matched_elements": [], "missing_elements": []},
            "causal_chain_completeness": {"score": 7, "explanation": "", "matched_elements": [], "missing_elements": []},
            "metric_precision": {"score": 7, "explanation": "", "matched_elements": [], "missing_elements": []},
            "reasoning_quality": {"score": 7, "explanation": "", "matched_elements": [], "missing_elements": []},
            "actionability": {"score": 7, "explanation": "", "matched_elements": [], "missing_elements": []},
            "summary": "All 7s",
        })
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client
        
        judge = LLMReportJudge(provider="openai", api_key="test-key")
        result = judge.evaluate("human", "agent", "test")
        
        # All 7s should give composite of 7.0 (B grade)
        assert result.composite_score == 7.0
        assert result.grade() == "B"
    
    def test_judge_requires_api_key_anthropic(self):
        """Test Claude judge raises error without API key."""
        from judge.llm_judge import LLMReportJudge
        
        with patch.dict("os.environ", {}, clear=True):
            with patch("judge.llm_judge.os.getenv", return_value=None):
                with pytest.raises(ValueError, match="Anthropic API key required"):
                    LLMReportJudge(provider="anthropic")
    
    def test_judge_requires_api_key_openai(self):
        """Test OpenAI judge raises error without API key."""
        from judge.llm_judge import LLMReportJudge
        
        with patch.dict("os.environ", {}, clear=True):
            with patch("judge.llm_judge.os.getenv", return_value=None):
                with pytest.raises(ValueError, match="OpenAI API key required"):
                    LLMReportJudge(provider="openai")


class TestEvaluationPrompt:
    """Tests for the evaluation prompt structure."""
    
    def test_prompt_includes_dimensions(self):
        """Verify prompt includes all 5 dimensions."""
        from judge.llm_judge import EVALUATION_PROMPT
        
        dimensions = [
            "Root Cause Accuracy",
            "Causal Chain Completeness",
            "Metric Precision",
            "Reasoning Quality",
            "Actionability",
        ]
        
        for dim in dimensions:
            assert dim in EVALUATION_PROMPT
    
    def test_prompt_includes_weights(self):
        """Verify prompt includes weight percentages."""
        from judge.llm_judge import EVALUATION_PROMPT
        
        weights = ["50%", "20%", "15%", "10%", "5%"]
        for weight in weights:
            assert weight in EVALUATION_PROMPT
