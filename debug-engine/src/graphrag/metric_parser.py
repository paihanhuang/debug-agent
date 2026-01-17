"""Metric parser for extracting power metrics from text input."""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedMetrics:
    """Extracted power metrics from user input."""
    vcore_percent: float | None = None
    vcore_mv: int | None = None
    ddr5460_percent: float | None = None
    ddr6370_percent: float | None = None
    ddr_total_percent: float | None = None
    mmdvfs_opp: str | None = None  # "OPP3", "OPP4", etc.
    mmdvfs_opp_percent: float | None = None
    cpu_big_mhz: int | None = None
    cpu_mid_mhz: int | None = None
    cpu_small_mhz: int | None = None
    sw_req_flags: set[str] = field(default_factory=set)
    raw_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    
    def to_query_string(self) -> str:
        """Convert to a search query string."""
        parts = []
        
        if self.vcore_percent is not None:
            parts.append(f"VCORE 725mV at {self.vcore_percent}%")
        if self.vcore_mv is not None:
            parts.append(f"VCORE {self.vcore_mv}mV")
        if self.ddr6370_percent is not None:
            parts.append(f"DDR6370 {self.ddr6370_percent}%")
        if self.ddr5460_percent is not None:
            parts.append(f"DDR5460 {self.ddr5460_percent}%")
        if self.ddr_total_percent is not None:
            parts.append(f"DDR total {self.ddr_total_percent}%")
        if self.mmdvfs_opp is not None:
            parts.append(f"MMDVFS {self.mmdvfs_opp}")
        if self.mmdvfs_opp_percent is not None:
            parts.append(f"MMDVFS usage {self.mmdvfs_opp_percent}%")
        if self.sw_req_flags:
            parts.append(f"DDR voting {', '.join(sorted(self.sw_req_flags))}")
        
        return ", ".join(parts) if parts else self.raw_text
    
    def has_metrics(self) -> bool:
        """Check if any metrics were extracted."""
        return any([
            self.vcore_percent is not None,
            self.vcore_mv is not None,
            self.ddr5460_percent is not None,
            self.ddr6370_percent is not None,
            self.mmdvfs_opp is not None,
            self.mmdvfs_opp_percent is not None,
            bool(self.sw_req_flags),
        ])


class MetricParser:
    """Parser for extracting power metrics from text."""
    
    # Regex patterns for metric extraction
    PATTERNS = {
        "vcore_percent": [
            r"VCORE\s*(?:725mV)?\s*(?:at|@|:|：)?\s*([\d.]+)\s*%",
            r"([\d.]+)\s*%\s*(?:使用率|usage).*VCORE",
        ],
        "vcore_mv": [
            r"VCORE\s*([\d]+)\s*mV",
        ],
        "ddr6370_percent": [
            r"DDR\s*6370\s*(?:at|@|:|：|佔)?\s*([\d.]+)\s*%",
            r"DDR6370\s*(?:at|@|:|：|佔)?\s*([\d.]+)\s*%",
        ],
        "ddr5460_percent": [
            r"DDR\s*5460\s*(?:at|@|:|：|佔)?\s*([\d.]+)\s*%",
            r"DDR5460\s*(?:at|@|:|：|佔)?\s*([\d.]+)\s*%",
        ],
        "ddr_total_percent": [
            r"DDR\s*(?:total|總|使用率)\s*(?:at|@|:|：)?\s*([\d.]+)\s*%",
        ],
        "mmdvfs_opp": [
            r"MMDVFS\s*(OPP\d+)",
            r"MMDVFS\s*(?:at|@|:|：)?\s*(OPP\d+)",
        ],
        "mmdvfs_opp_percent": [
            r"MMDVFS.*?([\d.]+)\s*%\s*usage",
            r"MMDVFS.*?([\d.]+)\s*%",
        ],
        "cpu_big_mhz": [
            r"大核\s*([\d]+)\s*MHz",
            r"big\s*core[s]?\s*([\d]+)\s*MHz",
        ],
        "cpu_mid_mhz": [
            r"中核\s*([\d]+)\s*MHz",
            r"mid\s*core[s]?\s*([\d]+)\s*MHz",
        ],
        "cpu_small_mhz": [
            r"小核\s*([\d]+)\s*MHz",
            r"small\s*core[s]?\s*([\d]+)\s*MHz",
        ],
    }
    
    def parse(self, text: str) -> ExtractedMetrics:
        """Parse text to extract power metrics.
        
        Args:
            text: Input text (can be Chinese or English)
            
        Returns:
            ExtractedMetrics with parsed values
        """
        metrics = ExtractedMetrics(raw_text=text)
        
        for field_name, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1)
                    
                    # Convert to appropriate type
                    if field_name == "mmdvfs_opp":
                        setattr(metrics, field_name, value.upper())
                    elif "mhz" in field_name:
                        setattr(metrics, field_name, int(value))
                    else:
                        setattr(metrics, field_name, float(value))
                    break

        # Extract DDR voting flags (SW_REQ2/SW_REQ3)
        sw_reqs = re.findall(r"SW_REQ\d", text, re.IGNORECASE)
        if sw_reqs:
            metrics.sw_req_flags = {req.upper() for req in sw_reqs}
        
        # Calculate DDR total if not provided
        if metrics.ddr_total_percent is None:
            if metrics.ddr5460_percent is not None and metrics.ddr6370_percent is not None:
                metrics.ddr_total_percent = metrics.ddr5460_percent + metrics.ddr6370_percent
        
        return metrics
    
    def parse_structured(self, data: dict[str, Any]) -> ExtractedMetrics:
        """Parse structured data (JSON/dict) to extract metrics.
        
        Args:
            data: Dictionary with metric keys
            
        Returns:
            ExtractedMetrics with parsed values
        """
        return ExtractedMetrics(
            vcore_percent=data.get("vcore_percent") or data.get("VCORE"),
            vcore_mv=data.get("vcore_mv"),
            ddr5460_percent=data.get("ddr5460_percent") or data.get("DDR5460"),
            ddr6370_percent=data.get("ddr6370_percent") or data.get("DDR6370"),
            ddr_total_percent=data.get("ddr_total_percent"),
            mmdvfs_opp=data.get("mmdvfs_opp") or data.get("MMDVFS"),
            mmdvfs_opp_percent=data.get("mmdvfs_opp_percent"),
            cpu_big_mhz=data.get("cpu_big_mhz"),
            cpu_mid_mhz=data.get("cpu_mid_mhz"),
            cpu_small_mhz=data.get("cpu_small_mhz"),
            sw_req_flags=set(data.get("sw_req_flags", [])),
            extra=data,
        )
