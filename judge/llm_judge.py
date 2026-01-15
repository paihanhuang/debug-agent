"""Report Quality Judge - Multi-Provider LLM Evaluation.

Supports both OpenAI (GPT-4o) and Anthropic (Claude-3.5-Sonnet) for evaluation.
"""

from __future__ import annotations
import json
import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Anthropic import (optional)
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .models import DimensionScore, EvaluationResult, DEFAULT_WEIGHTS

load_dotenv()


class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


EVALUATION_PROMPT = """You are an expert evaluator for power debugging analysis reports.
Your task is to score an agent-generated report against a human expert report (gold standard).

## Language Equivalence Rule
Treat Chinese and English terms as EQUIVALENT. For example:
- "拉檔" = "frequency throttling" = "pulling frequency"
- "調控策略" = "control policy"
- "大核/中核/小核" = "large/medium/small cores"
- "投票機制" = "voting mechanism"

## Human Expert Report (Gold Standard)
{human_report}

## Agent Generated Report
{agent_report}

## Scoring Instructions

Score the agent report on these 5 dimensions using a 1-10 scale:
- 10 = Perfect: Exceeds human expert analysis
- 9 = Excellent: Fully matches human expert
- 8 = Very Good: Minor details missing
- 7 = Good: Correct overall with some omissions
- 6 = Satisfactory: Core elements present
- 5 = Adequate: Basic understanding shown
- 4 = Marginal: Significant gaps in analysis
- 3 = Poor: Major errors or omissions
- 2 = Very Poor: Fundamentally flawed
- 1 = Fail: Completely incorrect or missing

## Dimensions to Evaluate

1. **Root Cause Accuracy** (50% weight): Did the agent identify the correct root cause(s)?
   - Check if CM, PowerHal, MMDVFS, or other causes are correctly identified
   - Check if 拉檔 (frequency throttling) concept is captured (Chinese or English)
   - Treat "CM" = "CPU Manager" as equivalent

2. **Causal Chain Completeness** (20% weight): Are all causal links captured?
   - Check CM → CPU → DDR → VCORE chain
   - Check if SW_REQ2/SW_REQ3 voting mechanisms are mentioned

3. **Metric Precision** (15% weight): Are specific metrics correctly identified?
   - Check VCORE percentages (82.6%, 29.32%, 52.51%)
   - Check DDR percentages (DDR5460, DDR6370)
   - Check CPU frequencies (2700MHz, 2500MHz, 2100MHz)

4. **Reasoning Quality** (10% weight): Is the diagnostic reasoning logical?
   - Check if MMDVFS is correctly ruled out or identified as cause
   - Check if the explanation flows logically

5. **Actionability** (5% weight): Are suggested fixes practical?
   - Check if historical fixes or recommendations are relevant

## Response Format

Return ONLY valid JSON (no markdown, no explanation):
{{
    "root_cause_accuracy": {{
        "score": <1-10>,
        "explanation": "<brief explanation>",
        "matched_elements": ["<element1>", "<element2>"],
        "missing_elements": ["<element1>", "<element2>"]
    }},
    "causal_chain_completeness": {{
        "score": <1-10>,
        "explanation": "<brief explanation>",
        "matched_elements": ["<element1>", "<element2>"],
        "missing_elements": ["<element1>", "<element2>"]
    }},
    "metric_precision": {{
        "score": <1-10>,
        "explanation": "<brief explanation>",
        "matched_elements": ["<element1>", "<element2>"],
        "missing_elements": ["<element1>", "<element2>"]
    }},
    "reasoning_quality": {{
        "score": <1-10>,
        "explanation": "<brief explanation>",
        "matched_elements": ["<element1>", "<element2>"],
        "missing_elements": ["<element1>", "<element2>"]
    }},
    "actionability": {{
        "score": <1-10>,
        "explanation": "<brief explanation>",
        "matched_elements": ["<element1>", "<element2>"],
        "missing_elements": ["<element1>", "<element2>"]
    }},
    "summary": "<overall assessment in 1-2 sentences>"
}}"""


