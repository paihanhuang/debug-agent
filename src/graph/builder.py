"""Graph builder - orchestrates the full extraction pipeline."""

from __future__ import annotations
from pathlib import Path
from typing import Any

from ..parser.text_parser import TextParser, ParsedDocument
from ..extraction.entity_extractor import EntityExtractor
from ..extraction.relation_extractor import RelationExtractor
from ..llm.client import BaseLLMClient, LLMClient
from .models import CausalGraph, Entity, Relation


class GraphBuilder:
    """Orchestrates the full pipeline to build a causal knowledge graph."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        llm_provider: str = "openai",
    ):
        """Initialize the graph builder.
        
        Args:
            llm_client: Pre-configured LLM client. If None, creates one.
            llm_provider: LLM provider to use if creating client.
        """
        self._llm = llm_client or LLMClient.create(provider=llm_provider)
        self._parser = TextParser()
        self._entity_extractor = EntityExtractor(llm_client=self._llm)
        self._relation_extractor = RelationExtractor(llm_client=self._llm)
    
    def build_from_text(
        self,
        problem_text: str,
        analysis_text: str,
    ) -> CausalGraph:
        """Build a causal graph from raw text inputs.
        
        Args:
            problem_text: Problem description text.
            analysis_text: Expert analysis report text.
            
        Returns:
            A CausalGraph representing the causal analysis.
        """
        # Combine texts for entity extraction
        combined_text = f"""
PROBLEM DESCRIPTION:
{problem_text}

EXPERT ANALYSIS:
{analysis_text}
"""
        
        # Parse documents
        problem_doc = self._parser.parse(problem_text)
        analysis_doc = self._parser.parse(analysis_text)
        
        # Extract entities from both documents
        problem_entities = self._entity_extractor.extract_from_sections(
            {"problem": problem_doc.raw_text} if not problem_doc.sections else problem_doc.sections
        )
        analysis_entities = self._entity_extractor.extract_from_sections(
            analysis_doc.sections if analysis_doc.sections else {"analysis": analysis_doc.raw_text}
        )
        
        # Merge entities (deduplicate by label)
        entity_map: dict[str, Entity] = {}
        for entity in problem_entities + analysis_entities:
            key = entity.label.lower()
            if key not in entity_map or entity.confidence > entity_map[key].confidence:
                entity_map[key] = entity
        
        all_entities = list(entity_map.values())
        
        # Extract relations
        relations = self._relation_extractor.build_causal_chain(
            combined_text,
            all_entities,
        )
        
        # Build the graph
        graph = CausalGraph()
        for entity in all_entities:
            graph.add_entity(entity)
        for relation in relations:
            try:
                graph.add_relation(relation)
            except ValueError:
                # Skip invalid relations (missing entities)
                pass
        
        return graph
    
    def build_from_files(
        self,
        problem_file: str | Path,
        analysis_file: str | Path,
    ) -> CausalGraph:
        """Build a causal graph from input files.
        
        Args:
            problem_file: Path to problem description file.
            analysis_file: Path to expert analysis file.
            
        Returns:
            A CausalGraph representing the causal analysis.
        """
        problem_doc, analysis_doc = self._parser.parse_problem_and_analysis(
            problem_file, analysis_file
        )
        
        return self.build_from_text(
            problem_doc.raw_text,
            analysis_doc.raw_text,
        )
    
    def build_from_single_file(self, file_path: str | Path) -> CausalGraph:
        """Build a causal graph from a single combined file.
        
        The file should contain both problem description and analysis.
        
        Args:
            file_path: Path to the combined file.
            
        Returns:
            A CausalGraph representing the causal analysis.
        """
        doc = self._parser.parse_file(file_path)
        
        # Use empty problem if not distinguished
        problem_text = doc.sections.get("problem", "")
        analysis_text = doc.raw_text
        
        return self.build_from_text(problem_text, analysis_text)
