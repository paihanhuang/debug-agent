from __future__ import annotations

import os
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.agent import DebugAgent
from graphrag.metric_parser import ExtractedMetrics
from graphrag.retriever import DiagnosisContext


class _NoLLM:
    def __init__(self):
        self.called = False

    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                raise AssertionError("LLM should not be called in abstain mode")


def _make_context(*, with_root_causes: bool, with_chains: bool) -> DiagnosisContext:
    # Minimal synthetic context; no Neo4j needed.
    metrics = ExtractedMetrics(raw_text="VCORE 725mV at 82.6%")
    root_causes = []
    causal_chains = []
    if with_root_causes:
        # EntityNode-like object with required fields used downstream
        root_causes = [type("N", (), {"id": "rc1", "label": "CM", "description": ""})()]
    if with_chains:
        causal_chains = [[type("N", (), {"id": "n1", "label": "CM", "description": ""})()]]
    return DiagnosisContext(
        metrics=metrics,
        matched_entities=[],
        root_causes=root_causes,
        causal_chains=causal_chains,
        subgraph={},
        relevant_fixes=[],
    )


def test_abstain_gate_triggers_and_skips_llm(monkeypatch):
    monkeypatch.setenv("ENABLE_ABSTAIN_GATE", "1")
    monkeypatch.setenv("ABSTAIN_MIN_ROOT_CAUSES", "1")
    monkeypatch.setenv("ABSTAIN_MIN_CHAINS", "1")

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _make_context(with_root_causes=False, with_chains=False)})()
    agent._llm_client = _NoLLM()

    res = DebugAgent.diagnose(agent, "unseen anomaly input")
    assert res.root_cause == "ABSTAIN"
    assert "## Mode" in res.raw_response
    assert "ABSTAIN" in res.raw_response
    assert "Insufficient CKG coverage" in res.raw_response


def test_abstain_gate_does_not_trigger_when_coverage_sufficient(monkeypatch):
    monkeypatch.setenv("ENABLE_ABSTAIN_GATE", "1")
    monkeypatch.setenv("ABSTAIN_MIN_ROOT_CAUSES", "1")
    monkeypatch.setenv("ABSTAIN_MIN_CHAINS", "1")

    class _LLM:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    # Return minimal structure expected by DebugAgent
                    return type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "## Root Cause\nX\n## Causal Chain\nY\n## Diagnosis\nZ\n## Historical Fixes (for reference)\n- None\n"})()})()]})()

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _make_context(with_root_causes=True, with_chains=True)})()
    agent._llm_client = _LLM()
    # Stub methods used after LLM call to keep unit test hermetic
    agent._build_prompt = lambda input_text, context: "p"
    agent._ensure_traversal_nodes = lambda r, c: r
    agent._rewrite_report_to_include_required_metrics = lambda r, m: r
    agent._parse_response = lambda r, c: type("DR", (), {"root_cause": "X", "causal_chain": "Y", "diagnosis": "Z", "historical_fixes": [], "raw_response": r, "context": c})()
    agent._llm_model = "gpt-4o"

    res = DebugAgent.diagnose(agent, "seen anomaly input")
    assert res.root_cause == "X"

