"""Assemble a ready-to-run PraxisAgent from settings.

`offline=True` wires the deterministic ScriptedLLM + an in-process FakeLinear so
the full loop runs with no network and no API keys (used by tests and
`praxis demo --offline`). Otherwise it builds the configured live LLM provider
and a real Linear client.
"""

from __future__ import annotations

from typing import Optional

from .config import Settings
from .llm import build_llm
from .llm.scripted import ScriptedLLM
from .agents.offline_brain import make_offline_responder
from .memory import Memory
from .orchestrator import PraxisAgent
from .platform.fake import FakeLinear
from .platform.linear.client import HttpxTransport, LinearClient


def build_agent(
    settings: Optional[Settings] = None,
    *,
    offline: bool = False,
    memory: Optional[Memory] = None,
    fake: Optional[FakeLinear] = None,
    client: Optional[LinearClient] = None,
) -> PraxisAgent:
    settings = settings or Settings()
    mem = memory or Memory(settings.memory_file() if not offline else ":memory:")

    if offline or settings.llm_provider == "scripted":
        llm = ScriptedLLM(make_offline_responder())
    else:
        llm = build_llm(settings)

    if client is None:
        if offline:
            client = LinearClient(fake or FakeLinear())
        else:
            if not settings.linear_api_key:
                raise RuntimeError("LINEAR_API_KEY is not set — cannot reach Linear. Use offline mode for a dry run.")
            client = LinearClient(HttpxTransport(settings.linear_api_url, settings.linear_api_key))

    return PraxisAgent(llm=llm, client=client, memory=mem, settings=settings)
