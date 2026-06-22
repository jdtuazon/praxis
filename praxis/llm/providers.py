"""Concrete LLM providers: Anthropic (default) and OpenAI."""

from __future__ import annotations

from .base import LLM, LLMError


class AnthropicLLM(LLM):
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__()
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        import anthropic  # local import keeps the dep optional at import time

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    def _generate(self, system: str, prompt: str, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
        sys = system
        if json_mode:
            sys = (system + "\n\nRespond with ONLY valid JSON. No prose, no code fences.").strip()
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=sys,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        usage = getattr(resp, "usage", None)
        it = getattr(usage, "input_tokens", 0) if usage else 0
        ot = getattr(usage, "output_tokens", 0) if usage else 0
        return text, it, ot


class OpenAILLM(LLM):
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__()
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set.")
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    def _generate(self, system: str, prompt: str, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            **kwargs,
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        it = getattr(usage, "prompt_tokens", 0) if usage else 0
        ot = getattr(usage, "completion_tokens", 0) if usage else 0
        return text, it, ot
