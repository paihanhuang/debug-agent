"""Hybrid Two-Stage Debug Agent.

Orchestrates the 3-stage diagnosis pipeline:
1. Stage 1: Anomaly Detection (LLM + CKG patterns)
2. Stage 2: Per-Anomaly Diagnosis (×N)
3. Stage 3: Synthesis into unified report
"""

from __future__ import annotations
import os
from typing import Any

from openai import OpenAI

from .models import (
    DetectedAnomaly,
    AnomalyDiagnosis,
    HybridDiagnosisResult,
)
from .anomaly_detector import AnomalyDetector
from .retriever import Retriever
from .vector_store import VectorStore
from .neo4j_store import Neo4jStore
from .fix_store import FixStore
from .embeddings import EmbeddingService
from .metric_parser import MetricParser, ExtractedMetrics


# Stage 2: Per-Anomaly Diagnosis Prompt
PER_ANOMALY_DIAGNOSIS_PROMPT = """You are diagnosing a SPECIFIC power anomaly.

## Anomaly Being Diagnosed:
Type: {anomaly_type}
Metric: {anomaly_metric}
Value: {anomaly_value}
Severity: {anomaly_severity}
Why Abnormal: {anomaly_why}

## User's Original Metrics (USE THESE EXACT VALUES):
{original_metrics}

## CKG Context for This Anomaly:
{ckg_context}

## Task
Diagnose THIS SPECIFIC anomaly. Provide:
1. The root cause for THIS anomaly
2. Causal chain with EXACT metrics from user input
3. Explanation of why this root cause causes this symptom
4. Suggested fixes

Use the EXACT metric values from the user's input.
If this is a VCORE floor issue, focus on MMDVFS.
If this is a VCORE ceiling issue, focus on CM/PowerHal/DDR.

Response format:
## Root Cause
[Single root cause for this anomaly]

## Causal Chain
[Chain with exact metrics: RootCause → Component → ... → Symptom]

## Explanation
[Why this root cause causes this specific anomaly]

## Suggested Fixes
- [Fix 1]
- [Fix 2]
"""


# Stage 3: Synthesis Prompt
SYNTHESIS_PROMPT = """You are synthesizing multiple anomaly diagnoses into a unified report.

## Detected Anomalies and Their Diagnoses:
{diagnoses}

## Original User Input:
{original_input}

## Task
Create a unified diagnosis report that:
1. Lists ALL root causes (numbered if multiple)
2. Shows if issues are independent or related
3. Includes causal chain for each with EXACT metrics
4. Provides fixes for EACH root cause

IMPORTANT: 
- If there are multiple independent root causes, clearly state "TWO INDEPENDENT ISSUES"
- Use EXACT metrics from user input
- For MMDVFS: state if ruled out (OPP4) or confirmed (OPP3 high)

Response format:
## Root Cause(s)
[List all root causes, numbered if multiple]

## Causal Chain
[Show each chain with exact metrics]
[If independent, mark as "Issue 1:", "Issue 2:", etc.]

## Diagnosis Summary
[Unified explanation of all issues]

## Recommended Actions
[Fixes for each root cause]
"""


