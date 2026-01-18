from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StopCriteria:
    """Stop when accuracy >= threshold AND overall > threshold."""

    min_accuracy: float = 9.0
    min_overall: float = 8.0  # strictly greater than this


@dataclass(frozen=True)
class CaseSpec:
    case_id: str  # "case1", "case2", "case3"
    case_num: int  # 1,2,3
    human_report_path: Path


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    max_iters: int
    dry_run: bool
    output_root: Path
    base_ckg_path: Path
    stop: StopCriteria
    cases: list[CaseSpec]
    per_case: bool = False
    max_iters_per_case: int | None = None
    start_from_scratch: bool = False
    judge_provider: str = "openai"


@dataclass(frozen=True)
class IterationPaths:
    iter_num: int
    iter_dir: Path
    ckg_dir: Path
    agent_dir: Path
    judge_dir: Path
    feedback_dir: Path

    def iter_tag(self) -> str:
        return f"iter_{self.iter_num:04d}"


@dataclass
class Feedback:
    run_id: str
    iter_num: int
    average_score: float
    accuracy_score: float
    per_case: dict[str, dict[str, Any]]
    stop_reached: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "iter_num": self.iter_num,
            "average_score": self.average_score,
            "accuracy_score": self.accuracy_score,
            "stop_reached": self.stop_reached,
            "per_case": self.per_case,
        }

