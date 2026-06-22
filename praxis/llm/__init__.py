"""LLM provider layer."""

from __future__ import annotations

from ..config import Settings
from .base import LLM, LLMError, LLMUsage, extract_json
from .providers import AnthropicLLM, OpenAILLM
from .scripted import ScriptedLLM

__all__ = [
    "LLM",
    "LLMError",
    "LLMUsage",
    "extract_json",
    "AnthropicLLM",
    "OpenAILLM",
    "ScriptedLLM",
    "build_llm",
]


def build_llm(settings: Settings) -> LLM:
    """Construct the configured provider. Raises LLMError if not ready."""
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings.anthropic_api_key or "", settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAILLM(settings.openai_api_key or "", settings.llm_model)
    raise LLMError(
        f"Provider '{settings.llm_provider}' cannot be built from settings; "
        "inject a ScriptedLLM directly for offline use."
    )
