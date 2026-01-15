"""Tests for graph models."""

import pytest
import json
from src.graph.models import Entity, Relation, CausalGraph, EntityType, RelationType


class TestEntity:
    """Test cases for Entity class."""
    
    def test_entity_creation(self):
        """Test basic entity creation."""
        entity = Entity(
            id="e1",
            entity_type=EntityType.SYMPTOM,
            label="503 errors",
        )
        assert entity.id == "e1"
        assert entity.entity_type == EntityType.SYMPTOM
        assert entity.label == "503 errors"
    
    def test_entity_to_dict(self):
        """Test entity serialization to dict."""
        entity = Entity(
            id="e1",
            entity_type=EntityType.ROOT_CAUSE,
            label="Missing index",
            description="Database index was missing",
            confidence=0.95,
        )
        d = entity.to_dict()
        assert d["id"] == "e1"
        assert d["type"] == "RootCause"
        assert d["label"] == "Missing index"
        assert d["confidence"] == 0.95
    
    def test_entity_from_dict(self):
        """Test entity deserialization from dict."""
        data = {
            "id": "e2",
            "type": "Component",
            "label": "Database server",
            "description": "Main DB",
            "confidence": 0.9,
        }
        entity = Entity.from_dict(data)
        assert entity.id == "e2"
        assert entity.entity_type == EntityType.COMPONENT
        assert entity.label == "Database server"


class TestRelation:
    """Test cases for Relation class."""
    
    def test_relation_creation(self):
        """Test basic relation creation."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
        )
        assert relation.source_id == "e1"
        assert relation.target_id == "e2"
        assert relation.relation_type == RelationType.CAUSES
    
    def test_relation_to_dict(self):
        """Test relation serialization to dict."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.INDICATES,
            confidence=0.8,
            evidence="Log analysis showed correlation",
        )
        d = relation.to_dict()
        assert d["source"] == "e1"
        assert d["target"] == "e2"
        assert d["type"] == "INDICATES"
        assert d["confidence"] == 0.8


class TestCausalGraph:
    """Test cases for CausalGraph class."""
    
    def test_empty_graph(self):
        """Test empty graph creation."""
        graph = CausalGraph()
        assert len(graph.get_entities()) == 0
        assert len(graph.get_relations()) == 0
    
    def test_add_entity(self):
        """Test adding entities to graph."""
        graph = CausalGraph()
        entity = Entity(id="e1", entity_type=EntityType.SYMPTOM, label="Error")
        graph.add_entity(entity)
        
        assert len(graph.get_entities()) == 1
        assert graph.get_entity("e1") == entity
    
    def test_add_relation(self):
        """Test adding relations to graph."""
        graph = CausalGraph()
        e1 = Entity(id="e1", entity_type=EntityType.ROOT_CAUSE, label="Cause")
        e2 = Entity(id="e2", entity_type=EntityType.SYMPTOM, label="Effect")
        
        graph.add_entity(e1)
        graph.add_entity(e2)
        
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
        )
        graph.add_relation(relation)
        
        assert len(graph.get_relations()) == 1
    
    def test_add_relation_invalid_source(self):
        """Test that adding relation with invalid source raises error."""
        graph = CausalGraph()
        e2 = Entity(id="e2", entity_type=EntityType.SYMPTOM, label="Effect")
        graph.add_entity(e2)
        
        relation = Relation(
            source_id="e1",  # Doesn't exist
            target_id="e2",
            relation_type=RelationType.CAUSES,
        )
        
        with pytest.raises(ValueError):
            graph.add_relation(relation)
    
    def test_get_root_causes(self):
        """Test getting root cause entities."""
        graph = CausalGraph()
        rc = Entity(id="rc1", entity_type=EntityType.ROOT_CAUSE, label="Root cause")
        sym = Entity(id="s1", entity_type=EntityType.SYMPTOM, label="Symptom")
        
        graph.add_entity(rc)
        graph.add_entity(sym)
        
        root_causes = graph.get_root_causes()
        assert len(root_causes) == 1
        assert root_causes[0].id == "rc1"
    
    def test_to_json_and_from_json(self):
        """Test JSON round-trip serialization."""
        graph = CausalGraph()
        e1 = Entity(id="e1", entity_type=EntityType.ROOT_CAUSE, label="Cause")
        e2 = Entity(id="e2", entity_type=EntityType.SYMPTOM, label="Effect")
        
        graph.add_entity(e1)
        graph.add_entity(e2)
        graph.add_relation(Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
        ))
        
        json_str = graph.to_json()
        restored = CausalGraph.from_json(json_str)
        
        assert len(restored.get_entities()) == 2
        assert len(restored.get_relations()) == 1
    
    def test_get_downstream_effects(self):
        """Test getting downstream effects of an entity."""
        graph = CausalGraph()
        e1 = Entity(id="e1", entity_type=EntityType.ROOT_CAUSE, label="Root")
        e2 = Entity(id="e2", entity_type=EntityType.COMPONENT, label="Middle")
        e3 = Entity(id="e3", entity_type=EntityType.SYMPTOM, label="Symptom")
        
        graph.add_entity(e1)
        graph.add_entity(e2)
        graph.add_entity(e3)
        
        graph.add_relation(Relation("e1", "e2", RelationType.CAUSES))
        graph.add_relation(Relation("e2", "e3", RelationType.CAUSES))
        
        effects = graph.get_downstream_effects("e1")
        effect_ids = {e.id for e in effects}
        assert "e2" in effect_ids
        assert "e3" in effect_ids
