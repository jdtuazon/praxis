"""Shared fixtures: every test runs the FULL agent offline (ScriptedLLM + FakeLinear).

No API keys, no network — yet the entire planning/synthesis/execution/learning
loop runs for real against a genuine GraphQL schema.
"""

from __future__ import annotations

import pytest

from praxis.build import build_agent
from praxis.config import Settings
from praxis.memory import Memory
from praxis.platform.fake import FakeLinear
from praxis.platform.linear.client import LinearClient


def settings() -> Settings:
    return Settings(llm_provider="scripted")


def make_agent(memory: Memory | None = None, fake: FakeLinear | None = None):
    return build_agent(
        settings(), offline=True, memory=memory or Memory(":memory:"), fake=fake or FakeLinear()
    )


@pytest.fixture
def memory() -> Memory:
    return Memory(":memory:")


@pytest.fixture
def fake() -> FakeLinear:
    return FakeLinear()


@pytest.fixture
def client(fake) -> LinearClient:
    return LinearClient(fake)


@pytest.fixture
def agent(memory, fake):
    return make_agent(memory, fake)
