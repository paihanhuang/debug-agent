"""Data models for Hybrid Two-Stage Debug Agent."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectedAnomaly:
    """An anomaly detected in user metrics by Stage 1.
    
    Attributes:
        id: Unique identifier (e.g., "anomaly_1")
        type: Anomaly type from CKG patterns or "UNKNOWN"
        metric: The specific metric that's abnormal
        value: The actual value observed
        severity: high, medium, or low
        why_abnormal: Explanation of why this is abnormal
        indicated_causes: CKG root cause entity IDs that may explain this
    """
    id: str
    type: str  # VCORE_CEILING, VCORE_FLOOR, DDR_HIGH, MMDVFS_ABNORMAL, UNKNOWN
    metric: str
    value: str
    severity: str  # high, medium, low
    why_abnormal: str
    indicated_causes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "metric": self.metric,
            "value": self.value,
            "severity": self.severity,
            "why_abnormal": self.why_abnormal,
            "indicated_causes": self.indicated_causes,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DetectedAnomaly":
        return cls(
            id=data["id"],
            type=data["type"],
            metric=data["metric"],
            value=data["value"],
            severity=data["severity"],
            why_abnormal=data["why_abnormal"],
            indicated_causes=data.get("indicated_causes", []),
        )


@dataclass
class AnomalyDiagnosis:
    """Diagnosis for a single anomaly from Stage 2.
    
    Attributes:
        anomaly: The anomaly being diagnosed
        root_cause: Identified root cause
        causal_chain: Chain from root cause to symptom
        explanation: Detailed explanation
        suggested_fixes: List of recommended fixes
    """
    anomaly: DetectedAnomaly
    root_cause: str
    causal_chain: str
    explanation: str
    suggested_fixes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly": self.anomaly.to_dict(),
            "root_cause": self.root_cause,
            "causal_chain": self.causal_chain,
            "explanation": self.explanation,
            "suggested_fixes": self.suggested_fixes,
        }


@dataclass
class HybridDiagnosisResult:
    """Complete result from Hybrid Two-Stage Agent.
    
    Attributes:
        anomalies: All detected anomalies from Stage 1
        diagnoses: Per-anomaly diagnoses from Stage 2
        synthesized_report: Unified report from Stage 3
        has_dual_issue: Whether multiple independent issues were found
        llm_calls: Number of LLM API calls made
        total_tokens: Approximate token usage
    """
    anomalies: list[DetectedAnomaly]
    diagnoses: list[AnomalyDiagnosis]
    synthesized_report: str
    has_dual_issue: bool = False
    llm_calls: int = 0
    total_tokens: int = 0
    
    @property
    def root_causes(self) -> list[str]:
        """Get unique root causes from all diagnoses."""
        return list(set(d.root_cause for d in self.diagnoses))
    
    @property
    def anomaly_count(self) -> int:
        """Number of anomalies detected."""
        return len(self.anomalies)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "anomalies": [a.to_dict() for a in self.anomalies],
            "diagnoses": [d.to_dict() for d in self.diagnoses],
            "synthesized_report": self.synthesized_report,
            "has_dual_issue": self.has_dual_issue,
            "root_causes": self.root_causes,
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
        }


# Anomaly type constants
class AnomalyType:
    """Known anomaly types from CKG patterns."""
    VCORE_CEILING = "VCORE_CEILING"  # VCORE 725mV > 10%
    VCORE_FLOOR = "VCORE_FLOOR"      # VCORE floor > 575mV
    DDR_HIGH = "DDR_HIGH"            # DDR usage abnormally high
    MMDVFS_ABNORMAL = "MMDVFS_ABNORMAL"  # MMDVFS at unexpected OPP
    CPU_CEILING = "CPU_CEILING"      # CPU frequencies at ceiling
    UNKNOWN = "UNKNOWN"              # Detected but not in patterns


# Severity thresholds
class Severity:
    HIGH = "high"      # > 50% threshold exceeded
    MEDIUM = "medium"  # 10-50% threshold exceeded
    LOW = "low"        # < 10% threshold exceeded
