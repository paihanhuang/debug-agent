"""Anomaly Detector - Stage 1 of Hybrid Two-Stage Agent.

Detects anomalies in user metrics using LLM guided by CKG patterns.
"""

from __future__ import annotations
import json
import os

from openai import OpenAI

from .models import DetectedAnomaly, AnomalyType
from .metric_parser import ExtractedMetrics
from .neo4j_store import Neo4jStore, EntityNode


ANOMALY_DETECTION_PROMPT = """You are a power debugging anomaly detector for mobile devices.

## User Observation:
{user_input}

## Extracted Metrics:
{metrics}

## Known Anomaly Patterns (from CKG):
{patterns}

## Detection Rules:
1. VCORE 725mV > 10%: This is a VCORE_CEILING anomaly (indicates CM/PowerHal issue)
2. VCORE floor > 575mV: This is a VCORE_FLOOR anomaly (indicates MMDVFS OPP3 issue)
3. DDR total > 30%: This may be a DDR_HIGH anomaly
4. MMDVFS at OPP3 with high usage: This is MMDVFS_ABNORMAL
5. CPU at ceiling frequencies: This may be CPU_CEILING
6. Any other unusual value: Mark as UNKNOWN

## Severity Guidelines:
- high: Metric exceeds threshold by >50% (e.g., VCORE 725mV at 80% when threshold is 10%)
- medium: Metric exceeds threshold by 10-50%
- low: Metric slightly exceeds threshold

## Task
Identify ALL anomalies present in the user's metrics. Include:
1. Known patterns that match
2. Any unusual values even if not in patterns
3. Both VCORE floor AND ceiling issues if present (DUAL ISSUE)

IMPORTANT: If BOTH VCORE floor issue AND VCORE 725mV issue exist, you MUST detect BOTH as separate anomalies.

Return JSON only:
{{
  "anomalies": [
    {{
      "id": "anomaly_1",
      "type": "VCORE_CEILING|VCORE_FLOOR|DDR_HIGH|MMDVFS_ABNORMAL|CPU_CEILING|UNKNOWN",
      "metric": "exact metric name from input",
      "value": "exact value from input",
      "severity": "high|medium|low",
      "why_abnormal": "brief explanation",
      "indicated_causes": ["rc_cm", "rc_mmdvfs", etc.]
    }}
  ],
  "has_dual_issue": true|false,
  "summary": "brief summary of all detected anomalies"
}}
"""


class AnomalyDetector:
    """LLM-based anomaly detection guided by CKG patterns.
    
    Stage 1 of the Hybrid Two-Stage Agent.
    Uses LLM to detect anomalies, guided by AnomalyPattern entities in CKG.
    """
    
    def __init__(
        self,
        llm_client: OpenAI | None = None,
        neo4j_store: Neo4jStore | None = None,
        model: str = "gpt-4o",
    ):
        """Initialize the anomaly detector.
        
        Args:
            llm_client: OpenAI client (default: create from env)
            neo4j_store: Neo4j store for CKG patterns
            model: LLM model to use
        """
        self._llm = llm_client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._neo4j = neo4j_store
        self._model = model
    
    def detect(
        self,
        user_input: str,
        metrics: ExtractedMetrics | None = None,
    ) -> list[DetectedAnomaly]:
        """Detect anomalies in user input using LLM + CKG patterns.
        
        Args:
            user_input: Raw user observation text
            metrics: Pre-extracted metrics (optional)
            
        Returns:
            List of detected anomalies
        """
        # Get anomaly patterns from CKG if available
        patterns = self._get_ckg_patterns()
        
        # Format metrics
        metrics_str = metrics.to_query_string() if metrics else "Not extracted"
        
        # Build prompt
        prompt = ANOMALY_DETECTION_PROMPT.format(
            user_input=user_input,
            metrics=metrics_str,
            patterns=self._format_patterns(patterns),
        )
        
        # Call LLM
        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        
        # Parse response
        return self._parse_response(response.choices[0].message.content)
    
    def _get_ckg_patterns(self) -> list[EntityNode]:
        """Get AnomalyPattern entities from CKG."""
        if self._neo4j is None:
            return []
        
        try:
            return self._neo4j.get_entities_by_type("AnomalyPattern")
        except Exception:
            return []
    
    def _format_patterns(self, patterns: list[EntityNode]) -> str:
        """Format CKG patterns for prompt."""
        if not patterns:
            return """Default patterns:
- VCORE_CEILING: VCORE 725mV usage > 10% → indicates CM/PowerHal
- VCORE_FLOOR: VCORE floor > 575mV → indicates MMDVFS OPP3
- DDR_HIGH: Total DDR usage > 30%
- MMDVFS_ABNORMAL: MMDVFS at OPP3 with high usage
- CPU_CEILING: CPU cores at maximum frequency"""
        
        lines = []
        for p in patterns:
            lines.append(f"- {p.label}: {p.description}")
        return "\n".join(lines)
    
    def _parse_response(self, response_text: str) -> list[DetectedAnomaly]:
        """Parse LLM JSON response into DetectedAnomaly objects."""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Fallback: return empty if parsing fails
            return []
        
        anomalies = []
        for item in data.get("anomalies", []):
            try:
                anomaly = DetectedAnomaly(
                    id=item.get("id", f"anomaly_{len(anomalies) + 1}"),
                    type=item.get("type", AnomalyType.UNKNOWN),
                    metric=item.get("metric", "unknown"),
                    value=item.get("value", "unknown"),
                    severity=item.get("severity", "medium"),
                    why_abnormal=item.get("why_abnormal", ""),
                    indicated_causes=item.get("indicated_causes", []),
                )
                anomalies.append(anomaly)
            except Exception:
                continue
        
        return anomalies
    
    def detect_with_details(
        self,
        user_input: str,
        metrics: ExtractedMetrics | None = None,
    ) -> tuple[list[DetectedAnomaly], bool, str]:
        """Detect anomalies and return additional metadata.
        
        Returns:
            Tuple of (anomalies, has_dual_issue, summary)
        """
        patterns = self._get_ckg_patterns()
        metrics_str = metrics.to_query_string() if metrics else "Not extracted"
        
        prompt = ANOMALY_DETECTION_PROMPT.format(
            user_input=user_input,
            metrics=metrics_str,
            patterns=self._format_patterns(patterns),
        )
        
        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        
        try:
            data = json.loads(response.choices[0].message.content)
            anomalies = self._parse_response(response.choices[0].message.content)
            has_dual_issue = data.get("has_dual_issue", False)
            summary = data.get("summary", "")
            return anomalies, has_dual_issue, summary
        except Exception:
            return [], False, ""
