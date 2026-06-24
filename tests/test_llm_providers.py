"""Offline tests for the LLM provider factory (`build_llm`).

No network: the OpenAI-compatible client connects lazily, so constructing a
provider with a dummy key exercises all the wiring (base URL, model defaulting,
error messages) without a live call. Settings are driven via env vars, exactly
as `.env` would supply them.
"""

from __future__ import annotations

import pytest

from praxis.config import (
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
    Settings,
)
from praxis.llm import build_llm
from praxis.llm.base import LLMError

_LLM_ENV = (
    "PRAXIS_LLM_PROVIDER",
    "PRAXIS_LLM_MODEL",
    "PRAXIS_LLM_BASE_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture
def env(monkeypatch):
    """Return a builder that sets a clean LLM env and yields fresh Settings."""

    def _build(**values):
        for key in _LLM_ENV:
            monkeypatch.delenv(key, raising=False)
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        # `_env_file=None` keeps these hermetic: ignore any real `.env` in the
        # repo (a developer's live keys must not leak into provider unit tests).
        return Settings(_env_file=None)

    return _build


def test_openrouter_defaults(env):
    s = env(PRAXIS_LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="sk-or-test")
    assert s.llm_ready() is True
    llm = build_llm(s)
    # Namespaced default slug substituted (the native Anthropic default is invalid here).
    assert llm.name == f"openrouter:{DEFAULT_OPENROUTER_MODEL}"
    assert str(llm._client.base_url).rstrip("/") == OPENROUTER_BASE_URL
    # JSON is steered via the prompt, not response_format (broad model compatibility).
    assert llm._json_via_response_format is False


def test_openrouter_explicit_model(env):
    s = env(
        PRAXIS_LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="k",
        PRAXIS_LLM_MODEL="openai/gpt-4o",
    )
    assert build_llm(s).name == "openrouter:openai/gpt-4o"


def test_openrouter_base_url_override(env):
    s = env(
        PRAXIS_LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="k",
        PRAXIS_LLM_BASE_URL="https://example.test/v1",
    )
    assert str(build_llm(s)._client.base_url).rstrip("/") == "https://example.test/v1"


def test_openrouter_missing_key(env):
    s = env(PRAXIS_LLM_PROVIDER="openrouter")
    assert s.llm_ready() is False
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        build_llm(s)


def test_openai_honors_base_url(env):
    s = env(
        PRAXIS_LLM_PROVIDER="openai",
        OPENAI_API_KEY="k",
        PRAXIS_LLM_BASE_URL="https://gateway.test/v1",
        PRAXIS_LLM_MODEL="gpt-4o",
    )
    llm = build_llm(s)
    assert llm.name == "openai:gpt-4o"
    assert str(llm._client.base_url).rstrip("/") == "https://gateway.test/v1"
