"""Causal relation extraction from analysis text."""

from __future__ import annotations
from typing import Any

from ..graph.models import (
    Entity,
    Relation,
    RelationType,
    CausalEffect,
    TemporalOrder,
    CAUSAL_RELATION_TYPES,
)
from ..llm.client import BaseLLMClient, LLMClient


RELATION_EXTRACTION_SYSTEM_PROMPT = """You are an expert at identifying causal relationships in technical incident reports.
Your task is to identify how entities are causally related in the analysis, with a focus on TRUE CAUSAL relationships.

## Relation Types (ordered by causal strength):

### True Causal Relations:
- CAUSES: Direct causation (A directly causes B). Use for clear cause-effect chains.
- PREVENTS: A prevents B from happening (negative causation).
- ENABLES: A enables B to occur (necessary but not sufficient condition).

### Evidential Relations:
- INDICATES: Evidence relationship (symptom indicates potential cause)
- CONFIRMS: Validation (test/evidence confirms hypothesis)
- RULES_OUT: Elimination (evidence rules out a hypothesis)

### Analysis Flow Relations:
- LEADS_TO: Analysis progression (observation leads to hypothesis)
- DEPENDS_ON: Dependency relationship (A depends on B)

### Non-Causal Relations:
- CORRELATES_WITH: Co-occurrence WITHOUT direct causation
- ASSOCIATED_WITH: Statistical association only

## Causal Effect Properties:
For CAUSES/PREVENTS/ENABLES relations, you MUST specify:
- causal_strength: -1.0 (strongly inhibits) to 1.0 (strongly promotes)
- temporal_order: "immediate", "seconds", "minutes", "hours", "days", "unknown"
- mechanism: Brief description of HOW the causation works

IMPORTANT: Be careful to distinguish correlation from causation. If unsure, use CORRELATES_WITH.

Return relations as a JSON object with a "relations" array."""


RELATION_EXTRACTION_PROMPT = """Given the following entities and the original text, identify all relationships between the entities.
Focus on TRUE CAUSAL relationships when present.

Entities:
{entities_json}

Original Text:
{text}

Return a JSON object with this structure:
{{
  "relations": [
    {{
      "source": "entity_id (the cause)",
      "target": "entity_id (the effect)",
      "type": "CAUSES|PREVENTS|ENABLES|INDICATES|LEADS_TO|RULES_OUT|CONFIRMS|CORRELATES_WITH|ASSOCIATED_WITH|DEPENDS_ON",
      "evidence": "quote from text supporting this relation",
      "confidence": 0.9,
      "causal_effect": {{
        "strength": 0.8,
        "temporal_order": "immediate|seconds|minutes|hours|days|unknown",
        "mechanism": "brief description of how A causes B"
      }}
    }}
  ]
}}

Note: causal_effect is REQUIRED for CAUSES, PREVENTS, ENABLES relations.
For other relation types, causal_effect can be omitted.

Focus on:
1. Root cause → intermediate effects → symptoms chains
2. Evidence → hypothesis validation/elimination
3. Quantify how STRONG the causal effect is (0.0-1.0)"""


