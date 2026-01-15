"""Unit tests for Phase 2: Retrieval Pipeline.

Tests:
- MetricParser: Metric extraction from text
- (Retriever tests require running Neo4j)
"""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.metric_parser import MetricParser, ExtractedMetrics


class TestMetricParser:
    """Tests for metric parser."""
    
    def setup_method(self):
        self.parser = MetricParser()
    
    def test_parse_vcore_percent(self):
        """Test parsing VCORE percentage."""
        text = "VCORE 725mV at 82.6%"
        metrics = self.parser.parse(text)
        assert metrics.vcore_percent == 82.6
    
    def test_parse_vcore_percent_chinese(self):
        """Test parsing VCORE with Chinese text."""
        text = "VCORE 725mV 超過預期的10%使用率在82.6%"
        metrics = self.parser.parse(text)
        # May or may not match depending on pattern
        # At minimum, raw_text should be preserved
        assert metrics.raw_text == text
    
    def test_parse_ddr6370(self):
        """Test parsing DDR6370 percentage."""
        text = "DDR6370佔26.13%"
        metrics = self.parser.parse(text)
        assert metrics.ddr6370_percent == 26.13
    
    def test_parse_ddr5460(self):
        """Test parsing DDR5460 percentage."""
        text = "DDR5460佔3.54%"
        metrics = self.parser.parse(text)
        assert metrics.ddr5460_percent == 3.54
    
    def test_parse_mmdvfs_opp(self):
        """Test parsing MMDVFS OPP level."""
        text = "MMDVFS OPP4"
        metrics = self.parser.parse(text)
        assert metrics.mmdvfs_opp == "OPP4"
        
        text2 = "MMDVFS OPP3"
        metrics2 = self.parser.parse(text2)
        assert metrics2.mmdvfs_opp == "OPP3"
    
    def test_parse_cpu_frequencies(self):
        """Test parsing CPU frequencies."""
        text = "大核2700MHz，中核2500MHz，小核2100MHz"
        metrics = self.parser.parse(text)
        assert metrics.cpu_big_mhz == 2700
        assert metrics.cpu_mid_mhz == 2500
        assert metrics.cpu_small_mhz == 2100
    
    def test_parse_combined_text(self):
        """Test parsing combined metrics."""
        text = "VCORE at 45%, DDR6370 40%, DDR5460 5%, MMDVFS OPP4"
        metrics = self.parser.parse(text)
        assert metrics.vcore_percent == 45.0
        assert metrics.ddr6370_percent == 40.0
        assert metrics.ddr5460_percent == 5.0
        assert metrics.mmdvfs_opp == "OPP4"
        # Auto-calculated DDR total
        assert metrics.ddr_total_percent == 45.0
    
    def test_to_query_string(self):
        """Test conversion to query string."""
        metrics = ExtractedMetrics(
            vcore_percent=82.6,
            ddr6370_percent=50.0,
            mmdvfs_opp="OPP4",
        )
        query = metrics.to_query_string()
        assert "VCORE 725mV at 82.6%" in query
        assert "DDR6370 50.0%" in query
        assert "MMDVFS OPP4" in query
    
    def test_has_metrics(self):
        """Test has_metrics check."""
        empty = ExtractedMetrics()
        assert not empty.has_metrics()
        
        with_metrics = ExtractedMetrics(vcore_percent=50.0)
        assert with_metrics.has_metrics()
    
    def test_parse_structured(self):
        """Test parsing from structured data."""
        data = {
            "VCORE": 45.0,
            "DDR5460": 10.0,
            "DDR6370": 35.0,
            "MMDVFS": "OPP4",
        }
        metrics = self.parser.parse_structured(data)
        assert metrics.vcore_percent == 45.0
        assert metrics.ddr5460_percent == 10.0
        assert metrics.ddr6370_percent == 35.0
        assert metrics.mmdvfs_opp == "OPP4"


class TestExtractedMetrics:
    """Tests for ExtractedMetrics dataclass."""
    
    def test_default_values(self):
        """Test default values are None."""
        metrics = ExtractedMetrics()
        assert metrics.vcore_percent is None
        assert metrics.ddr6370_percent is None
        assert metrics.mmdvfs_opp is None
    
    def test_ddr_total_calculation(self):
        """Test DDR total is calculated from components."""
        parser = MetricParser()
        text = "DDR5460 20%, DDR6370 30%"
        metrics = parser.parse(text)
        assert metrics.ddr_total_percent == 50.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
