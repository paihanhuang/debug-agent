"""Neo4j graph store for CKG structure and traversal."""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase


@dataclass
class EntityNode:
    """Entity from the graph."""
    id: str
    type: str
    label: str
    description: str = ""


@dataclass
class RelationEdge:
    """Relation between entities."""
    source_id: str
    target_id: str
    type: str
    strength: float = 1.0
    mechanism: str = ""


class Neo4jStore:
    """Neo4j client for CKG storage and graph traversal."""
    
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        """Initialize Neo4j connection.
        
        Args:
            uri: Neo4j URI (default: from NEO4J_URI env)
            user: Neo4j user (default: from NEO4J_USER env)
            password: Neo4j password (default: from NEO4J_PASSWORD env)
        """
        self._uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self._user = user or os.getenv("NEO4J_USER", "neo4j")
        self._password = password or os.getenv("NEO4J_PASSWORD", "password")
        self._driver = None
    
    def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        # Verify connection
        self._driver.verify_connectivity()
    
    def close(self) -> None:
        """Close the connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def __enter__(self) -> "Neo4jStore":
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    # ========================================
    # Write Operations
    # ========================================
    
    def add_entity(self, entity: EntityNode) -> None:
        """Add an entity node to the graph."""
        query = """
        MERGE (e:Entity {id: $id})
        SET e.type = $type,
            e.label = $label,
            e.description = $description
        """
        with self._driver.session() as session:
            session.run(
                query,
                id=entity.id,
                type=entity.type,
                label=entity.label,
                description=entity.description,
            )
    
    def add_relation(self, relation: RelationEdge) -> None:
        """Add a relation edge to the graph."""
        query = """
        MATCH (s:Entity {id: $source_id})
        MATCH (t:Entity {id: $target_id})
        MERGE (s)-[r:RELATION {type: $type}]->(t)
        SET r.strength = $strength,
            r.mechanism = $mechanism
        """
        with self._driver.session() as session:
            session.run(
                query,
                source_id=relation.source_id,
                target_id=relation.target_id,
                type=relation.type,
                strength=relation.strength,
                mechanism=relation.mechanism,
            )
    
    def load_ckg_from_dict(self, ckg_data: dict[str, Any]) -> None:
        """Load a complete CKG from dictionary format."""
        # Add entities
        for entity in ckg_data.get("entities", []):
            self.add_entity(EntityNode(
                id=entity["id"],
                type=entity["type"],
                label=entity["label"],
                description=entity.get("description", ""),
            ))
        
        # Add relations
        for rel in ckg_data.get("relations", []):
            causal_effect = rel.get("causal_effect", {})
            self.add_relation(RelationEdge(
                source_id=rel["source"],
                target_id=rel["target"],
                type=rel["type"],
                strength=causal_effect.get("strength", 1.0),
                mechanism=causal_effect.get("mechanism", ""),
            ))
    
    def clear_all(self) -> None:
        """Clear all nodes and relationships."""
        query = "MATCH (n) DETACH DELETE n"
        with self._driver.session() as session:
            session.run(query)
    
    # ========================================
    # Read Operations
    # ========================================
    
    def get_entity(self, entity_id: str) -> EntityNode | None:
        """Get an entity by ID."""
        query = "MATCH (e:Entity {id: $id}) RETURN e"
        with self._driver.session() as session:
            result = session.run(query, id=entity_id)
            record = result.single()
            if record:
                node = record["e"]
                return EntityNode(
                    id=node["id"],
                    type=node["type"],
                    label=node["label"],
                    description=node.get("description", ""),
                )
        return None
    
    def get_entities_by_type(self, entity_type: str) -> list[EntityNode]:
        """Get all entities of a specific type."""
        query = "MATCH (e:Entity {type: $type}) RETURN e"
        entities = []
        with self._driver.session() as session:
            result = session.run(query, type=entity_type)
            for record in result:
                node = record["e"]
                entities.append(EntityNode(
                    id=node["id"],
                    type=node["type"],
                    label=node["label"],
                    description=node.get("description", ""),
                ))
        return entities
    
    def get_all_entities(self) -> list[EntityNode]:
        """Get all entities."""
        query = "MATCH (e:Entity) RETURN e"
        entities = []
        with self._driver.session() as session:
            result = session.run(query)
            for record in result:
                node = record["e"]
                entities.append(EntityNode(
                    id=node["id"],
                    type=node["type"],
                    label=node["label"],
                    description=node.get("description", ""),
                ))
        return entities
    
    # ========================================
    # Graph Traversal
    # ========================================
    
    def get_upstream_causes(self, entity_id: str, max_hops: int = 5) -> list[EntityNode]:
        """Traverse upstream to find all causes of an entity.
        
        Args:
            entity_id: Starting entity ID
            max_hops: Maximum traversal depth
            
        Returns:
            List of upstream entities (causes)
        """
        query = f"""
        MATCH (target:Entity {{id: $id}})
        MATCH path = (cause:Entity)-[:RELATION*1..{max_hops}]->(target)
        RETURN DISTINCT cause
        """
        entities = []
        with self._driver.session() as session:
            result = session.run(query, id=entity_id)
            for record in result:
                node = record["cause"]
                entities.append(EntityNode(
                    id=node["id"],
                    type=node["type"],
                    label=node["label"],
                    description=node.get("description", ""),
                ))
        return entities
    
    def get_root_causes(self, entity_id: str) -> list[EntityNode]:
        """Get root causes for an entity (entities with type RootCause)."""
        upstream = self.get_upstream_causes(entity_id)
        return [e for e in upstream if e.type == "RootCause"]
    
    def get_causal_chain(self, from_id: str, to_id: str) -> list[EntityNode]:
        """Get the causal chain between two entities.
        
        Args:
            from_id: Source entity ID (cause)
            to_id: Target entity ID (effect)
            
        Returns:
            List of entities in the chain, in order
        """
        query = """
        MATCH path = shortestPath(
            (source:Entity {id: $from_id})-[:RELATION*]->(target:Entity {id: $to_id})
        )
        RETURN nodes(path) as chain
        """
        with self._driver.session() as session:
            result = session.run(query, from_id=from_id, to_id=to_id)
            record = result.single()
            if record:
                chain = []
                for node in record["chain"]:
                    chain.append(EntityNode(
                        id=node["id"],
                        type=node["type"],
                        label=node["label"],
                        description=node.get("description", ""),
                    ))
                return chain
        return []
    
    def get_subgraph(self, entity_ids: list[str], hops: int = 2) -> dict[str, Any]:
        """Get a subgraph around specified entities.
        
        Args:
            entity_ids: List of entity IDs to center on
            hops: Number of hops in each direction
            
        Returns:
            Dictionary with entities and relations
        """
        query = f"""
        MATCH (center:Entity)
        WHERE center.id IN $ids
        OPTIONAL MATCH path = (other:Entity)-[:RELATION*1..{hops}]-(center)
        WITH center, collect(DISTINCT other) as neighbors
        UNWIND neighbors + [center] as entity
        WITH DISTINCT entity
        MATCH (entity)-[r:RELATION]->(target:Entity)
        RETURN 
            collect(DISTINCT entity) as entities,
            collect(DISTINCT {{source: entity.id, target: target.id, type: r.type, strength: r.strength}}) as relations
        """
        with self._driver.session() as session:
            result = session.run(query, ids=entity_ids)
            record = result.single()
            if record:
                entities = [
                    EntityNode(
                        id=node["id"],
                        type=node["type"],
                        label=node["label"],
                        description=node.get("description", ""),
                    )
                    for node in record["entities"]
                ]
                relations = record["relations"]
                return {"entities": entities, "relations": relations}
        return {"entities": [], "relations": []}
