"""Debug agent - main orchestrator for LLM-based diagnosis."""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
import json

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

STRUCTURED_SYSTEM_PROMPT = """You are an expert power debugging assistant for mobile devices.

You MUST return ONLY valid JSON (no markdown, no extra text).

Your output must separate:
- Observations: facts copied verbatim from the user input (no invented numbers)
- CKG-grounded facts: statements supported by CKG traversal nodes / causal chain context
- Hypotheses: explicitly marked as unverified, and must not invent new metrics
- Conclusion: root cause + confidence, justified only by observations + CKG-grounded facts

Do not fabricate metrics or thresholds. Treat Chinese/English as equivalent (拉檔 = frequency throttling).
"""

STRUCTURED_RESPONSE_SCHEMA_PROMPT = """Given the following user observation and CKG context, produce a JSON object with this structure:

{{
  "observations": [{{"text": "verbatim fact", "source": "input"}}],
  "ckg_grounded_facts": [{{"text": "fact", "source": "ckg", "nodes": ["node_label_1", "node_label_2"]}}],
  "hypotheses": [{{"text": "hypothesis", "confidence": "low|medium|high", "why": ["..."], "what_would_confirm": ["..."]}}],
  "conclusion": {{"root_cause": "CM|PowerHal|MMDVFS|UNKNOWN|...", "confidence": "low|medium|high", "justification": ["..."]}},
  "next_steps": ["..."],
  "historical_fixes": [{{"case_id": "id", "fix": "fix text"}}]
}}

Rules:
- Observations MUST be grounded in the input_text (no new numbers).
- If CKG traversal nodes are provided, ckg_grounded_facts MUST reference them via the nodes field.
- If CKG grounding is weak, set conclusion.root_cause to UNKNOWN and confidence to low.
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

LOW_COVERAGE_VERIFIER_SYSTEM_PROMPT = """You are a strict verifier for power debugging reports.

Your task:
- Check whether the report makes claims not supported by (1) the user's observations or (2) the provided CKG context.
- If unsupported claims exist, either rewrite to remove/downgrade them, or return ABSTAIN when a grounded diagnosis isn't possible.

Rules:
- Do NOT invent metrics, thresholds, or new facts.
- If the report asserts a specific root cause but coverage indicates no grounded root causes/chains, you MUST set status=ABSTAIN or rewrite conclusion to UNKNOWN + hypotheses.
- Return ONLY valid JSON (no markdown).

