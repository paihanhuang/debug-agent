"""Tests for enhanced CKG features - DAG validation, causal effects, temporal ordering."""

import pytest
from src.graph.models import (
    Entity,
    EntityType,
    Relation,
    RelationType,
    CausalEffect,
    TemporalOrder,
    CausalGraph,
    CausalGraphValidationError,
    CAUSAL_RELATION_TYPES,
)


class TestCausalEffect:
    """Test cases for CausalEffect dataclass."""
    
    def test_causal_effect_creation(self):
        """Test basic causal effect creation."""
        effect = CausalEffect(
            strength=0.8,
            is_direct=True,
            temporal_order=TemporalOrder.MINUTES,
            mechanism="Memory exhaustion causes slow queries",
        )
        assert effect.strength == 0.8
        assert effect.is_direct is True
        assert effect.temporal_order == TemporalOrder.MINUTES
        assert "Memory" in effect.mechanism
    
    def test_causal_effect_to_dict(self):
        """Test causal effect serialization."""
        effect = CausalEffect(
            strength=-0.5,
            is_direct=False,
            temporal_order=TemporalOrder.HOURS,
            mechanism="Cache reduces load",
        )
        d = effect.to_dict()
        assert d["strength"] == -0.5
        assert d["is_direct"] is False
        assert d["temporal_order"] == "hours"
    
    def test_causal_effect_from_dict(self):
        """Test causal effect deserialization."""
        data = {
            "strength": 0.9,
            "is_direct": True,
            "temporal_order": "immediate",
            "mechanism": "Direct crash",
        }
        effect = CausalEffect.from_dict(data)
        assert effect.strength == 0.9
        assert effect.temporal_order == TemporalOrder.IMMEDIATE


