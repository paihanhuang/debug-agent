"""Tests for text parser module."""

import pytest
from src.parser.text_parser import TextParser, ParsedDocument


class TestTextParser:
    """Test cases for TextParser."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.parser = TextParser()
    
    def test_preprocess_normalizes_whitespace(self):
        """Test that preprocess normalizes whitespace."""
        text = "Hello   world\r\n\r\nTest"
        result = self.parser.preprocess(text)
        assert "   " not in result
        assert "\r" not in result
    
    def test_preprocess_strips_lines(self):
        """Test that preprocess strips leading/trailing whitespace from lines."""
        text = "  Hello world  \n  Test line  "
        result = self.parser.preprocess(text)
        lines = result.split("\n")
        for line in lines:
            assert line == line.strip()
    
    def test_extract_sentences_basic(self):
        """Test basic sentence extraction."""
        text = "This is sentence one. This is sentence two. And sentence three."
        sentences = self.parser.extract_sentences(text)
        assert len(sentences) >= 2
    
    def test_segment_sections_finds_problem(self):
        """Test that section segmentation finds problem sections."""
        text = """# Problem Description
        
This is the problem.

# Investigation

This is what we found.
"""
        sections = self.parser.segment_sections(text)
        assert "problem" in sections or "main" in sections
    
    def test_segment_sections_finds_root_cause(self):
        """Test that section segmentation finds root cause sections."""
        text = """# Analysis

Some analysis here.

# Root Cause

The database was slow.
"""
        sections = self.parser.segment_sections(text)
        assert "root_cause" in sections
    
    def test_parse_returns_parsed_document(self):
        """Test that parse returns a ParsedDocument."""
        text = "This is a test document with some content."
        result = self.parser.parse(text)
        assert isinstance(result, ParsedDocument)
        assert result.raw_text == text
        assert len(result.sentences) > 0


class TestParsedDocument:
    """Test cases for ParsedDocument."""
    
    def test_parsed_document_default_values(self):
        """Test that ParsedDocument has correct defaults."""
        doc = ParsedDocument(raw_text="test")
        assert doc.raw_text == "test"
        assert doc.sections == {}
        assert doc.sentences == []
        assert doc.metadata == {}
