"""LLM provider layer."""

from __future__ import annotations

from ..config import (
    DEFAULT_LLM_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
    Settings,
)
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
        return OpenAILLM(
            settings.openai_api_key or "",
            settings.llm_model,
            base_url=settings.llm_base_url,
        )
    if settings.llm_provider == "openrouter":
        # OpenRouter needs a namespaced slug; if the user left PRAXIS_LLM_MODEL at
        # the native Anthropic default, substitute a sensible OpenRouter default.
        model = settings.llm_model
        if model == DEFAULT_LLM_MODEL:
            model = DEFAULT_OPENROUTER_MODEL
        return OpenAILLM(
            settings.openrouter_api_key or "",
            model,
            base_url=settings.llm_base_url or OPENROUTER_BASE_URL,
            name_prefix="openrouter",
            # Broadest model compatibility: steer JSON via the prompt, not a
            # response_format some OpenRouter models reject.
            json_via_response_format=False,
        )
    raise LLMError(
        f"Provider '{settings.llm_provider}' cannot be built from settings; "
        "inject a ScriptedLLM directly for offline use."
    )