class TestRelationCausalProperties:
    """Test cases for Relation causal properties."""
    
    def test_is_causal_for_causes(self):
        """Test that CAUSES relation is marked as causal."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
        )
        assert relation.is_causal is True
    
    def test_is_causal_for_prevents(self):
        """Test that PREVENTS relation is marked as causal."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.PREVENTS,
        )
        assert relation.is_causal is True
    
    def test_is_not_causal_for_correlates(self):
        """Test that CORRELATES_WITH relation is NOT causal."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CORRELATES_WITH,
        )
        assert relation.is_causal is False
    
    def test_is_not_causal_for_indicates(self):
        """Test that INDICATES relation is NOT causal."""
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.INDICATES,
        )
        assert relation.is_causal is False
    
    def test_relation_with_causal_effect(self):
        """Test relation with causal effect attached."""
        effect = CausalEffect(strength=0.9, temporal_order=TemporalOrder.SECONDS)
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
            causal_effect=effect,
        )
        assert relation.causal_effect is not None
        assert relation.causal_effect.strength == 0.9
    
    def test_relation_to_dict_includes_causal_effect(self):
        """Test relation serialization includes causal effect."""
        effect = CausalEffect(strength=0.7)
        relation = Relation(
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.CAUSES,
            causal_effect=effect,
        )
        d = relation.to_dict()
        assert "is_causal" in d
        assert d["is_causal"] is True
        assert "causal_effect" in d
        assert d["causal_effect"]["strength"] == 0.7


class TestDAGValidation:
    """Test cases for DAG validation in CausalGraph."""
    
    def test_empty_graph_is_valid_dag(self):
        """Test that empty graph is a valid DAG."""
        graph = CausalGraph()
        assert graph.is_valid_dag() is True
    
    def test_simple_chain_is_valid_dag(self):
        """Test that a simple chain A->B->C is a valid DAG."""
        graph = CausalGraph()
        graph.add_entity(Entity(id="a", entity_type=EntityType.ROOT_CAUSE, label="A"))
        graph.add_entity(Entity(id="b", entity_type=EntityType.COMPONENT, label="B"))
        graph.add_entity(Entity(id="c", entity_type=EntityType.SYMPTOM, label="C"))
        
        graph.add_relation(Relation("a", "b", RelationType.CAUSES))
        graph.add_relation(Relation("b", "c", RelationType.CAUSES))
        
        assert graph.is_valid_dag() is True
    
    def test_cycle_prevention_in_strict_mode(self):
        """Test that adding a cycle raises error in strict DAG mode."""
        graph = CausalGraph(strict_dag=True)
        graph.add_entity(Entity(id="a", entity_type=EntityType.ROOT_CAUSE, label="A"))
        graph.add_entity(Entity(id="b", entity_type=EntityType.SYMPTOM, label="B"))
        
        # Add A -> B
        graph.add_relation(Relation("a", "b", RelationType.CAUSES))
        
        # Try to add B -> A (would create cycle)
        with pytest.raises(CausalGraphValidationError):
            graph.add_relation(Relation("b", "a", RelationType.CAUSES))
    
    def test_cycle_allowed_for_non_causal_relations(self):
        """Test that non-causal relations can create cycles."""
        graph = CausalGraph(strict_dag=True)
        graph.add_entity(Entity(id="a", entity_type=EntityType.COMPONENT, label="A"))
        graph.add_entity(Entity(id="b", entity_type=EntityType.COMPONENT, label="B"))
        
        # Add A -> B (CORRELATES_WITH is not causal)
        graph.add_relation(Relation("a", "b", RelationType.CORRELATES_WITH))
        
        # This should NOT raise because CORRELATES_WITH is not causal
        graph.add_relation(Relation("b", "a", RelationType.CORRELATES_WITH))
        
        # Graph has a cycle but it's allowed for non-causal
        assert len(graph.get_relations()) == 2
    
    def test_non_strict_mode_allows_cycles(self):
        """Test that cycles are allowed in non-strict mode."""
        graph = CausalGraph(strict_dag=False)
        graph.add_entity(Entity(id="a", entity_type=EntityType.ROOT_CAUSE, label="A"))
        graph.add_entity(Entity(id="b", entity_type=EntityType.SYMPTOM, label="B"))
        
        graph.add_relation(Relation("a", "b", RelationType.CAUSES))
        # This should NOT raise in non-strict mode
        graph.add_relation(Relation("b", "a", RelationType.CAUSES))
        
        # But validation should report issue
        issues = graph.validate()
        assert any("cycle" in issue.lower() for issue in issues)
    
    def test_validate_reports_multiple_issues(self):
        """Test that validate() returns all issues."""
        graph = CausalGraph(strict_dag=False)
        graph.add_entity(Entity(id="isolated", entity_type=EntityType.COMPONENT, label="Isolated"))
        
        issues = graph.validate()
        # Should report isolated node
        assert len(issues) >= 1
    
    def test_get_causal_relations_only(self):
        """Test filtering to only causal relations."""
        graph = CausalGraph()
        graph.add_entity(Entity(id="a", entity_type=EntityType.ROOT_CAUSE, label="A"))
        graph.add_entity(Entity(id="b", entity_type=EntityType.SYMPTOM, label="B"))
        graph.add_entity(Entity(id="c", entity_type=EntityType.COMPONENT, label="C"))
        
        # Add causal and non-causal relations
        graph.add_relation(Relation("a", "b", RelationType.CAUSES))
        graph.add_relation(Relation("b", "c", RelationType.CORRELATES_WITH))
        
        causal_only = graph.get_causal_relations_only()
        assert len(causal_only) == 1
        assert causal_only[0].relation_type == RelationType.CAUSES


class TestTemporalOrder:
    """Test cases for TemporalOrder enum."""
    
    def test_temporal_order_values(self):
        """Test that all temporal orders have correct values."""
        assert TemporalOrder.IMMEDIATE.value == "immediate"
        assert TemporalOrder.SECONDS.value == "seconds"
        assert TemporalOrder.MINUTES.value == "minutes"
        assert TemporalOrder.HOURS.value == "hours"
        assert TemporalOrder.DAYS.value == "days"
        assert TemporalOrder.UNKNOWN.value == "unknown"


class TestCausalRelationTypes:
    """Test cases for CAUSAL_RELATION_TYPES constant."""
    
    def test_causes_is_causal(self):
        assert RelationType.CAUSES in CAUSAL_RELATION_TYPES
    
    def test_prevents_is_causal(self):
        assert RelationType.PREVENTS in CAUSAL_RELATION_TYPES
    
    def test_enables_is_causal(self):
        assert RelationType.ENABLES in CAUSAL_RELATION_TYPES
    
    def test_correlates_is_not_causal(self):
        assert RelationType.CORRELATES_WITH not in CAUSAL_RELATION_TYPES
    
    def test_indicates_is_not_causal(self):
        assert RelationType.INDICATES not in CAUSAL_RELATION_TYPES