class RelationExtractor:
    """Extracts causal relationships between entities using LLM."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        llm_provider: str = "openai",
    ):
        """Initialize relation extractor.
        
        Args:
            llm_client: Pre-configured LLM client. If None, creates one.
            llm_provider: LLM provider to use if creating client.
        """
        self._llm = llm_client or LLMClient.create(provider=llm_provider)
    
    def _parse_relation_type(self, type_str: str) -> RelationType:
        """Parse relation type string to enum."""
        type_map = {
            "causes": RelationType.CAUSES,
            "prevents": RelationType.PREVENTS,
            "enables": RelationType.ENABLES,
            "indicates": RelationType.INDICATES,
            "leads_to": RelationType.LEADS_TO,
            "leadsto": RelationType.LEADS_TO,
            "rules_out": RelationType.RULES_OUT,
            "rulesout": RelationType.RULES_OUT,
            "confirms": RelationType.CONFIRMS,
            "correlates_with": RelationType.CORRELATES_WITH,
            "correlateswith": RelationType.CORRELATES_WITH,
            "associated_with": RelationType.ASSOCIATED_WITH,
            "associatedwith": RelationType.ASSOCIATED_WITH,
            "depends_on": RelationType.DEPENDS_ON,
            "dependson": RelationType.DEPENDS_ON,
        }
        return type_map.get(type_str.lower().replace(" ", "_"), RelationType.CAUSES)
    
    def _parse_temporal_order(self, temporal_str: str) -> TemporalOrder:
        """Parse temporal order string to enum."""
        temporal_map = {
            "immediate": TemporalOrder.IMMEDIATE,
            "seconds": TemporalOrder.SECONDS,
            "minutes": TemporalOrder.MINUTES,
            "hours": TemporalOrder.HOURS,
            "days": TemporalOrder.DAYS,
            "unknown": TemporalOrder.UNKNOWN,
        }
        return temporal_map.get(temporal_str.lower(), TemporalOrder.UNKNOWN)
    
    def _parse_causal_effect(self, effect_data: dict[str, Any] | None) -> CausalEffect | None:
        """Parse causal effect from LLM response."""
        if not effect_data:
            return None
        
        return CausalEffect(
            strength=float(effect_data.get("strength", 0.5)),
            is_direct=effect_data.get("is_direct", True),
            temporal_order=self._parse_temporal_order(
                effect_data.get("temporal_order", "unknown")
            ),
            mechanism=effect_data.get("mechanism", ""),
        )
    
    def extract_relations(
        self,
        text: str,
        entities: list[Entity],
    ) -> list[Relation]:
        """Extract causal relations between entities.
        
        Args:
            text: Original text content.
            entities: List of extracted entities.
            
        Returns:
            List of causal relations with effect quantification.
        """
        if len(entities) < 2:
            return []
        
        # Prepare entity information for prompt
        entities_info = [
            {
                "id": e.id,
                "type": e.entity_type.value,
                "label": e.label,
                "description": e.description,
            }
            for e in entities
        ]
        
        import json
        entities_json = json.dumps(entities_info, indent=2)
        
        prompt = RELATION_EXTRACTION_PROMPT.format(
            entities_json=entities_json,
            text=text,
        )
        
        try:
            result = self._llm.complete_json(prompt, RELATION_EXTRACTION_SYSTEM_PROMPT)
        except Exception:
            # Fallback to heuristic relation extraction
            return self._fallback_extraction(entities)
        
        # Build entity ID set for validation
        entity_ids = {e.id for e in entities}
        
        relations = []
        for item in result.get("relations", []):
            source_id = item.get("source", "")
            target_id = item.get("target", "")
            
            # Validate entity IDs exist
            if source_id not in entity_ids or target_id not in entity_ids:
                continue
            
            # Avoid self-loops
            if source_id == target_id:
                continue
            
            relation_type = self._parse_relation_type(item.get("type", "CAUSES"))
            
            # Parse causal effect for causal relations
            causal_effect = None
            if relation_type in CAUSAL_RELATION_TYPES:
                effect_data = item.get("causal_effect")
                if effect_data:
                    causal_effect = self._parse_causal_effect(effect_data)
                else:
                    # Default causal effect for causal relations
                    causal_effect = CausalEffect(
                        strength=float(item.get("confidence", 0.8)),
                        is_direct=True,
                        temporal_order=TemporalOrder.UNKNOWN,
                        mechanism="",
                    )
            
            relation = Relation(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                confidence=float(item.get("confidence", 0.8)),
                evidence=item.get("evidence", ""),
                causal_effect=causal_effect,
            )
            relations.append(relation)
        
        return relations
    
    def _fallback_extraction(self, entities: list[Entity]) -> list[Relation]:
        """Fallback relation extraction using heuristics.
        
        Args:
            entities: List of entities.
            
        Returns:
            List of relations based on entity types.
        """
        relations = []
        
        # Find root causes and symptoms
        root_causes = [e for e in entities if e.entity_type.value == "RootCause"]
        symptoms = [e for e in entities if e.entity_type.value == "Symptom"]
        
        # Root cause -> symptoms with default causal effect
        for rc in root_causes:
            for sym in symptoms:
                relations.append(Relation(
                    source_id=rc.id,
                    target_id=sym.id,
                    relation_type=RelationType.CAUSES,
                    confidence=0.5,
                    evidence="Inferred: root cause leads to symptom",
                    causal_effect=CausalEffect(
                        strength=0.5,
                        is_direct=False,  # May be mediated
                        temporal_order=TemporalOrder.UNKNOWN,
                        mechanism="Inferred causal relationship",
                    ),
                ))
        
        return relations
    
    def build_causal_chain(
        self,
        text: str,
        entities: list[Entity],
    ) -> list[Relation]:
        """Build a complete causal chain from the analysis.
        
        This method extracts relations and then attempts to build
        a coherent causal chain from root cause to symptoms.
        
        Args:
            text: Original text content.
            entities: List of extracted entities.
            
        Returns:
            List of relations forming the causal chain.
        """
        # First extract raw relations
        relations = self.extract_relations(text, entities)
        
        # Filter to high-confidence relations
        high_conf = [r for r in relations if r.confidence >= 0.7]
        
        # If we have enough high-confidence relations, use those
        if len(high_conf) >= 2:
            return high_conf
        
        return relations
    
    def get_causal_subgraph(
        self,
        relations: list[Relation],
    ) -> list[Relation]:
        """Extract only the true causal relations.
        
        Args:
            relations: All extracted relations.
            
        Returns:
            Only relations that are truly causal (CAUSES, PREVENTS, ENABLES).
        """
        return [r for r in relations if r.is_causal]
