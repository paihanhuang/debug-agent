"""Entity extraction from analysis text."""

from __future__ import annotations
import re
import uuid
from typing import Any

from ..graph.models import Entity, EntityType
from ..llm.client import BaseLLMClient, LLMClient


ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert at analyzing technical incident reports and root cause analyses. 
Your task is to extract entities from the given text that are relevant to understanding the causal chain of events.

Entity Types:
- Symptom: Observable problems or issues (e.g., "503 errors", "slow response times", "high CPU usage")
- Component: System parts, services, or infrastructure (e.g., "database server", "API gateway", "cache layer")
- Metric: Measured values or thresholds (e.g., "response time > 5s", "error rate 15%", "memory usage 90%")
- Hypothesis: Potential causes that were considered (e.g., "network congestion", "memory leak")
- RootCause: The identified underlying cause of the problem
- Action: Steps taken during investigation (e.g., "checked logs", "ran profiler", "restarted service")
- Observation: Factual findings during analysis (e.g., "logs showed timeouts", "metrics indicated spike")
- Conclusion: Final determinations or findings

For each entity, provide:
- A unique ID (e.g., "e1", "e2")
- The entity type
- A concise label
- A brief description
- The source text that mentions this entity
- A confidence score (0.0 to 1.0)

Return the entities as a JSON object with an "entities" array."""


ENTITY_EXTRACTION_PROMPT = """Analyze the following text and extract all relevant entities for understanding the causal analysis.

Text:
{text}

Return a JSON object with this structure:
{{
  "entities": [
    {{
      "id": "e1",
      "type": "Symptom|Component|Metric|Hypothesis|RootCause|Action|Observation|Conclusion",
      "label": "concise label",
      "description": "brief description",
      "source_text": "exact quote from text",
      "confidence": 0.95
    }}
  ]
}}"""


class EntityExtractor:
    """Extracts entities from analysis text using LLM."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        llm_provider: str = "openai",
    ):
        """Initialize entity extractor.
        
        Args:
            llm_client: Pre-configured LLM client. If None, creates one.
            llm_provider: LLM provider to use if creating client.
        """
        self._llm = llm_client or LLMClient.create(provider=llm_provider)
        self._entity_counter = 0
    
    def _generate_id(self) -> str:
        """Generate a unique entity ID."""
        self._entity_counter += 1
        return f"e{self._entity_counter}"
    
    def _parse_entity_type(self, type_str: str) -> EntityType:
        """Parse entity type string to enum."""
        type_map = {
            "symptom": EntityType.SYMPTOM,
            "component": EntityType.COMPONENT,
            "metric": EntityType.METRIC,
            "hypothesis": EntityType.HYPOTHESIS,
            "rootcause": EntityType.ROOT_CAUSE,
            "root_cause": EntityType.ROOT_CAUSE,
            "action": EntityType.ACTION,
            "observation": EntityType.OBSERVATION,
            "conclusion": EntityType.CONCLUSION,
        }
        return type_map.get(type_str.lower().replace(" ", ""), EntityType.OBSERVATION)
    
    def extract_entities(self, text: str) -> list[Entity]:
        """Extract entities from text using LLM.
        
        Args:
            text: Input text to analyze.
            
        Returns:
            List of extracted entities.
        """
        prompt = ENTITY_EXTRACTION_PROMPT.format(text=text)
        
        try:
            result = self._llm.complete_json(prompt, ENTITY_EXTRACTION_SYSTEM_PROMPT)
        except Exception as e:
            # Fallback to basic extraction if LLM fails
            return self._fallback_extraction(text)
        
        entities = []
        for item in result.get("entities", []):
            entity = Entity(
                id=item.get("id", self._generate_id()),
                entity_type=self._parse_entity_type(item.get("type", "Observation")),
                label=item.get("label", "Unknown"),
                description=item.get("description", ""),
                source_text=item.get("source_text", ""),
                confidence=float(item.get("confidence", 0.8)),
            )
            entities.append(entity)
        
        return entities
    
    def _fallback_extraction(self, text: str) -> list[Entity]:
        """Fallback entity extraction using pattern matching.
        
        Args:
            text: Input text.
            
        Returns:
            List of entities extracted via patterns.
        """
        entities = []
        
        # Pattern-based extraction for common entity types
        patterns = [
            # Symptoms
            (r"(?:error|failure|issue|problem|outage|incident)\s+(?:rate|with)?\s*[:\-]?\s*(\d+%?|\w+)",
             EntityType.SYMPTOM),
            # Metrics
            (r"(\d+(?:\.\d+)?%?\s*(?:ms|seconds?|s|minutes?|hours?|MB|GB|KB))",
             EntityType.METRIC),
            # Components
            (r"(?:server|service|database|api|cache|queue|load\s*balancer|gateway|cluster)(?:\s+\w+)?",
             EntityType.COMPONENT),
        ]
        
        for pattern, entity_type in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                label = match.group(0).strip()
                if len(label) > 3:  # Filter very short matches
                    entities.append(Entity(
                        id=self._generate_id(),
                        entity_type=entity_type,
                        label=label,
                        source_text=match.group(0),
                        confidence=0.6,
                    ))
        
        return entities
    
    def extract_from_sections(
        self,
        sections: dict[str, str],
    ) -> list[Entity]:
        """Extract entities from parsed document sections.
        
        Args:
            sections: Dictionary of section names to content.
            
        Returns:
            List of all extracted entities.
        """
        all_entities = []
        
        # Process each section
        for section_name, content in sections.items():
            if not content.strip():
                continue
            
            entities = self.extract_entities(content)
            
            # Add section context to entities
            for entity in entities:
                entity.attributes["source_section"] = section_name
            
            all_entities.extend(entities)
        
        # Deduplicate by label (keep highest confidence)
        seen_labels: dict[str, Entity] = {}
        for entity in all_entities:
            key = entity.label.lower()
            if key not in seen_labels or entity.confidence > seen_labels[key].confidence:
                seen_labels[key] = entity
        
        return list(seen_labels.values())
