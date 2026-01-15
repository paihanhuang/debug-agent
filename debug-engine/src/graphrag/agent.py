"""Debug agent - main orchestrator for LLM-based diagnosis."""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .retriever import Retriever, DiagnosisContext
from .vector_store import VectorStore
from .neo4j_store import Neo4jStore
from .fix_store import FixStore
from .embeddings import EmbeddingService
from .metric_parser import MetricParser


SYSTEM_PROMPT = """You are an expert power debugging assistant for mobile devices.

Your task is to analyze power issues based on:
1. Observed metrics (VCORE, DDR, MMDVFS, CPU frequencies)
2. Causal knowledge from the CKG (Causal Knowledge Graph)
3. Historical fixes for similar issues

Guidelines:
- Identify the root cause based on the CKG causal chains
- Explain the causal chain from root cause to symptom
- List ALL relevant historical fixes (do not rank them)
- Be precise about metric values and thresholds
- Use technical terminology appropriate for power engineers

Response format:
## Root Cause
[Identified root cause]

## Causal Chain
[Chain from root cause to symptom]

## Diagnosis
[Explanation of why this is the root cause]

## Historical Fixes (for reference)
[List all relevant fixes without ranking]
"""


@dataclass
class DiagnosisResult:
    """Result of a diagnosis."""
    root_cause: str
    causal_chain: str
    diagnosis: str
    historical_fixes: list[str]
    raw_response: str
    context: DiagnosisContext
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "causal_chain": self.causal_chain,
            "diagnosis": self.diagnosis,
            "historical_fixes": self.historical_fixes,
            "raw_response": self.raw_response,
        }


class DebugAgent:
    """Main agent for power debugging using GraphRAG."""
    
    def __init__(
        self,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        fix_db_path: str = "fixes.db",
        vector_store_path: str | None = None,
        openai_api_key: str | None = None,
        llm_model: str = "gpt-4o",
    ):
        """Initialize the debug agent.
        
        Args:
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            fix_db_path: Path to SQLite fix database
            vector_store_path: Path to saved vector store (optional)
            openai_api_key: OpenAI API key
            llm_model: LLM model for diagnosis (default: gpt-4o)
        """
        self._llm_model = llm_model
        self._api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        
        if not self._api_key:
            raise ValueError("OpenAI API key required")
        
        # Initialize components
        self._embedding_service = EmbeddingService(api_key=self._api_key)
        
        # Vector store
        if vector_store_path:
            self._vector_store = VectorStore.load(vector_store_path)
        else:
            self._vector_store = VectorStore(dimension=self._embedding_service.dimension)
        
        # Neo4j store
        self._neo4j_store = Neo4jStore(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
        )
        
        # Fix store
        self._fix_store = FixStore(fix_db_path)
        
        # Retriever
        self._retriever = Retriever(
            vector_store=self._vector_store,
            neo4j_store=self._neo4j_store,
            fix_store=self._fix_store,
            embedding_service=self._embedding_service,
        )
        
        # LLM client
        self._llm_client = OpenAI(api_key=self._api_key)
        
        # Metric parser
        self._metric_parser = MetricParser()
    
    def connect(self) -> None:
        """Connect to Neo4j."""
        self._neo4j_store.connect()
    
    def close(self) -> None:
        """Close all connections."""
        self._neo4j_store.close()
        self._fix_store.close()
    
    def __enter__(self) -> "DebugAgent":
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def diagnose(self, input_text: str) -> DiagnosisResult:
        """Diagnose a power issue.
        
        Args:
            input_text: User input with observation/metrics
            
        Returns:
            DiagnosisResult with root cause and fixes
        """
        # Step 1: Retrieve context
        context = self._retriever.retrieve(input_text)
        
        # Step 2: Build prompt
        prompt = self._build_prompt(input_text, context)
        
        # Step 3: Call LLM
        response = self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Low temperature for consistency
        )
        
        raw_response = response.choices[0].message.content
        
        # Step 4: Parse response
        return self._parse_response(raw_response, context)
    
    def _build_prompt(self, input_text: str, context: DiagnosisContext) -> str:
        """Build the prompt for LLM."""
        lines = [
            "## User Observation",
            input_text,
            "",
            context.to_prompt_context(),
            "",
            "Please analyze this power issue and provide your diagnosis.",
        ]
        return "\n".join(lines)
    
    def _parse_response(
        self,
        raw_response: str,
        context: DiagnosisContext,
    ) -> DiagnosisResult:
        """Parse LLM response into structured result."""
        # Simple parsing - can be made more robust
        root_cause = ""
        causal_chain = ""
        diagnosis = ""
        historical_fixes = []
        
        sections = raw_response.split("## ")
        for section in sections:
            if section.startswith("Root Cause"):
                root_cause = section.split("\n", 1)[1].strip() if "\n" in section else ""
            elif section.startswith("Causal Chain"):
                causal_chain = section.split("\n", 1)[1].strip() if "\n" in section else ""
            elif section.startswith("Diagnosis"):
                diagnosis = section.split("\n", 1)[1].strip() if "\n" in section else ""
            elif section.startswith("Historical Fixes"):
                content = section.split("\n", 1)[1] if "\n" in section else ""
                historical_fixes = [
                    line.strip("- ").strip()
                    for line in content.split("\n")
                    if line.strip().startswith("-")
                ]
        
        return DiagnosisResult(
            root_cause=root_cause,
            causal_chain=causal_chain,
            diagnosis=diagnosis,
            historical_fixes=historical_fixes,
            raw_response=raw_response,
            context=context,
        )
    
    # ========================================
    # Setup methods
    # ========================================
    
    def index_entity(self, entity: dict[str, Any]) -> None:
        """Add an entity to the vector index.
        
        Args:
            entity: Entity dict with id, label, type, description
        """
        embedding = self._embedding_service.embed_entity(entity)
        self._vector_store.add(
            entity_id=entity["id"],
            embedding=embedding,
            metadata={
                "label": entity.get("label", ""),
                "type": entity.get("type", ""),
            },
        )
    
    def load_ckg(self, ckg_data: dict[str, Any]) -> None:
        """Load a complete CKG into Neo4j and vector store.
        
        Args:
            ckg_data: CKG dictionary with entities and relations
        """
        # Load into Neo4j
        self._neo4j_store.load_ckg_from_dict(ckg_data)
        
        # Index entities in vector store
        for entity in ckg_data.get("entities", []):
            self.index_entity(entity)
    
    def add_historical_fix(
        self,
        case_id: str,
        root_cause: str,
        symptom_summary: str,
        metrics: dict[str, Any],
        fix_description: str,
        resolution_notes: str = "",
    ) -> None:
        """Add a historical fix to the database.
        
        Args:
            case_id: Unique case identifier
            root_cause: Root cause (must match CKG root cause labels)
            symptom_summary: Brief summary of symptoms
            metrics: Metric values for this case
            fix_description: What was done to fix
            resolution_notes: Additional notes
        """
        from .fix_store import HistoricalFix
        
        fix = HistoricalFix(
            case_id=case_id,
            root_cause=root_cause,
            symptom_summary=symptom_summary,
            metrics=metrics,
            fix_description=fix_description,
            resolution_notes=resolution_notes,
        )
        self._fix_store.add_fix(fix)
    
    def save_vector_store(self, path: str) -> None:
        """Save the vector store to disk."""
        self._vector_store.save(path)