class LLMReportJudge:
    """LLM-based judge for evaluating report quality.
    
    Supports multiple providers:
    - OpenAI: gpt-4o, gpt-4-turbo, etc.
    - Anthropic: claude-3-5-sonnet-20241022, claude-3-opus, etc.
    """
    
    def __init__(
        self,
        provider: str | LLMProvider = LLMProvider.ANTHROPIC,
        model: str | None = None,
        api_key: str | None = None,
        weights: dict[str, float] | None = None,
    ):
        """Initialize the judge.
        
        Args:
            provider: LLM provider ("openai" or "anthropic")
            model: Model name (default: claude-3-5-sonnet for anthropic, gpt-4o for openai)
            api_key: API key (default: from environment)
            weights: Custom dimension weights (default: DEFAULT_WEIGHTS)
        """
        # Normalize provider
        if isinstance(provider, str):
            provider = LLMProvider(provider.lower())
        self._provider = provider
        
        # Set default model based on provider
        if model is None:
            if provider == LLMProvider.ANTHROPIC:
                model = "claude-3-5-sonnet-20241022"
            else:
                model = "gpt-4o"
        self._model = model
        
        # Initialize client based on provider
        if provider == LLMProvider.ANTHROPIC:
            if not ANTHROPIC_AVAILABLE:
                raise ImportError(
                    "anthropic package required for Claude support. "
                    "Install with: pip install anthropic"
                )
            self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not self._api_key:
                raise ValueError("Anthropic API key required (set ANTHROPIC_API_KEY)")
            self._client = Anthropic(api_key=self._api_key)
        else:
            self._api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not self._api_key:
                raise ValueError("OpenAI API key required (set OPENAI_API_KEY)")
            self._client = OpenAI(api_key=self._api_key)
        
        self._weights = weights or DEFAULT_WEIGHTS
    
    def evaluate(
        self,
        human_report: str,
        agent_report: str,
        case_name: str = "unknown",
        human_report_path: str = "",
        agent_report_path: str = "",
    ) -> EvaluationResult:
        """Evaluate an agent report against human expert report.
        
        Args:
            human_report: Human expert report content (gold standard)
            agent_report: Agent generated report content
            case_name: Name/identifier for this case
            human_report_path: Path to human report file
            agent_report_path: Path to agent report file
            
        Returns:
            EvaluationResult with dimension scores and composite score
        """
        # Build prompt
        prompt = EVALUATION_PROMPT.format(
            human_report=human_report,
            agent_report=agent_report,
        )
        
        # Call LLM based on provider
        if self._provider == LLMProvider.ANTHROPIC:
            result_text = self._call_anthropic(prompt)
        else:
            result_text = self._call_openai(prompt)
        
        # Parse response - handle potential JSON in markdown code blocks
        result_text = self._extract_json(result_text)
        result_data = json.loads(result_text)
        
        # Build dimension scores
        dimensions = self._build_dimensions(result_data)
        
        # Calculate composite score
        composite = EvaluationResult.calculate_composite(dimensions)
        
        return EvaluationResult(
            case_name=case_name,
            dimensions=dimensions,
            composite_score=composite,
            summary=result_data.get("summary", ""),
            human_report_path=human_report_path,
            agent_report_path=agent_report_path,
        )
    
    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": f"You are a precise evaluation assistant. Return only valid JSON, no markdown formatting.\n\n{prompt}"
                }
            ],
        )
        return response.content[0].text
    
    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": "You are a precise evaluation assistant. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, handling markdown code blocks."""
        text = text.strip()
        
        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or not line.startswith("```"):
                    json_lines.append(line)
            text = "\n".join(json_lines)
        
        return text.strip()
    
    def _build_dimensions(self, result_data: dict) -> list[DimensionScore]:
        """Build dimension scores from LLM response."""
        dimensions = []
        dimension_keys = [
            ("root_cause_accuracy", "Root Cause Accuracy"),
            ("causal_chain_completeness", "Causal Chain Completeness"),
            ("metric_precision", "Metric Precision"),
            ("reasoning_quality", "Reasoning Quality"),
            ("actionability", "Actionability"),
        ]
        
        for key, name in dimension_keys:
            dim_data = result_data.get(key, {})
            dimensions.append(DimensionScore(
                name=name,
                score=dim_data.get("score", 1),
                weight=self._weights.get(key, 0.2),
                explanation=dim_data.get("explanation", ""),
                matched_elements=dim_data.get("matched_elements", []),
                missing_elements=dim_data.get("missing_elements", []),
            ))
        
        return dimensions
    
    def evaluate_from_files(
        self,
        human_report_path: str | Path,
        agent_report_path: str | Path,
        case_name: str | None = None,
    ) -> EvaluationResult:
        """Evaluate reports from file paths.
        
        Args:
            human_report_path: Path to human expert report
            agent_report_path: Path to agent generated report
            case_name: Optional case name (default: derived from filename)
            
        Returns:
            EvaluationResult
        """
        human_path = Path(human_report_path)
        agent_path = Path(agent_report_path)
        
        human_report = human_path.read_text(encoding="utf-8")
        agent_report = agent_path.read_text(encoding="utf-8")
        
        if case_name is None:
            case_name = agent_path.stem
        
        return self.evaluate(
            human_report=human_report,
            agent_report=agent_report,
            case_name=case_name,
            human_report_path=str(human_path),
            agent_report_path=str(agent_path),
        )
