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
from .metric_parser import ExtractedMetrics


SYSTEM_PROMPT = """You are an expert power debugging assistant for mobile devices.

CRITICAL RULES (MUST FOLLOW):
1. ALWAYS use metric values from the "User Observation" section - these are the ACTUAL values
2. NEVER copy metrics from "Historical Fixes" - those are reference cases only  
3. In your Causal Chain, include the EXACT percentages from the user's input
4. Treat Chinese and English terms as equivalent (拉檔 = frequency throttling)
5. DETECT MULTIPLE ROOT CAUSES - Power issues often have 2+ independent contributing factors
6. ALWAYS check for DUAL VCORE issues:
   - VCORE FLOOR issue: If VCORE floor > 575mV (e.g., 600mV), this indicates MMDVFS OPP3 issue
   - VCORE CEILING issue: If VCORE 725mV > 10%, this indicates CM/PowerHal/DDR voting issue
   - These are INDEPENDENT issues with DIFFERENT root causes
7. MMDVFS status MUST be addressed:
   - If MMDVFS at OPP4: Explicitly state "MMDVFS ruled out (OPP4 = normal operation)"
   - If MMDVFS at OPP3 with high usage: This IS a root cause for VCORE floor issues
8. If a section titled "CKG Traversal Nodes" is provided, you MUST explicitly include every node label listed there in your report.

Your task is to analyze power issues based on:
1. Observed metrics (VCORE, DDR, MMDVFS, CPU frequencies) - USE EXACT VALUES
2. Causal knowledge from the CKG (Causal Knowledge Graph)
3. Historical fixes for similar issues (for reference patterns only)

Guidelines:
- Identify ALL root causes based on the CKG causal chains
- If BOTH VCORE floor AND VCORE 725mV are abnormal, report BOTH root causes separately
- Explain the causal chain from each root cause to its symptom with EXACT user metrics
- List ALL relevant historical fixes (do not rank them)
- Be precise about metric values and thresholds
- Use technical terminology appropriate for power engineers

Response format:
## Root Cause
[Identified root cause(s) - list multiple if applicable]

## Causal Chain
[Chain from root cause to symptom - USE EXACT METRICS FROM USER INPUT]
[If multiple root causes, show each chain separately]

## Diagnosis
[Explanation of why this is the root cause]
[For MMDVFS: explicitly state if ruled out (OPP4) or confirmed (OPP3 high usage)]

## Historical Fixes (for reference)
[List all relevant fixes without ranking - do NOT copy their metrics to your analysis]
"""

POSTPROCESS_SYSTEM_PROMPT = """You are a precise technical editor.
Ensure the report includes all required CKG traversal node labels.
If any are missing, revise the report to include them without changing metrics.
Return only the revised report text."""

