from __future__ import annotations

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.agent import DebugAgent
from graphrag.metric_parser import ExtractedMetrics
from graphrag.retriever import DiagnosisContext


class _LLMJson:
    def __init__(self, payload: dict):
        self.payload = payload
        self.last_kwargs = None

    class chat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                raise NotImplementedError

    def bind(self):
        parent = self

        class _Chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    parent.last_kwargs = kwargs
                    content = json.dumps(parent.payload, ensure_ascii=False)
                    return type(
                        "Resp",
                        (),
                        {"choices": [type("C", (), {"message": type("M", (), {"content": content})()})()]},
                    )()

        self.chat = _Chat
        return self


def _ctx() -> DiagnosisContext:
    metrics = ExtractedMetrics(raw_text="VCORE 725mV at 82.6%")
    root_causes = [type("N", (), {"id": "rc1", "label": "CM", "description": ""})()]
    causal_chains = [[type("N", (), {"id": "n1", "label": "CM", "description": ""})()]]
    return DiagnosisContext(
        metrics=metrics,
        matched_entities=[],
        root_causes=root_causes,
        causal_chains=causal_chains,
        subgraph={},
        relevant_fixes=[],
    )


def test_structured_schema_renders_sections_and_calls_json_response_format(monkeypatch):
    monkeypatch.setenv("ENABLE_OBS_HYP_SCHEMA", "1")
    monkeypatch.setenv("ENABLE_REPORT_METRIC_REWRITE", "0")  # keep unit test single-pass

    payload = {
        "observations": [{"text": "VCORE 725mV usage is at 82.6%", "source": "input"}],
        "ckg_grounded_facts": [{"text": "SW_REQ2 indicates CM involvement", "source": "ckg", "nodes": ["SW_REQ2", "CM"]}],
        "hypotheses": [{"text": "CM voting is raising VCORE ceiling", "confidence": "medium", "why": ["x"], "what_would_confirm": ["y"]}],
        "conclusion": {"root_cause": "CM", "confidence": "medium", "justification": ["Based on observed VCORE and CKG facts."]},
        "next_steps": ["Collect DDR voting SW_REQ2/SW_REQ3 signals."],
        "historical_fixes": [{"case_id": "fix_1", "fix": "Adjust CM policy."}],
    }
    llm = _LLMJson(payload).bind()

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _ctx()})()
    agent._llm_client = llm
    agent._llm_model = "gpt-4o"
    # Ensure traversal-node postprocess doesn't call LLM for this test
    agent._collect_required_nodes = lambda ctx: []

    res = DebugAgent.diagnose(agent, "VCORE 725mV usage is at 82.6%")
    assert res.root_cause == "CM"
    assert "## Observations" in res.raw_response
    assert "## Hypotheses (Unverified)" in res.raw_response
    assert "## Root Cause" in res.raw_response
    assert "## Historical Fixes (for reference)" in res.raw_response

    assert llm.last_kwargs is not None
    assert llm.last_kwargs.get("response_format") == {"type": "json_object"}

