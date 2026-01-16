"""Closed-loop refinement system for report quality optimization.

Uses GPT-4o Debug Agent with Claude-3.5-Sonnet Judge for
diverse evaluation and iterative improvement.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
import json

if TYPE_CHECKING:
    from .agent import DebugAgent


@dataclass
class RefinementResult:
    """Result of refinement loop."""
    final_diagnosis: Any  # DiagnosisResult
    iterations: int
    final_score: float
    final_grade: str
    improvement_history: list[dict] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "iterations": self.iterations,
            "final_score": self.final_score,
            "final_grade": self.final_grade,
            "improvement_history": self.improvement_history,
            "timestamp": self.timestamp,
            "diagnosis": self.final_diagnosis.to_dict() if self.final_diagnosis else None,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class RefinementLoop:
    """Judge-Guided Refinement Loop.
    
    Uses different LLMs for diverse evaluation:
    - Agent: GPT-4o (generates reports)
    - Judge: Claude-3.5-Sonnet (evaluates quality)
    
    This avoids self-confirmation bias where the same LLM
    grades its own work.
    """
    
    def __init__(
        self,
        agent: "DebugAgent",
        judge: Any,  # LLMReportJudge
        max_iterations: int = 3,
        score_threshold: float = 8.0,
        verbose: bool = True,
    ):
        """Initialize the refinement loop.
        
        Args:
            agent: Debug Agent (GPT-4o)
            judge: Report Quality Judge (Claude-3.5-Sonnet)
            max_iterations: Maximum refinement iterations
            score_threshold: Score threshold to stop refinement (1-10 scale)
            verbose: Print progress to console
        """
        self._agent = agent
        self._judge = judge
        self._max_iterations = max_iterations
        self._threshold = score_threshold
        self._verbose = verbose
        self._last_feedback = ""
    
    def diagnose_with_refinement(
        self,
        input_text: str,
        ground_truth: str | None = None,
    ) -> RefinementResult:
        """Run diagnosis with iterative refinement.
        
        Args:
            input_text: User observation/metrics
            ground_truth: Optional human expert report for comparison
            
        Returns:
            RefinementResult with final diagnosis and improvement history
        """
        history = []
        current_result = None
        
        if self._verbose:
            print(f"  Agent: {self._agent._llm_model}")
            print(f"  Judge: {self._judge._model} ({self._judge._provider.value})")
            print(f"  Threshold: {self._threshold}/10")
            print()
        
        for iteration in range(self._max_iterations):
            # Step 1: Generate or refine diagnosis
            if iteration == 0:
                if self._verbose:
                    print(f"  [Iteration {iteration + 1}] Generating initial diagnosis...")
                current_result = self._agent.diagnose(input_text)
            else:
                if self._verbose:
                    print(f"  [Iteration {iteration + 1}] Refining based on feedback...")
                current_result = self._agent.refine(
                    previous_result=current_result,
                    feedback=self._last_feedback,
                    original_input=input_text,
                )
            
            # Step 2: Evaluate with Judge
            report_md = self._format_report(current_result)
            reference = ground_truth or self._create_reference(input_text)
            
            if self._verbose:
                print(f"  [Iteration {iteration + 1}] Evaluating with Claude Judge...")
            
            evaluation = self._judge.evaluate(
                human_report=reference,
                agent_report=report_md,
                case_name=f"iteration_{iteration + 1}",
            )
            
            # Record history
            history_entry = {
                "iteration": iteration + 1,
                "score": evaluation.composite_score,
                "grade": evaluation.grade(),
                "weak_dimensions": [
                    {"name": d.name, "score": d.score}
                    for d in evaluation.dimensions if d.score < 8
                ],
                "summary": evaluation.summary,
            }
            history.append(history_entry)
            
            if self._verbose:
                print(f"  [Iteration {iteration + 1}] Score: {evaluation.composite_score}/10 ({evaluation.grade()})")
                if history_entry["weak_dimensions"]:
                    weak_names = [f"{d['name']}:{d['score']}" for d in history_entry["weak_dimensions"]]
                    print(f"  [Iteration {iteration + 1}] Weak: {', '.join(weak_names)}")
            
            # Step 3: Check if good enough
            if evaluation.composite_score >= self._threshold:
                if self._verbose:
                    print(f"\n  ✓ Threshold {self._threshold}/10 met! Stopping refinement.")
                break
            
            # Step 4: Build feedback for next iteration
            if iteration < self._max_iterations - 1:
                self._last_feedback = self._build_feedback(evaluation)
                if self._verbose:
                    print(f"  [Iteration {iteration + 1}] Preparing feedback for next iteration...")
        else:
            if self._verbose:
                print(f"\n  ⚠ Max iterations ({self._max_iterations}) reached.")
        
        return RefinementResult(
            final_diagnosis=current_result,
            iterations=len(history),
            final_score=history[-1]["score"] if history else 0,
            final_grade=history[-1]["grade"] if history else "F",
            improvement_history=history,
        )
    
    def _format_report(self, result: Any) -> str:
        """Format diagnosis as markdown for Judge."""
        return f"""## Root Cause
{result.root_cause}

## Causal Chain
{result.causal_chain}

## Diagnosis
{result.diagnosis}

## Historical Fixes
{chr(10).join('- ' + fix for fix in result.historical_fixes) if result.historical_fixes else 'None listed'}
"""
    
    def _create_reference(self, input_text: str) -> str:
        """Create reference from input when no ground truth available.
        
        This allows self-evaluation against the input metrics,
        which is useful for checking metric precision.
        """
        return f"""Expected analysis should:
- Use metrics EXACTLY as stated in the user input
- Identify root causes based on the data patterns
- Provide logical causal chain from root cause to symptom
- Reference relevant historical fixes

## User Input Metrics (Must Match Exactly)
{input_text}
"""
    
    def _build_feedback(self, evaluation: Any) -> str:
        """Convert Judge evaluation to actionable feedback."""
        weak_dims = [d for d in evaluation.dimensions if d.score < 8]
        
        if not weak_dims:
            return "Minor improvements needed. Please review your analysis."
        
        lines = ["Please improve the following aspects of your analysis:", ""]
        
        for dim in weak_dims:
            lines.append(f"**{dim.name}** (Current Score: {dim.score}/10)")
            lines.append(f"  Issue: {dim.explanation}")
            if dim.missing_elements:
                lines.append(f"  Missing: {', '.join(dim.missing_elements)}")
            if dim.matched_elements:
                lines.append(f"  Good: {', '.join(dim.matched_elements[:3])}")
            lines.append("")
        
        lines.append("IMPORTANT: Use EXACT metrics from the original user input.")
        
        return "\n".join(lines)