METRIC_REWRITE_SYSTEM_PROMPT = """You are an expert technical editor for power debugging reports.

Your job is to revise an existing report to NATURALLY include specific REQUIRED FACTS (metrics/frequencies).

CRITICAL RULES (MUST FOLLOW):
1. Do not change any numeric values already present in the report.
2. Do not invent any new metrics, numbers, thresholds, or facts beyond the REQUIRED FACTS list.
3. Do not add a new section like \"Metric Echo\". Blend facts into existing sections.
4. Preserve the report structure and tone. Make minimal edits.
5. Return ONLY the revised report text (no markdown fences, no commentary)."""


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
        fix_db_path: str = "output/fixes.db",
        vector_store_path: str | None = None,
        openai_api_key: str | None = None,
        llm_model: str = "gpt-4o",
        llm_client: Any | None = None,
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
        
        # LLM client (injectable for tests)
        self._llm_client = llm_client or OpenAI(api_key=self._api_key)
        
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
        raw_response = self._ensure_traversal_nodes(raw_response, context)
        raw_response = self._rewrite_report_to_include_required_metrics(raw_response, context.metrics)
        
        # Step 4: Parse response
        return self._parse_response(raw_response, context)

    def _metric_rewrite_enabled(self) -> bool:
        v = os.getenv("ENABLE_REPORT_METRIC_REWRITE")
        if v is None:
            return True  # default ON
        return v.strip().lower() not in {"0", "false", "no", "off"}

    def _rewrite_report_to_include_required_metrics(self, report: str, metrics: ExtractedMetrics) -> str:
        """Second-pass LLM editor to blend required metrics into the report (default ON).

        This is a targeted editor pass. It should not change meaning or numeric values.
        """
        if not self._metric_rewrite_enabled():
            return report

        required: list[str] = []
        # DDR breakdown
        if metrics.ddr5460_percent is not None:
            required.append(f"DDR5460: {metrics.ddr5460_percent}%")
        if metrics.ddr6370_percent is not None:
            required.append(f"DDR6370: {metrics.ddr6370_percent}%")
        if metrics.ddr_total_percent is not None:
            required.append(f"DDR total: {metrics.ddr_total_percent}%")

        # CPU frequencies
        if metrics.cpu_big_mhz is not None or metrics.cpu_mid_mhz is not None or metrics.cpu_small_mhz is not None:
            required.append(
                "CPU frequencies observed: "
                f"big={metrics.cpu_big_mhz}MHz, mid={metrics.cpu_mid_mhz}MHz, small={metrics.cpu_small_mhz}MHz"
            )

        if not required:
            return report

        lower = report.lower()
        need_tokens: list[str] = []
        if metrics.ddr5460_percent is not None:
            need_tokens.append("ddr5460")
        if metrics.ddr6370_percent is not None:
            need_tokens.append("ddr6370")
        if (metrics.cpu_big_mhz is not None or metrics.cpu_mid_mhz is not None or metrics.cpu_small_mhz is not None):
            need_tokens.append("mhz")

        # If already present, avoid the extra LLM call.
        if all(t in lower for t in need_tokens):
            return report

        prompt = f"""You are given a draft power debugging report and a list of REQUIRED FACTS.

REQUIRED FACTS (must be included verbatim, but you may adjust surrounding wording):
{chr(10).join('- ' + r for r in required)}

Draft Report:
{report}
"""
        try:
            resp = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": METRIC_REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            return resp.choices[0].message.content or report
        except Exception:
            return report
    
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

    def _ensure_traversal_nodes(
        self,
        raw_response: str,
        context: DiagnosisContext,
    ) -> str:
        """LLM post-processing to include all traversed nodes."""
        required_nodes = self._collect_required_nodes(context)
        if not required_nodes:
            return raw_response

        missing = [
            label for label in required_nodes
            if label.lower() not in raw_response.lower()
        ]
        if not missing:
            return raw_response

        prompt = """You are given a diagnosis report and a list of required CKG nodes.
Update the report so that EVERY required node label appears in the report text.
Preserve the original structure and all metric values. If you add text, do so in the Causal Chain section.

Required Nodes:
{required_nodes}

Original Report:
{report}
"""
        response = self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[
                {"role": "system", "content": POSTPROCESS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt.format(
                    required_nodes=", ".join(required_nodes),
                    report=raw_response,
                )},
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content or raw_response

    def _collect_required_nodes(self, context: DiagnosisContext) -> list[str]:
        labels = []
        for chain in context.causal_chains:
            for node in chain:
                label = getattr(node, "label", "")
                if label and label not in labels:
                    labels.append(label)
        return labels
    
    def refine(
        self,
        previous_result: DiagnosisResult,
        feedback: str,
        original_input: str,
    ) -> DiagnosisResult:
        """Refine a previous diagnosis based on Judge feedback.
        
        Args:
            previous_result: Previous diagnosis to improve
            feedback: Specific feedback on what to improve
            original_input: Original user input for metric reference
            
        Returns:
            Improved DiagnosisResult
        """
        refinement_prompt = f"""## Original User Input (USE THESE EXACT METRICS)
{original_input}

## Your Previous Response
{previous_result.raw_response}

## Quality Feedback from Evaluator
{feedback}

## Instructions
Please revise your diagnosis to address the feedback above.
CRITICAL: Use the EXACT metrics from "Original User Input" - do NOT use metrics from historical fixes.

Provide a complete revised response in the standard format.
"""
        
        response = self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": refinement_prompt},
            ],
            temperature=0.1,
        )
        
        raw_response = response.choices[0].message.content
        return self._parse_response(raw_response, previous_result.context)
    
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
