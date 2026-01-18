from __future__ import annotations

import os


class _FakeChatCompletions:
    def __init__(self, parent: "_FakeOpenAI"):
        self._p = parent

    def create(self, model, messages, temperature=0.1, response_format=None, max_tokens=None):
        # Record calls for assertions
        self._p.calls.append({"model": model, "messages": messages, "temperature": temperature})

        # 1st call: draft
        if len(self._p.calls) == 1:
            class _Msg:
                # Default fake behavior returns a rewritten report that includes required metric tokens.
                # This matches how we use the helper in unit tests (single editor call).
                content = (
                    "## Root Cause\n...\n"
                    "## Causal Chain\nIncludes DDR5460 3.54% and DDR6370 26.13% and CPU 2700MHz.\n"
                    "## Diagnosis\n...\n"
                    "## Historical Fixes (for reference)\n- None\n"
                )

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

        raise AssertionError("Unexpected extra LLM calls")


class _FakeOpenAI:
    def __init__(self):
        self.calls = []
        self.chat = type("_Chat", (), {"completions": _FakeChatCompletions(self)})()


def test_editor_default_on_calls_second_pass_when_metrics_missing(monkeypatch):
    # Default is enabled; ensure env doesn't disable it.
    monkeypatch.delenv("ENABLE_REPORT_METRIC_REWRITE", raising=False)

    from graphrag.agent import DebugAgent
    from graphrag.metric_parser import ExtractedMetrics
    from graphrag.retriever import DiagnosisContext

    fake_client = _FakeOpenAI()

    # Build a fake context with required metrics present.
    metrics = ExtractedMetrics(ddr5460_percent=3.54, ddr6370_percent=26.13, cpu_big_mhz=2700, raw_text="")
    ctx = DiagnosisContext(metrics=metrics, matched_entities=[], root_causes=[], causal_chains=[], subgraph={}, relevant_fixes=[])

    agent = DebugAgent(openai_api_key="x", llm_client=fake_client)

    # Call the internal helper to avoid Neo4j/FAISS dependencies.
    draft = "## Root Cause\n...\n## Causal Chain\n...\n## Diagnosis\n...\n## Historical Fixes (for reference)\n- None\n"
    out = agent._rewrite_report_to_include_required_metrics(draft, ctx.metrics)  # type: ignore[attr-defined]
    assert "DDR5460" in out and "DDR6370" in out and "MHz" in out
    assert len(fake_client.calls) == 1  # only editor call in this direct helper call


def test_editor_flag_off_skips(monkeypatch):
    monkeypatch.setenv("ENABLE_REPORT_METRIC_REWRITE", "0")

    from graphrag.agent import DebugAgent
    from graphrag.metric_parser import ExtractedMetrics

    fake_client = _FakeOpenAI()
    agent = DebugAgent(openai_api_key="x", llm_client=fake_client)
    metrics = ExtractedMetrics(ddr5460_percent=3.54, raw_text="")

    out = agent._rewrite_report_to_include_required_metrics("draft", metrics)  # type: ignore[attr-defined]
    assert out == "draft"
    assert len(fake_client.calls) == 0


def test_editor_skip_when_already_contains(monkeypatch):
    monkeypatch.delenv("ENABLE_REPORT_METRIC_REWRITE", raising=False)

    from graphrag.agent import DebugAgent
    from graphrag.metric_parser import ExtractedMetrics

    fake_client = _FakeOpenAI()
    agent = DebugAgent(openai_api_key="x", llm_client=fake_client)

    metrics = ExtractedMetrics(ddr5460_percent=3.54, ddr6370_percent=26.13, cpu_big_mhz=2700, raw_text="")
    draft = "DDR5460 3.54% DDR6370 26.13% CPU 2700MHz"
    out = agent._rewrite_report_to_include_required_metrics(draft, metrics)  # type: ignore[attr-defined]
    assert out == draft
    assert len(fake_client.calls) == 0


def test_editor_prompt_contract_includes_numeric_guardrail(monkeypatch):
    monkeypatch.delenv("ENABLE_REPORT_METRIC_REWRITE", raising=False)

    from graphrag.agent import DebugAgent
    from graphrag.metric_parser import ExtractedMetrics

    fake_client = _FakeOpenAI()
    agent = DebugAgent(openai_api_key="x", llm_client=fake_client)

    metrics = ExtractedMetrics(ddr5460_percent=3.54, raw_text="")
    _ = agent._rewrite_report_to_include_required_metrics("draft", metrics)  # type: ignore[attr-defined]
    assert len(fake_client.calls) == 1
    messages = fake_client.calls[0]["messages"]
    full = "\n".join(m["content"] for m in messages)
    assert "do not change any numeric values" in full.lower()
    assert "DDR5460" in full

