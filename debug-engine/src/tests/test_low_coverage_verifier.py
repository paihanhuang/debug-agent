from __future__ import annotations

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.agent import DebugAgent, SYSTEM_PROMPT, LOW_COVERAGE_VERIFIER_SYSTEM_PROMPT
from graphrag.metric_parser import ExtractedMetrics
from graphrag.retriever import DiagnosisContext


class _LLMSeq:
    """Simple LLM stub that returns a sequence of contents and records call kwargs."""

    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls: list[dict] = []

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
                    parent.calls.append(kwargs)
                    if not parent.contents:
                        raise AssertionError("No more stubbed LLM responses")
                    content = parent.contents.pop(0)
                    return type(
                        "Resp",
                        (),
                        {"choices": [type("C", (), {"message": type("M", (), {"content": content})()})()]},
                    )()

        self.chat = _Chat
        return self


def _ctx(*, roots: int, chains: int, matched: int) -> DiagnosisContext:
    metrics = ExtractedMetrics(raw_text="VCORE 725mV at 82.6%")
    matched_entities = [type("S", (), {"entity_id": f"e{i}", "score": 0.1})() for i in range(matched)]
    root_causes = [type("N", (), {"id": f"rc{i}", "label": "CM", "description": ""})() for i in range(roots)]
    causal_chains = []
    for _ in range(chains):
        causal_chains.append([type("N", (), {"id": "n1", "label": "CM", "description": ""})()])
    return DiagnosisContext(
        metrics=metrics,
        matched_entities=matched_entities,
        root_causes=root_causes,
        causal_chains=causal_chains,
        subgraph={},
        relevant_fixes=[],
    )


def test_verifier_runs_on_low_coverage_and_can_force_abstain(monkeypatch):
    monkeypatch.setenv("ENABLE_LOW_COVERAGE_VERIFIER", "1")
    monkeypatch.setenv("MIN_REQUIRED_NODES", "3")
    monkeypatch.delenv("ENABLE_ABSTAIN_GATE", raising=False)

    # First LLM call: draft report. Second LLM call: verifier JSON -> ABSTAIN.
    llm = _LLMSeq(
        [
            "## Root Cause\n- CM\n\n## Causal Chain\n- (unknown)\n\n## Diagnosis\n- (guess)\n\n## Historical Fixes (for reference)\n- None\n",
            json.dumps({"status": "ABSTAIN", "problems": [{"type": "LOW_COVERAGE", "detail": "no chains"}]}, ensure_ascii=False),
        ]
    ).bind()

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _ctx(roots=0, chains=0, matched=0)})()
    agent._llm_client = llm
    agent._llm_model = "gpt-4o"
    agent._build_prompt = lambda input_text, context: "p"
    agent._ensure_traversal_nodes = lambda r, c: r
    agent._rewrite_report_to_include_required_metrics = lambda r, m: r

    res = DebugAgent.diagnose(agent, "unseen input")
    assert res.root_cause == "ABSTAIN"
    assert "## Mode" in res.raw_response and "ABSTAIN" in res.raw_response

    # verifier call should request json_object format
    assert len(llm.calls) == 2
    assert llm.calls[1].get("response_format") == {"type": "json_object"}
    assert llm.calls[1]["messages"][0]["content"] == LOW_COVERAGE_VERIFIER_SYSTEM_PROMPT


def test_verifier_rewrites_when_needed(monkeypatch):
    monkeypatch.setenv("ENABLE_LOW_COVERAGE_VERIFIER", "1")
    monkeypatch.setenv("MIN_REQUIRED_NODES", "3")
    monkeypatch.delenv("ENABLE_ABSTAIN_GATE", raising=False)

    rewritten = "## Root Cause\nCM\n\n## Causal Chain\nCM -> VCORE\n\n## Diagnosis\nGrounded.\n\n## Historical Fixes (for reference)\n- None\n"
    llm = _LLMSeq(
        [
            "## Root Cause\n- ???\n\n## Causal Chain\n- ???\n\n## Diagnosis\n- ???\n\n## Historical Fixes (for reference)\n- None\n",
            json.dumps({"status": "NEEDS_REWRITE", "problems": [], "rewritten_report": rewritten}, ensure_ascii=False),
        ]
    ).bind()

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _ctx(roots=0, chains=0, matched=0)})()
    agent._llm_client = llm
    agent._llm_model = "gpt-4o"
    agent._build_prompt = lambda input_text, context: "p"
    agent._ensure_traversal_nodes = lambda r, c: r
    agent._rewrite_report_to_include_required_metrics = lambda r, m: r

    res = DebugAgent.diagnose(agent, "unseen input")
    assert res.root_cause.strip() == "CM"
    assert "Grounded." in res.raw_response


def test_verifier_skips_when_coverage_sufficient(monkeypatch):
    monkeypatch.setenv("ENABLE_LOW_COVERAGE_VERIFIER", "1")
    monkeypatch.setenv("MIN_REQUIRED_NODES", "1")
    monkeypatch.delenv("ENABLE_ABSTAIN_GATE", raising=False)

    llm = _LLMSeq(
        [
            "## Root Cause\nCM\n\n## Causal Chain\nCM -> VCORE\n\n## Diagnosis\nok\n\n## Historical Fixes (for reference)\n- None\n",
        ]
    ).bind()

    agent = DebugAgent.__new__(DebugAgent)
    agent._retriever = type("R", (), {"retrieve": lambda self, t: _ctx(roots=1, chains=1, matched=1)})()
    agent._llm_client = llm
    agent._llm_model = "gpt-4o"
    agent._build_prompt = lambda input_text, context: "p"
    agent._ensure_traversal_nodes = lambda r, c: r
    agent._rewrite_report_to_include_required_metrics = lambda r, m: r

    res = DebugAgent.diagnose(agent, "seen input")
    assert res.root_cause.strip() == "CM"
    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT

