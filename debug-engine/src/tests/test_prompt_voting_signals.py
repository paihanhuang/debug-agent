from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.agent import DebugAgent


def test_build_prompt_includes_ddr_voting_signals() -> None:
    agent = DebugAgent.__new__(DebugAgent)
    ctx = type("C", (), {"to_prompt_context": lambda self: "CTX"})()

    prompt = agent._build_prompt("DDR voting shows SW_REQ2 and SW_REQ3 activity.", ctx)  # type: ignore[arg-type]
    assert "## DDR Voting Signals (from user input)" in prompt
    assert "SW_REQ2" in prompt and "SW_REQ3" in prompt


def test_build_prompt_mentions_no_ddr_voting_when_absent() -> None:
    agent = DebugAgent.__new__(DebugAgent)
    ctx = type("C", (), {"to_prompt_context": lambda self: "CTX"})()
    prompt = agent._build_prompt("No DDR voting data available.", ctx)  # type: ignore[arg-type]
    assert "No DDR voting data available." in prompt