class HybridTwoStageAgent:
    """Two-stage diagnosis agent: detect anomalies, then diagnose each.
    
    This agent uses a 3-stage pipeline:
    1. AnomalyDetector: LLM detects anomalies guided by CKG patterns
    2. Per-Anomaly: Each anomaly is diagnosed with focused CKG context  
    3. Synthesizer: All diagnoses are combined into unified report
    
    Benefits over single-stage:
    - Guaranteed detection of multiple independent issues
    - More focused CKG context per anomaly
    - Better causal chain accuracy
    """
    
    def __init__(
        self,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        fix_db_path: str = "fixes.db",
        openai_api_key: str | None = None,
        model: str = "gpt-4o",
    ):
        """Initialize the hybrid agent.
        
        Args:
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            fix_db_path: Path to SQLite fixes database
            openai_api_key: OpenAI API key
            model: LLM model to use
        """
        # Initialize LLM client
        self._api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._llm = OpenAI(api_key=self._api_key)
        self._model = model
        
        # Initialize stores
        self._neo4j_store = Neo4jStore(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
        )
        self._fix_store = FixStore(fix_db_path)
        self._embedding_service = EmbeddingService(api_key=self._api_key)
        self._vector_store = VectorStore(dimension=self._embedding_service.dimension)
        
        # Initialize components
        self._metric_parser = MetricParser()
        self._anomaly_detector = AnomalyDetector(
            llm_client=self._llm,
            neo4j_store=self._neo4j_store,
            model=self._model,
        )
        self._retriever = Retriever(
            vector_store=self._vector_store,
            neo4j_store=self._neo4j_store,
            fix_store=self._fix_store,
            embedding_service=self._embedding_service,
        )
        
        self._llm_calls = 0
    
    def connect(self) -> None:
        """Connect to Neo4j."""
        self._neo4j_store.connect()
    
    def close(self) -> None:
        """Close connections."""
        self._neo4j_store.close()
        self._fix_store.close()
    
    def __enter__(self) -> "HybridTwoStageAgent":
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def diagnose(self, user_input: str) -> HybridDiagnosisResult:
        """Run full three-stage diagnosis pipeline.
        
        Args:
            user_input: Raw user observation with metrics
            
        Returns:
            HybridDiagnosisResult with anomalies, diagnoses, and synthesized report
        """
        self._llm_calls = 0
        
        # Parse metrics
        metrics = self._metric_parser.parse(user_input)
        
        # ===== Stage 1: Detect Anomalies =====
        anomalies, has_dual_issue, summary = self._anomaly_detector.detect_with_details(
            user_input, metrics
        )
        self._llm_calls += 1
        
        if not anomalies:
            return HybridDiagnosisResult(
                anomalies=[],
                diagnoses=[],
                synthesized_report="No anomalies detected in the provided metrics.",
                has_dual_issue=False,
                llm_calls=self._llm_calls,
            )
        
        # ===== Stage 2: Diagnose Each Anomaly =====
        diagnoses = []
        for anomaly in anomalies:
            diagnosis = self._diagnose_single_anomaly(anomaly, metrics, user_input)
            diagnoses.append(diagnosis)
            self._llm_calls += 1
        
        # ===== Stage 3: Synthesize =====
        synthesized = self._synthesize(anomalies, diagnoses, user_input)
        self._llm_calls += 1
        
        return HybridDiagnosisResult(
            anomalies=anomalies,
            diagnoses=diagnoses,
            synthesized_report=synthesized,
            has_dual_issue=has_dual_issue or len(anomalies) > 1,
            llm_calls=self._llm_calls,
        )
    
    def _diagnose_single_anomaly(
        self,
        anomaly: DetectedAnomaly,
        metrics: ExtractedMetrics,
        original_input: str,
    ) -> AnomalyDiagnosis:
        """Diagnose a single anomaly with focused CKG context (Stage 2)."""
        
        # Get CKG context for this anomaly
        context = self._retriever.retrieve_for_anomaly(anomaly, metrics)
        
        # Build prompt
        prompt = PER_ANOMALY_DIAGNOSIS_PROMPT.format(
            anomaly_type=anomaly.type,
            anomaly_metric=anomaly.metric,
            anomaly_value=anomaly.value,
            anomaly_severity=anomaly.severity,
            anomaly_why=anomaly.why_abnormal,
            original_metrics=metrics.to_query_string(),
            ckg_context=context.to_prompt_context(),
        )
        
        # Call LLM
        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        
        # Parse response
        content = response.choices[0].message.content
        return self._parse_diagnosis(content, anomaly)
    
    def _parse_diagnosis(
        self,
        response: str,
        anomaly: DetectedAnomaly,
    ) -> AnomalyDiagnosis:
        """Parse LLM diagnosis response into AnomalyDiagnosis."""
        # Simple parsing by section headers
        root_cause = ""
        causal_chain = ""
        explanation = ""
        fixes = []
        
        current_section = None
        lines = response.split("\n")
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if "root cause" in line_lower and line.startswith("#"):
                current_section = "root_cause"
            elif "causal chain" in line_lower and line.startswith("#"):
                current_section = "causal_chain"
            elif "explanation" in line_lower and line.startswith("#"):
                current_section = "explanation"
            elif "suggested fix" in line_lower and line.startswith("#"):
                current_section = "fixes"
            elif current_section == "root_cause":
                root_cause += line + "\n"
            elif current_section == "causal_chain":
                causal_chain += line + "\n"
            elif current_section == "explanation":
                explanation += line + "\n"
            elif current_section == "fixes":
                if line.strip().startswith("-"):
                    fixes.append(line.strip()[1:].strip())
        
        return AnomalyDiagnosis(
            anomaly=anomaly,
            root_cause=root_cause.strip(),
            causal_chain=causal_chain.strip(),
            explanation=explanation.strip(),
            suggested_fixes=fixes,
        )
    
    def _synthesize(
        self,
        anomalies: list[DetectedAnomaly],
        diagnoses: list[AnomalyDiagnosis],
        original_input: str,
    ) -> str:
        """Synthesize multiple diagnoses into unified report (Stage 3)."""
        
        # Format diagnoses for prompt
        diag_text = ""
        for i, diag in enumerate(diagnoses, 1):
            diag_text += f"""
### Anomaly {i}: {diag.anomaly.type}
Metric: {diag.anomaly.metric} = {diag.anomaly.value}
Root Cause: {diag.root_cause}
Causal Chain: {diag.causal_chain}
"""
        
        # Build prompt
        prompt = SYNTHESIS_PROMPT.format(
            diagnoses=diag_text,
            original_input=original_input,
        )
        
        # Call LLM
        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        
        return response.choices[0].message.content
    
    def load_ckg(self, ckg_data: dict[str, Any]) -> None:
        """Load CKG data into Neo4j and vector store.
        
        Args:
            ckg_data: CKG dictionary with entities and relations
        """
        # Load into Neo4j
        self._neo4j_store.load_ckg_from_dict(ckg_data)
        
        # Index entities in vector store
        for entity in ckg_data.get("entities", []):
            text = f"{entity['label']}: {entity.get('description', '')}"
            # Generate embedding
            embedding = self._embedding_service.embed_text(text)
            self._vector_store.add(
                entity_id=entity["id"],
                embedding=embedding,
                metadata={"type": entity["type"], "label": entity["label"]},
            )
    
    def add_historical_fix(
        self,
        case_id: str,
        root_cause: str,
        symptom_summary: str,
        metrics: dict[str, Any],
        fix_description: str,
        resolution_notes: str = "",
    ) -> None:
        """Add a historical fix to the database."""
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
