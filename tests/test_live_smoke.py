"""Live-path smoke test — runs ONLY when real API keys are present.

The deterministic suite proves the logic offline. This guards the *live* wiring
(real LLM provider + real Linear transport) end to end when keys exist, so the
production path isn't entirely unexercised. It is skipped in normal CI."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("LINEAR_API_KEY")
        and (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
    ),
    reason="live keys not configured (LINEAR_API_KEY + an LLM key)",
)


def test_live_read_only_instruction():
    from praxis.build import build_agent
    from praxis.config import Settings
    from praxis.memory import Memory
    from praxis.models import ExecutionStatus

    agent = build_agent(Settings(), offline=False, memory=Memory(":memory:"))
    report = agent.run("List all teams")  # read-only: safe against a real workspace
    assert report.status in (ExecutionStatus.SUCCESS, ExecutionStatus.PARTIAL)
    assert report.total_api_calls >= 1
    assert report.execution_id is not None