Output JSON schema:
{
  "status": "OK|NEEDS_REWRITE|ABSTAIN",
  "problems": [{"type":"...", "detail":"..."}],
  "rewritten_report": "..."   // required when status=NEEDS_REWRITE
}
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

        # Optional: abstain gate to prevent hallucination when CKG coverage is insufficient.
        if self._abstain_gate_enabled():
            coverage = self._compute_coverage(context)
            if self._should_abstain(coverage):
                raw = self._format_abstain_report(input_text=input_text, context=context, coverage=coverage)
                return DiagnosisResult(
                    root_cause="ABSTAIN",
                    causal_chain="",
                    diagnosis="",
                    historical_fixes=[],
                    raw_response=raw,
                    context=context,
                )
        else:
            coverage = None

        # Optional: structured output mode to separate Observations vs Hypotheses.
        if self._obs_hyp_schema_enabled():
            res = self._diagnose_structured(input_text=input_text, context=context)
            cov = coverage or self._compute_coverage(context)
            return self._maybe_verify_low_coverage(input_text=input_text, context=context, coverage=cov, result=res)
        
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

        # Optional verifier pass only when coverage is low.
        cov = coverage or self._compute_coverage(context)
        raw_response = self._maybe_verify_low_coverage_raw(
            input_text=input_text,
            context=context,
            coverage=cov,
            report=raw_response,
        )

        # If verifier converted the report into an abstain response, return immediately.
        if raw_response.lstrip().startswith("## Mode") and "\nABSTAIN" in raw_response[:80]:
            return DiagnosisResult(
                root_cause="ABSTAIN",
                causal_chain="",
                diagnosis="",
                historical_fixes=[],
                raw_response=raw_response,
                context=context,
            )
        
        # Step 4: Parse response
        return self._parse_response(raw_response, context)

    def _obs_hyp_schema_enabled(self) -> bool:
        v = os.getenv("ENABLE_OBS_HYP_SCHEMA")
        if v is None:
            return False  # default OFF to preserve current behavior
        return v.strip().lower() not in {"0", "false", "no", "off"}

    def _diagnose_structured(self, *, input_text: str, context: DiagnosisContext) -> DiagnosisResult:
        prompt = self._build_structured_prompt(input_text=input_text, context=context)
        try:
            resp = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw_json = resp.choices[0].message.content or "{}"
            obj = json.loads(raw_json)
        except Exception:
            # Fallback to legacy flow if structured mode fails for any reason.
            legacy = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_prompt(input_text, context)},
                ],
                temperature=0.1,
            )
            raw = legacy.choices[0].message.content
            raw = self._ensure_traversal_nodes(raw, context)
            raw = self._rewrite_report_to_include_required_metrics(raw, context.metrics)
            return self._parse_response(raw, context)

        # Validate minimum structure
        observations = obj.get("observations", []) or []
        hypotheses = obj.get("hypotheses", []) or []
        conclusion = obj.get("conclusion", {}) or {}
        ckg_facts = obj.get("ckg_grounded_facts", []) or []
        next_steps = obj.get("next_steps", []) or []
        historical = obj.get("historical_fixes", []) or []

        md = self._render_structured_markdown(
            observations=observations,
            ckg_grounded_facts=ckg_facts,
            hypotheses=hypotheses,
            conclusion=conclusion,
            next_steps=next_steps,
            historical_fixes=historical,
        )

        md = self._ensure_traversal_nodes(md, context)
        md = self._rewrite_report_to_include_required_metrics(md, context.metrics)

        root_cause = str(conclusion.get("root_cause", "")).strip() or "UNKNOWN"
        diagnosis = "\n".join([str(x) for x in conclusion.get("justification", []) or []]).strip()
        causal_chain = "\n".join([str(x.get("text", "")) for x in ckg_facts if isinstance(x, dict)]).strip()
        hist_lines: list[str] = []
        for h in historical:
            if isinstance(h, dict):
                txt = h.get("fix") or ""
                cid = h.get("case_id") or ""
                if cid and txt:
                    hist_lines.append(f"Case {cid}: {txt}")
                elif txt:
                    hist_lines.append(str(txt))
            elif isinstance(h, str):
                hist_lines.append(h)

        return DiagnosisResult(
            root_cause=root_cause,
            causal_chain=causal_chain,
            diagnosis=diagnosis,
            historical_fixes=hist_lines,
            raw_response=md,
            context=context,
        )

    def _build_structured_prompt(self, *, input_text: str, context: DiagnosisContext) -> str:
        lines = [
            STRUCTURED_RESPONSE_SCHEMA_PROMPT,
            "",
            "input_text:",
            input_text,
            "",
            "ckg_context:",
            context.to_prompt_context(),
        ]
        return "\n".join(lines)

    def _render_structured_markdown(
        self,
        *,
        observations: list[Any],
        ckg_grounded_facts: list[Any],
        hypotheses: list[Any],
        conclusion: dict[str, Any],
        next_steps: list[Any],
        historical_fixes: list[Any],
    ) -> str:
        lines: list[str] = []

        # Explicit separation sections
        lines.append("## Observations")
        if observations:
            for o in observations:
                if isinstance(o, dict):
                    t = str(o.get("text", "")).strip()
                else:
                    t = str(o).strip()
                if t:
                    lines.append(f"- {t}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## CKG-Grounded Facts")
        if ckg_grounded_facts:
            for f in ckg_grounded_facts:
                if isinstance(f, dict):
                    t = str(f.get("text", "")).strip()
                    nodes = f.get("nodes") if isinstance(f.get("nodes"), list) else []
                    if nodes:
                        t = f"{t} (nodes: {', '.join(str(n) for n in nodes)})"
                else:
                    t = str(f).strip()
                if t:
                    lines.append(f"- {t}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Hypotheses (Unverified)")
        if hypotheses:
            for h in hypotheses:
                if isinstance(h, dict):
                    t = str(h.get("text", "")).strip()
                    conf = str(h.get("confidence", "")).strip()
                    if conf:
                        t = f"[{conf}] {t}"
                else:
                    t = str(h).strip()
                if t:
                    lines.append(f"- {t}")
        else:
            lines.append("- (none)")
        lines.append("")

        # Preserve legacy headings for downstream consumers
        lines.append("## Root Cause")
        rc = str(conclusion.get("root_cause", "")).strip() or "UNKNOWN"
        conf = str(conclusion.get("confidence", "")).strip()
        lines.append(f"- {rc}" + (f" (confidence: {conf})" if conf else ""))
        lines.append("")

        lines.append("## Causal Chain")
        if ckg_grounded_facts:
            for f in ckg_grounded_facts:
                if isinstance(f, dict):
                    t = str(f.get("text", "")).strip()
                else:
                    t = str(f).strip()
                if t:
                    lines.append(f"- {t}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Diagnosis")
        just = conclusion.get("justification", []) or []
        if isinstance(just, list) and just:
            for j in just:
                lines.append(f"- {str(j).strip()}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Next Steps")
        if next_steps:
            for s in next_steps:
                st = str(s).strip()
                if st:
                    lines.append(f"- {st}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Historical Fixes (for reference)")
        if historical_fixes:
            for h in historical_fixes:
                if isinstance(h, dict):
                    cid = str(h.get("case_id", "")).strip()
                    fx = str(h.get("fix", "")).strip()
                    if cid and fx:
                        lines.append(f"- Case {cid}: {fx}")
                    elif fx:
                        lines.append(f"- {fx}")
                else:
                    ht = str(h).strip()
                    if ht:
                        lines.append(f"- {ht}")
        else:
            lines.append("- No relevant historical fixes found")

        return "\n".join(lines).strip() + "\n"

    def _abstain_gate_enabled(self) -> bool:
        v = os.getenv("ENABLE_ABSTAIN_GATE")
        if v is None:
            return False  # default OFF to preserve current behavior
        return v.strip().lower() not in {"0", "false", "no", "off"}

    def _low_coverage_verifier_enabled(self) -> bool:
        v = os.getenv("ENABLE_LOW_COVERAGE_VERIFIER")
        if v is None:
            return False  # default OFF to preserve current behavior
        return v.strip().lower() not in {"0", "false", "no", "off"}

    @dataclass(frozen=True)
    class CoverageReport:
        matched_entities_count: int
        root_causes_count: int
        causal_chains_count: int
        relevant_fixes_count: int
        required_nodes_count: int

        def to_dict(self) -> dict[str, Any]:
            return {
                "matched_entities_count": self.matched_entities_count,
                "root_causes_count": self.root_causes_count,
                "causal_chains_count": self.causal_chains_count,
                "relevant_fixes_count": self.relevant_fixes_count,
                "required_nodes_count": self.required_nodes_count,
            }

    def _compute_coverage(self, context: DiagnosisContext) -> "DebugAgent.CoverageReport":
        required_nodes: list[str] = []
        for chain in context.causal_chains or []:
            for node in chain:
                if node.label not in required_nodes:
                    required_nodes.append(node.label)
        return DebugAgent.CoverageReport(
            matched_entities_count=len(context.matched_entities or []),
            root_causes_count=len(context.root_causes or []),
            causal_chains_count=len(context.causal_chains or []),
            relevant_fixes_count=len(context.relevant_fixes or []),
            required_nodes_count=len(required_nodes),
        )

    def _should_abstain(self, cov: "DebugAgent.CoverageReport") -> bool:
        min_rc = int(os.getenv("ABSTAIN_MIN_ROOT_CAUSES", "1"))
        min_chains = int(os.getenv("ABSTAIN_MIN_CHAINS", "1"))
        if cov.root_causes_count < min_rc:
            return True
        if cov.causal_chains_count < min_chains:
            return True
        return False

    def _is_low_coverage(self, cov: "DebugAgent.CoverageReport") -> bool:
        # Default trigger conditions (configurable via env)
        min_required_nodes = int(os.getenv("MIN_REQUIRED_NODES", "3"))
        if cov.root_causes_count == 0:
            return True
        if cov.causal_chains_count == 0:
            return True
        if cov.matched_entities_count == 0:
            return True
        if cov.required_nodes_count < min_required_nodes:
            return True
        return False

    def _maybe_verify_low_coverage_raw(
        self,
        *,
        input_text: str,
        context: DiagnosisContext,
        coverage: "DebugAgent.CoverageReport",
        report: str,
    ) -> str:
        if not self._low_coverage_verifier_enabled():
            return report
        if not self._is_low_coverage(coverage):
            return report

        payload = self._run_low_coverage_verifier(input_text=input_text, context=context, coverage=coverage, report=report)
        status = str(payload.get("status", "")).strip().upper()
        if status == "OK":
            return report
        if status == "ABSTAIN":
            return self._format_abstain_report(input_text=input_text, context=context, coverage=coverage)
        if status == "NEEDS_REWRITE":
            rewritten = str(payload.get("rewritten_report", "") or "").strip()
            if not rewritten:
                return report
            # Re-apply invariants
            rewritten = self._ensure_traversal_nodes(rewritten, context)
            rewritten = self._rewrite_report_to_include_required_metrics(rewritten, context.metrics)
            return rewritten
        return report

    def _maybe_verify_low_coverage(
        self,
        *,
        input_text: str,
        context: DiagnosisContext,
        coverage: "DebugAgent.CoverageReport",
        result: DiagnosisResult,
    ) -> DiagnosisResult:
        """Verifier wrapper for already-parsed DiagnosisResult (structured mode path)."""
        verified_raw = self._maybe_verify_low_coverage_raw(
            input_text=input_text,
            context=context,
            coverage=coverage,
            report=result.raw_response,
        )
        if verified_raw == result.raw_response:
            return result
        # If verifier produced ABSTAIN markdown, convert to ABSTAIN result
        if "## Mode" in verified_raw and "\nABSTAIN" in verified_raw:
            return DiagnosisResult(
                root_cause="ABSTAIN",
                causal_chain="",
                diagnosis="",
                historical_fixes=[],
                raw_response=verified_raw,
                context=context,
            )
        return self._parse_response(verified_raw, context)

    def _run_low_coverage_verifier(
        self,
        *,
        input_text: str,
        context: DiagnosisContext,
        coverage: "DebugAgent.CoverageReport",
        report: str,
    ) -> dict[str, Any]:
        required_nodes = self._collect_required_nodes(context)
        prompt = "\n".join(
            [
                "User observations (verbatim):",
                input_text.strip(),
                "",
                "Coverage:",
                json.dumps(coverage.to_dict(), indent=2, ensure_ascii=False),
                "",
                "CKG traversal nodes:",
                "\n".join(f"- {n}" for n in required_nodes) if required_nodes else "- (none)",
                "",
                "CKG context summary:",
                context.to_prompt_context(),
                "",
                "Draft report to verify:",
                report.strip(),
            ]
        )

        try:
            resp = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": LOW_COVERAGE_VERIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or "{}"
            obj = json.loads(content)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _format_abstain_report(
        self,
        *,
        input_text: str,
        context: DiagnosisContext,
        coverage: "DebugAgent.CoverageReport",
    ) -> str:
        # Keep this human-readable but also machine-parsable.
        payload = {
            "mode": "ABSTAIN",
            "reason": "Insufficient CKG coverage to support grounded diagnosis",
            "coverage": coverage.to_dict(),
            "observations": (input_text or "").strip().splitlines(),
            "missing_knowledge": [
                "CKG grounding missing: root causes and/or causal chains were not found for this input.",
                "Provide DDR voting signals (SW_REQ2/SW_REQ3) for the same window if available.",
                "Provide CPU ceiling breakdown by cluster (big/mid/small) and their usage ratios.",
                "Provide MMDVFS OPP level and its usage distribution.",
            ],
            "action": {
                "next_step": "REQUEST_MORE_DATA_OR_AUGMENT_CKG",
                "suggested_ckg_augment_inputs": ["raw_report", "raw_debug_query", "agent_output", "judge_feedback"],
            },
        }

        # Also include any extracted metrics as a convenience.
        try:
            payload["parsed_metrics"] = context.metrics.to_query_string().splitlines()  # type: ignore[attr-defined]
        except Exception:
            pass

        lines: list[str] = []
        lines.append("## Mode")
        lines.append("ABSTAIN")
        lines.append("")
        lines.append("## Reason")
        lines.append(payload["reason"])
        lines.append("")
        lines.append("## Coverage")
        lines.append(json.dumps(payload["coverage"], indent=2, ensure_ascii=False))
        lines.append("")
        lines.append("## Observations (verbatim input)")
        if payload["observations"]:
            for l in payload["observations"]:
                lines.append(f"- {l}")
        else:
            lines.append("- (empty)")
        lines.append("")
        lines.append("## Missing Knowledge / Next Data Needed")
        for item in payload["missing_knowledge"]:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## Action")
        lines.append(json.dumps(payload["action"], indent=2, ensure_ascii=False))
        return "\n".join(lines).strip() + "\n"

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
