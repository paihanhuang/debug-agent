"""Core data models for the causal knowledge graph."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import json
import networkx as nx


class EntityType(str, Enum):
    """Types of entities in the causal graph."""
    SYMPTOM = "Symptom"
    COMPONENT = "Component"
    METRIC = "Metric"
    HYPOTHESIS = "Hypothesis"
    ROOT_CAUSE = "RootCause"
    ACTION = "Action"
    OBSERVATION = "Observation"
    CONCLUSION = "Conclusion"


class RelationType(str, Enum):
    """Types of causal relationships."""
    # True causal relations
    CAUSES = "CAUSES"              # Direct causation: A causes B
    PREVENTS = "PREVENTS"          # A prevents B (negative causation)
    ENABLES = "ENABLES"            # A enables B to happen
    
    # Evidential relations
    INDICATES = "INDICATES"        # A indicates B (symptom → hypothesis)
    CONFIRMS = "CONFIRMS"          # A confirms B
    RULES_OUT = "RULES_OUT"        # A rules out B
    
    # Analysis flow relations
    LEADS_TO = "LEADS_TO"          # A leads to B (analysis progression)
    DEPENDS_ON = "DEPENDS_ON"      # A depends on B
    
    # Non-causal relations (correlational)
    CORRELATES_WITH = "CORRELATES_WITH"  # Correlation, not causation
    ASSOCIATED_WITH = "ASSOCIATED_WITH"  # Statistical association


# Relations that are truly causal (vs correlational/evidential)
CAUSAL_RELATION_TYPES = {
    RelationType.CAUSES,
    RelationType.PREVENTS,
    RelationType.ENABLES,
}


class TemporalOrder(str, Enum):
    """Temporal relationship between cause and effect."""
    IMMEDIATE = "immediate"      # Effect happens immediately
    SECONDS = "seconds"          # Within seconds
    MINUTES = "minutes"          # Within minutes
    HOURS = "hours"              # Within hours
    DAYS = "days"                # Within days
    UNKNOWN = "unknown"          # Temporal order not specified


@dataclass
class Entity:
    """Represents an entity/concept in the causal graph."""
    id: str
    entity_type: EntityType
    label: str
    description: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_text: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert entity to dictionary."""
        return {
            "id": self.id,
            "type": self.entity_type.value,
            "label": self.label,
            "description": self.description,
            "attributes": self.attributes,
            "confidence": self.confidence,
            "source_text": self.source_text,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entity:
        """Create entity from dictionary."""
        return cls(
            id=data["id"],
            entity_type=EntityType(data["type"]),
            label=data["label"],
            description=data.get("description", ""),
            attributes=data.get("attributes", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text", ""),
        )


@dataclass
class CausalEffect:
    """Quantifies the causal effect between two entities."""
    strength: float = 0.0       # -1.0 (inhibits) to 1.0 (promotes)
    is_direct: bool = True      # Direct vs mediated causation
    temporal_order: TemporalOrder = TemporalOrder.UNKNOWN
    mechanism: str = ""         # Description of causal mechanism
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "strength": self.strength,
            "is_direct": self.is_direct,
            "temporal_order": self.temporal_order.value,
            "mechanism": self.mechanism,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CausalEffect":
        return cls(
            strength=data.get("strength", 0.0),
            is_direct=data.get("is_direct", True),
            temporal_order=TemporalOrder(data.get("temporal_order", "unknown")),
            mechanism=data.get("mechanism", ""),
        )


@dataclass
class Relation:
    """Represents a relationship between entities in the causal graph."""
    source_id: str
    target_id: str
    relation_type: RelationType
    confidence: float = 1.0
    evidence: str = ""
    causal_effect: CausalEffect | None = None  # Only for causal relations
    attributes: dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_causal(self) -> bool:
        """Returns True if this is a true causal relation (not correlational)."""
        return self.relation_type in CAUSAL_RELATION_TYPES
    
    def to_dict(self) -> dict[str, Any]:
        """Convert relation to dictionary."""
        result = {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.relation_type.value,
            "is_causal": self.is_causal,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "attributes": self.attributes,
        }
        if self.causal_effect:
            result["causal_effect"] = self.causal_effect.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relation":
        """Create relation from dictionary."""
        causal_effect = None
        if "causal_effect" in data:
            causal_effect = CausalEffect.from_dict(data["causal_effect"])
        
        return cls(
            source_id=data["source"],
            target_id=data["target"],
            relation_type=RelationType(data["type"]),
            confidence=data.get("confidence", 1.0),
            evidence=data.get("evidence", ""),
            causal_effect=causal_effect,
            attributes=data.get("attributes", {}),
        )


class CausalGraphValidationError(Exception):
    """Raised when causal graph validation fails."""
    pass


class CausalGraph:
    """A causal knowledge graph built from analysis reports.
    
    A proper Causal Knowledge Graph (CKG) must be a Directed Acyclic Graph (DAG)
    to support valid causal inference. This class enforces DAG constraints and
    distinguishes between causal and correlational relationships.
    """
    
    def __init__(self, strict_dag: bool = True):
        """Initialize an empty causal graph.
        
        Args:
            strict_dag: If True, raises error when adding relations that create cycles.
        """
        self._graph = nx.DiGraph()
        self._entities: dict[str, Entity] = {}
        self._relations: list[Relation] = []
        self._strict_dag = strict_dag
    
    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        self._entities[entity.id] = entity
        self._graph.add_node(
            entity.id,
            entity_type=entity.entity_type.value,
            label=entity.label,
            description=entity.description,
            confidence=entity.confidence,
        )
    
    def add_relation(self, relation: Relation, validate_dag: bool = True) -> None:
        """Add a relation to the graph.
        
        Args:
            relation: The relation to add.
            validate_dag: If True and strict_dag is True, validates that adding
                         this relation won't create a cycle.
        
        Raises:
            ValueError: If source or target entity doesn't exist.
            CausalGraphValidationError: If adding relation would create a cycle.
        """
        if relation.source_id not in self._entities:
            raise ValueError(f"Source entity '{relation.source_id}' not found")
        if relation.target_id not in self._entities:
            raise ValueError(f"Target entity '{relation.target_id}' not found")
        
        # Check for cycles before adding (for causal relations)
        if self._strict_dag and validate_dag and relation.is_causal:
            if self._would_create_cycle(relation.source_id, relation.target_id):
                raise CausalGraphValidationError(
                    f"Adding relation {relation.source_id} -> {relation.target_id} "
                    f"would create a cycle. Causal graphs must be DAGs."
                )
        
        self._relations.append(relation)
        edge_attrs = {
            "relation_type": relation.relation_type.value,
            "is_causal": relation.is_causal,
            "confidence": relation.confidence,
            "evidence": relation.evidence,
        }
        if relation.causal_effect:
            edge_attrs["causal_strength"] = relation.causal_effect.strength
            edge_attrs["temporal_order"] = relation.causal_effect.temporal_order.value
        
        self._graph.add_edge(relation.source_id, relation.target_id, **edge_attrs)
    
    def _would_create_cycle(self, source: str, target: str) -> bool:
        """Check if adding an edge would create a cycle."""
        # A cycle would be created if there's already a path from target to source
        return nx.has_path(self._graph, target, source)
    
    def is_valid_dag(self) -> bool:
        """Check if the graph is a valid DAG (no cycles)."""
        return nx.is_directed_acyclic_graph(self._graph)
    
    def validate(self) -> list[str]:
        """Validate the causal graph and return list of issues."""
        issues = []
        
        # Check DAG property
        if not self.is_valid_dag():
            cycles = list(nx.simple_cycles(self._graph))
            issues.append(f"Graph contains {len(cycles)} cycle(s): {cycles[:3]}...")
        
        # Check for isolated nodes (entities with no relations)
        isolated = list(nx.isolates(self._graph))
        if isolated:
            issues.append(f"Found {len(isolated)} isolated entities: {isolated[:5]}...")
        
        # Check for causal relations without causal effect
        for rel in self._relations:
            if rel.is_causal and rel.causal_effect is None:
                issues.append(f"Causal relation {rel.source_id}->{rel.target_id} missing causal_effect")
        
        return issues
    
    def get_causal_relations_only(self) -> list[Relation]:
        """Get only the true causal relations (excluding correlational)."""
        return [r for r in self._relations if r.is_causal]
    
    def get_entity(self, entity_id: str) -> Entity | None:
        """Get an entity by ID."""
        return self._entities.get(entity_id)
    
    def get_entities(self, entity_type: EntityType | None = None) -> list[Entity]:
        """Get all entities, optionally filtered by type."""
        if entity_type is None:
            return list(self._entities.values())
        return [e for e in self._entities.values() if e.entity_type == entity_type]
    
    def get_relations(self, relation_type: RelationType | None = None) -> list[Relation]:
        """Get all relations, optionally filtered by type."""
        if relation_type is None:
            return list(self._relations)
        return [r for r in self._relations if r.relation_type == relation_type]
    
    def get_root_causes(self) -> list[Entity]:
        """Get all root cause entities."""
        return self.get_entities(EntityType.ROOT_CAUSE)
    
    def get_causal_chain(self, entity_id: str) -> list[list[str]]:
        """Get all causal chains leading from an entity."""
        if entity_id not in self._entities:
            return []
        
        chains = []
        for successor in self._graph.successors(entity_id):
            sub_chains = self.get_causal_chain(successor)
            if sub_chains:
                for chain in sub_chains:
                    chains.append([entity_id] + chain)
            else:
                chains.append([entity_id, successor])
        
        if not chains:
            chains = [[entity_id]]
        
        return chains
    
    def get_upstream_causes(self, entity_id: str) -> list[Entity]:
        """Get all entities that cause the given entity."""
        if entity_id not in self._entities:
            return []
        predecessors = list(nx.ancestors(self._graph, entity_id))
        return [self._entities[p] for p in predecessors if p in self._entities]
    
    def get_downstream_effects(self, entity_id: str) -> list[Entity]:
        """Get all entities affected by the given entity."""
        if entity_id not in self._entities:
            return []
        descendants = list(nx.descendants(self._graph, entity_id))
        return [self._entities[d] for d in descendants if d in self._entities]
    
    @property
    def networkx_graph(self) -> nx.DiGraph:
        """Get the underlying NetworkX graph."""
        return self._graph
    
    def to_dict(self) -> dict[str, Any]:
        """Convert graph to dictionary format."""
        return {
            "entities": [e.to_dict() for e in self._entities.values()],
            "relations": [r.to_dict() for r in self._relations],
            "metadata": {
                "num_entities": len(self._entities),
                "num_relations": len(self._relations),
                "entity_types": list(set(e.entity_type.value for e in self._entities.values())),
                "relation_types": list(set(r.relation_type.value for r in self._relations)),
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert graph to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalGraph:
        """Create graph from dictionary."""
        graph = cls()
        for entity_data in data.get("entities", []):
            graph.add_entity(Entity.from_dict(entity_data))
        for relation_data in data.get("relations", []):
            graph.add_relation(Relation.from_dict(relation_data))
        return graph
    
    @classmethod
    def from_json(cls, json_str: str) -> CausalGraph:
        """Create graph from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __repr__(self) -> str:
        return f"CausalGraph(entities={len(self._entities)}, relations={len(self._relations)})"
