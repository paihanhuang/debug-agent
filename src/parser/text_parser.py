"""Text parser for processing input files."""

from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ParsedDocument:
    """A parsed document with extracted sections."""
    raw_text: str
    sections: dict[str, str] = field(default_factory=dict)
    sentences: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


class TextParser:
    """Parser for input text files (problem descriptions and analysis reports)."""
    
    # Common section headers in analysis reports
    SECTION_PATTERNS = [
        (r"(?i)^#+\s*(problem|issue|incident)\s*(description|summary)?", "problem"),
        (r"(?i)^#+\s*(symptoms?|observations?)", "symptoms"),
        (r"(?i)^#+\s*(investigation|analysis|diagnosis)", "investigation"),
        (r"(?i)^#+\s*(hypothesis|hypotheses|potential causes?)", "hypotheses"),
        (r"(?i)^#+\s*(root cause|conclusion|findings?)", "root_cause"),
        (r"(?i)^#+\s*(resolution|solution|fix|remediation)", "resolution"),
        (r"(?i)^#+\s*(timeline|chronology)", "timeline"),
        (r"(?i)^#+\s*(impact|affected)", "impact"),
        (r"(?i)^#+\s*(recommendations?|next steps?)", "recommendations"),
    ]
    
    def __init__(self):
        """Initialize the text parser."""
        self._compiled_patterns = [
            (re.compile(pattern), section_name)
            for pattern, section_name in self.SECTION_PATTERNS
        ]
    
    def load_file(self, file_path: str | Path) -> str:
        """Load text content from a file.
        
        Args:
            file_path: Path to the text file.
            
        Returns:
            The raw text content of the file.
            
        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file cannot be read as text.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try with latin-1 as fallback
            try:
                return path.read_text(encoding="latin-1")
            except Exception as e:
                raise ValueError(f"Cannot read file as text: {e}")
    
    def preprocess(self, text: str) -> str:
        """Preprocess text for analysis.
        
        Args:
            text: Raw text content.
            
        Returns:
            Cleaned and normalized text.
        """
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        
        # Remove excessive whitespace but preserve paragraph structure
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Strip leading/trailing whitespace from each line
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        
        return text.strip()
    
    def extract_sentences(self, text: str) -> list[str]:
        """Extract sentences from text.
        
        Args:
            text: Input text.
            
        Returns:
            List of sentences.
        """
        # Simple sentence splitting (can be enhanced with spaCy)
        # Handle common abbreviations
        text = re.sub(r"(?<=[.!?])\s+", "\n", text)
        sentences = [s.strip() for s in text.split("\n") if s.strip()]
        
        # Filter out very short fragments
        sentences = [s for s in sentences if len(s) > 10]
        
        return sentences
    
    def segment_sections(self, text: str) -> dict[str, str]:
        """Segment text into logical sections.
        
        Args:
            text: Input text content.
            
        Returns:
            Dictionary mapping section names to their content.
        """
        sections = {}
        current_section = "main"
        current_content = []
        
        lines = text.split("\n")
        
        for line in lines:
            # Check if line matches any section pattern
            matched_section = None
            for pattern, section_name in self._compiled_patterns:
                if pattern.match(line):
                    matched_section = section_name
                    break
            
            if matched_section:
                # Save current section
                if current_content:
                    content = "\n".join(current_content).strip()
                    if content:
                        sections[current_section] = content
                
                # Start new section
                current_section = matched_section
                current_content = []
            else:
                current_content.append(line)
        
        # Save last section
        if current_content:
            content = "\n".join(current_content).strip()
            if content:
                sections[current_section] = content
        
        return sections
    
    def parse(self, text: str) -> ParsedDocument:
        """Parse text into a structured document.
        
        Args:
            text: Raw text content.
            
        Returns:
            ParsedDocument with extracted sections and sentences.
        """
        preprocessed = self.preprocess(text)
        sections = self.segment_sections(preprocessed)
        sentences = self.extract_sentences(preprocessed)
        
        return ParsedDocument(
            raw_text=text,
            sections=sections,
            sentences=sentences,
        )
    
    def parse_file(self, file_path: str | Path) -> ParsedDocument:
        """Load and parse a file.
        
        Args:
            file_path: Path to the text file.
            
        Returns:
            ParsedDocument with extracted content.
        """
        text = self.load_file(file_path)
        doc = self.parse(text)
        doc.metadata["source_file"] = str(file_path)
        return doc
    
    def parse_problem_and_analysis(
        self,
        problem_file: str | Path,
        analysis_file: str | Path,
    ) -> tuple[ParsedDocument, ParsedDocument]:
        """Parse both problem description and analysis report.
        
        Args:
            problem_file: Path to the problem description file.
            analysis_file: Path to the expert analysis report.
            
        Returns:
            Tuple of (problem_doc, analysis_doc).
        """
        problem_doc = self.parse_file(problem_file)
        problem_doc.metadata["document_type"] = "problem_description"
        
        analysis_doc = self.parse_file(analysis_file)
        analysis_doc.metadata["document_type"] = "analysis_report"
        
        return problem_doc, analysis_doc
