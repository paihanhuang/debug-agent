"""Smart anomaly detector with deterministic rules + LLM fallback."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .metric_parser import ExtractedMetrics
from .models import DetectedAnomaly, AnomalyType, Severity
from .pattern_store import PatternStore, Pattern, ExclusionCondition
from .anomaly_detector import AnomalyDetector


@dataclass
class Ambiguity:
    """Ambiguity signals that require LLM refinement."""
    reasons: list[str]

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.reasons)


class SmartAnomalyDetector:
    """Deterministic anomaly detection with LLM fallback for ambiguity."""

    def __init__(
        self,
        pattern_store: PatternStore | None = None,
        llm_detector: AnomalyDetector | None = None,
    ):
        self._store = pattern_store or PatternStore()
        self._store.ensure_defaults()
        self._llm_detector = llm_detector

    def detect_with_details(
        self,
        user_input: str,
        metrics: ExtractedMetrics | None = None,
    ) -> tuple[list[DetectedAnomaly], bool, str]:
        metrics = metrics or ExtractedMetrics(raw_text=user_input)
        canonical = self._to_canonical(metrics)
        patterns = self._store.list_patterns()

        candidates: list[DetectedAnomaly] = []
        ambiguity = Ambiguity(reasons=[])

        for pattern in patterns:
            metric_value = canonical.get(pattern.metric_key)
            if metric_value is None:
                continue

            if self._match_pattern(metric_value, pattern):
                severity = self._severity(metric_value, pattern)
                candidates.append(
                    DetectedAnomaly(
                        id=f"anomaly_{len(candidates) + 1}",
                        type=pattern.anomaly_type,
                        metric=pattern.metric_key,
                        value=str(metric_value),
                        severity=severity,
                        why_abnormal=f"{pattern.name} exceeds threshold",
                        indicated_causes=pattern.indicated_causes,
                    )
                )

        filtered, ambiguity = self._apply_exclusions(candidates, canonical, ambiguity)

        # If nothing matched but metrics exist, treat as ambiguous (unknown pattern)
        if not filtered and metrics.has_metrics():
            ambiguity.reasons.append("no_pattern_match")

        if ambiguity.is_ambiguous and self._llm_detector:
            return self._llm_detector.detect_with_details(user_input, metrics)

        has_dual_issue = len(filtered) > 1
        summary = self._summary(filtered, ambiguity)
        return filtered, has_dual_issue, summary

    def detect(
        self,
        user_input: str,
        metrics: ExtractedMetrics | None = None,
    ) -> list[DetectedAnomaly]:
        anomalies, _, _ = self.detect_with_details(user_input, metrics)
        return anomalies

    def _to_canonical(self, metrics: ExtractedMetrics) -> dict[str, Any]:
        text = metrics.raw_text or ""
        canonical: dict[str, Any] = {}

        if metrics.vcore_percent is not None:
            canonical["vcore_725mv_pct"] = metrics.vcore_percent

        # Treat VCORE floor only if explicitly mentioned as floor
        if metrics.vcore_mv is not None and self._mentions_floor(text):
            canonical["vcore_floor_mv"] = metrics.vcore_mv

        if metrics.ddr_total_percent is not None:
            canonical["ddr_total_pct"] = metrics.ddr_total_percent

        if metrics.mmdvfs_opp is not None:
            canonical["mmdvfs_opp"] = metrics.mmdvfs_opp

        if metrics.mmdvfs_opp_percent is not None and metrics.mmdvfs_opp == "OPP3":
            canonical["mmdvfs_opp3_pct"] = metrics.mmdvfs_opp_percent

        if metrics.sw_req_flags:
            canonical["sw_req_flags"] = metrics.sw_req_flags

        return canonical

    def _mentions_floor(self, text: str) -> bool:
        return "floor" in text.lower() or "地板" in text

    def _match_pattern(self, value: float, pattern: Pattern) -> bool:
        if pattern.operator == "gt":
            return value > (pattern.threshold or 0)
        if pattern.operator == "lt":
            return value < (pattern.threshold or 0)
        if pattern.operator == "eq":
            return value == (pattern.threshold or 0)
        if pattern.operator == "between":
            if pattern.threshold is None or pattern.threshold_hi is None:
                return False
            return pattern.threshold <= value <= pattern.threshold_hi
        return False

    def _severity(self, value: float, pattern: Pattern) -> str:
        thresholds = pattern.severity_map
        if value >= thresholds.get("high", float("inf")):
            return Severity.HIGH
        if value >= thresholds.get("medium", float("inf")):
            return Severity.MEDIUM
        return Severity.LOW

    def _apply_exclusions(
        self,
        anomalies: list[DetectedAnomaly],
        metrics: dict[str, Any],
        ambiguity: Ambiguity,
    ) -> tuple[list[DetectedAnomaly], Ambiguity]:
        filtered: list[DetectedAnomaly] = []

        for anomaly in anomalies:
            exclusions = self._store.list_exclusions(self._pattern_id_for(anomaly))
            if not exclusions:
                filtered.append(anomaly)
                continue

            if self._should_exclude(exclusions, metrics, ambiguity):
                continue

            filtered.append(anomaly)

        return filtered, ambiguity

    def _pattern_id_for(self, anomaly: DetectedAnomaly) -> str:
        mapping = {
            AnomalyType.VCORE_CEILING: "pattern_vcore_ceiling",
            AnomalyType.VCORE_FLOOR: "pattern_vcore_floor",
            AnomalyType.DDR_HIGH: "pattern_ddr_high",
            AnomalyType.MMDVFS_ABNORMAL: "pattern_mmdvfs_opp3",
        }
        return mapping.get(anomaly.type, "")

    def _should_exclude(
        self,
        exclusions: list[ExclusionCondition],
        metrics: dict[str, Any],
        ambiguity: Ambiguity,
    ) -> bool:
        for ex in exclusions:
            if ex.metric_key not in metrics:
                ambiguity.reasons.append(f"missing_metric:{ex.metric_key}")
                return False

        return all(self._match_exclusion(ex, metrics) for ex in exclusions)

    def _match_exclusion(self, exclusion: ExclusionCondition, metrics: dict[str, Any]) -> bool:
        value = metrics.get(exclusion.metric_key)
        if exclusion.operator == "eq":
            return str(value) == str(exclusion.value)
        if exclusion.operator == "lt":
            return float(value) < float(exclusion.value)
        if exclusion.operator == "gt":
            return float(value) > float(exclusion.value)
        if exclusion.operator == "in":
            return str(value) in exclusion.value.split(",")
        return False

    def _summary(self, anomalies: list[DetectedAnomaly], ambiguity: Ambiguity) -> str:
        if not anomalies and ambiguity.is_ambiguous:
            return "No deterministic match; ambiguous metrics require refinement."
        if not anomalies:
            return "No anomalies detected in the provided metrics."
        types = ", ".join(a.type for a in anomalies)
        return f"Detected anomalies: {types}"
