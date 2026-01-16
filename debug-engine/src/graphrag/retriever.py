"""Retriever that combines vector search and graph traversal."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .vector_store import VectorStore, SearchResult
from .neo4j_store import Neo4jStore, EntityNode
from .fix_store import FixStore, HistoricalFix
from .embeddings import EmbeddingService
from .metric_parser import MetricParser, ExtractedMetrics


@dataclass
class DiagnosisContext:
    """Context retrieved for LLM diagnosis."""
    # Extracted metrics from input
    metrics: ExtractedMetrics
    
    # Vector search results
    matched_entities: list[SearchResult]
    
    # Graph traversal results
    root_causes: list[EntityNode]
    causal_chains: list[list[EntityNode]]
    subgraph: dict[str, Any]
    
    # Historical fixes
    relevant_fixes: list[HistoricalFix]
    
    def to_prompt_context(self) -> str:
        """Convert to a prompt-ready string for LLM."""
        lines = []
        
        # Metrics - emphasize these are the actual values to use
        lines.append("## Observed Metrics (USE THESE EXACT VALUES IN YOUR ANALYSIS)")
        lines.append(self.metrics.to_query_string())
        lines.append("")
        
        # Root causes from graph
        lines.append("## Root Causes (from CKG)")
        if self.root_causes:
            for rc in self.root_causes:
                lines.append(f"- {rc.label}: {rc.description}")
        else:
            lines.append("- No root causes identified")
        lines.append("")
        
        # Causal chains
        lines.append("## Causal Chain")
        if self.causal_chains:
            for chain in self.causal_chains[:3]:  # Limit to 3 chains
                chain_str = " → ".join(e.label for e in chain)
                lines.append(f"- {chain_str}")
        lines.append("")
        
        # Anomaly patterns - help LLM identify issues
        lines.append("## Anomaly Patterns (CHECK THESE CONDITIONS)")
        lines.append("- VCORE 725mV > 10%: Indicates CM/PowerHal/DDR voting issue")
        lines.append("- VCORE floor > 575mV: Indicates MMDVFS OPP3 issue (floor should be 575mV)")
        lines.append("- MMDVFS at OPP3 with high usage: Causes VCORE floor at 600mV")
        lines.append("- MMDVFS at OPP4: Normal operation, rule out as cause")
        lines.append("- DUAL ISSUE: If BOTH floor AND ceiling abnormal, report BOTH root causes")
        lines.append("")
        
        # Historical fixes - clarify these are reference only
        lines.append("## Historical Fixes (REFERENCE ONLY - do not copy these metrics)")
        if self.relevant_fixes:
            for fix in self.relevant_fixes:
                lines.append(f"- Case {fix.case_id}: {fix.fix_description}")
                if fix.resolution_notes:
                    lines.append(f"  Notes: {fix.resolution_notes}")
        else:
            lines.append("- No relevant historical fixes found")
        
        return "\n".join(lines)
    
    def token_estimate(self) -> int:
        """Estimate token count for this context."""
        text = self.to_prompt_context()
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4


class Retriever:
    """Retriever that combines vector search, graph traversal, and fix lookup."""
    
    def __init__(
        self,
        vector_store: VectorStore,
        neo4j_store: Neo4jStore,
        fix_store: FixStore,
        embedding_service: EmbeddingService,
    ):
        """Initialize the retriever.
        
        Args:
            vector_store: FAISS vector store
            neo4j_store: Neo4j graph store
            fix_store: SQLite fix store
            embedding_service: OpenAI embeddings
        """
        self._vector_store = vector_store
        self._neo4j_store = neo4j_store
        self._fix_store = fix_store
        self._embedding_service = embedding_service
        self._metric_parser = MetricParser()
    
    def retrieve(
        self,
        input_text: str,
        top_k_vectors: int = 5,
        max_hops: int = 5,
    ) -> DiagnosisContext:
        """Retrieve relevant context for diagnosis.
        
        Args:
            input_text: User input (observation/question + metrics)
            top_k_vectors: Number of vector search results
            max_hops: Maximum graph traversal depth
            
        Returns:
            DiagnosisContext with all retrieved information
        """
        # Step 1: Parse metrics from input
        metrics = self._metric_parser.parse(input_text)
        
        # Step 2: Vector search for similar symptoms/entities
        query_text = metrics.to_query_string() if metrics.has_metrics() else input_text
        query_embedding = self._embedding_service.embed_text(query_text)
        matched_entities = self._vector_store.search(query_embedding, k=top_k_vectors)
        
        # Step 3: Graph traversal for each matched entity
        root_causes = []
        causal_chains = []
        all_entity_ids = [m.entity_id for m in matched_entities]
        
        for match in matched_entities:
            # Get upstream causes
            upstream = self._neo4j_store.get_root_causes(match.entity_id)
            
            for rc in upstream:
                if rc not in root_causes:
                    root_causes.append(rc)
                    
                    # Get causal chain from root cause to symptom
                    chain = self._neo4j_store.get_causal_chain(
                        from_id=rc.id,
                        to_id=match.entity_id,
                    )
                    if chain:
                        causal_chains.append(chain)
        
        # Step 4: Get subgraph around matched entities
        subgraph = self._neo4j_store.get_subgraph(all_entity_ids, hops=2)
        
        # Step 5: Get historical fixes for found root causes
        relevant_fixes = []
        for rc in root_causes:
            fixes = self._fix_store.get_fixes_by_root_cause(rc.label)
            relevant_fixes.extend(fixes)
        
        return DiagnosisContext(
            metrics=metrics,
            matched_entities=matched_entities,
            root_causes=root_causes,
            causal_chains=causal_chains,
            subgraph=subgraph,
            relevant_fixes=relevant_fixes,
        )
    
    def retrieve_from_metrics(
        self,
        metrics: ExtractedMetrics,
        top_k_vectors: int = 5,
    ) -> DiagnosisContext:
        """Retrieve context from already-parsed metrics.
        
        Args:
            metrics: Pre-parsed metrics
            top_k_vectors: Number of vector search results
            
        Returns:
            DiagnosisContext with all retrieved information
        """
        # Convert metrics to search query and proceed
        query_text = metrics.to_query_string()
        return self.retrieve(query_text, top_k_vectors=top_k_vectors)
    
    def retrieve_for_anomaly(
        self,
        anomaly: "DetectedAnomaly",
        metrics: ExtractedMetrics,
    ) -> DiagnosisContext:
        """Retrieve CKG context specific to one anomaly (Stage 2).
        
        Args:
            anomaly: The detected anomaly to get context for
            metrics: Original extracted metrics
            
        Returns:
            DiagnosisContext focused on this anomaly's indicated causes
        """
        # Get indicated root cause entities
        root_causes = []
        for cause_id in anomaly.indicated_causes:
            entity = self._neo4j_store.get_entity(cause_id)
            if entity and entity.type == "RootCause":
                root_causes.append(entity)
        
        # If no indicated causes, try to find by anomaly type
        if not root_causes:
            root_causes = self._infer_causes_from_type(anomaly.type)
        
        # Get subgraph around indicated causes
        cause_ids = anomaly.indicated_causes or [rc.id for rc in root_causes]
        subgraph = {}
        if cause_ids:
            subgraph = self._neo4j_store.get_subgraph(cause_ids, hops=2)
        
        # Build causal chains from root causes
        causal_chains = []
        for rc in root_causes:
            # Find symptom nodes that match anomaly type
            symptom_ids = self._find_symptom_for_anomaly(anomaly.type)
            for symptom_id in symptom_ids[:1]:  # Just first match
                chain = self._neo4j_store.get_causal_chain(rc.id, symptom_id)
                if chain:
                    causal_chains.append(chain)
        
        # Get relevant historical fixes
        relevant_fixes = []
        for rc in root_causes:
            fixes = self._fix_store.get_fixes_by_root_cause(rc.label)
            relevant_fixes.extend(fixes)
        
        # Limit fixes to avoid token bloat
        relevant_fixes = relevant_fixes[:3]
        
        return DiagnosisContext(
            metrics=metrics,
            matched_entities=[],  # Not using vector search here
            root_causes=root_causes,
            causal_chains=causal_chains,
            subgraph=subgraph,
            relevant_fixes=relevant_fixes,
        )
    
    def _infer_causes_from_type(self, anomaly_type: str) -> list:
        """Infer likely root causes from anomaly type."""
        # Map anomaly types to likely root causes
        type_to_causes = {
            "VCORE_CEILING": ["rc_cm", "rc_powerhal"],
            "VCORE_FLOOR": ["rc_mmdvfs"],
            "DDR_HIGH": ["rc_cm", "rc_powerhal"],
            "MMDVFS_ABNORMAL": ["rc_mmdvfs"],
            "CPU_CEILING": ["rc_cm", "rc_policy"],
        }
        
        cause_ids = type_to_causes.get(anomaly_type, [])
        causes = []
        for cid in cause_ids:
            entity = self._neo4j_store.get_entity(cid)
            if entity:
                causes.append(entity)
        return causes
    
    def _find_symptom_for_anomaly(self, anomaly_type: str) -> list[str]:
        """Find symptom entity IDs that match anomaly type."""
        # Map anomaly types to symptom entity patterns
        type_to_symptoms = {
            "VCORE_CEILING": ["c1_vcore", "c2_vcore", "c3_vcore_high"],
            "VCORE_FLOOR": ["c3_vcore_floor"],
            "DDR_HIGH": ["c1_ddr", "c2_ddr", "c3_ddr"],
            "MMDVFS_ABNORMAL": ["c3_vcore_floor"],
        }
        return type_to_symptoms.get(anomaly_type, [])

