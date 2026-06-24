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

    def _generate(
        self, system: str, prompt: str, max_tokens: int, json_mode: bool
    ) -> tuple[str, int, int]:
        sys = system
        if json_mode:
            sys = (system + "\n\nRespond with ONLY valid JSON. No prose, no code fences.").strip()
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=sys,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(resp, "usage", None)
        it = getattr(usage, "input_tokens", 0) if usage else 0
        ot = getattr(usage, "output_tokens", 0) if usage else 0
        return text, it, ot


class OpenAILLM(LLM):
    """OpenAI-compatible chat client.

    Also drives any OpenAI-protocol gateway — notably **OpenRouter** — via a
    custom ``base_url``. OpenRouter exposes hundreds of models behind one key,
    and not all of them honour ``response_format={"type": "json_object"}``; set
    ``json_via_response_format=False`` to instead steer JSON purely through the
    system prompt (parsed leniently by ``extract_json``), which works on every
    model.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        name_prefix: str = "openai",
        json_via_response_format: bool = True,
    ) -> None:
        super().__init__()
        if not api_key:
            env = "OPENROUTER_API_KEY" if name_prefix == "openrouter" else "OPENAI_API_KEY"
            raise LLMError(f"{env} is not set.")
        import openai

        client_kwargs: dict = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**client_kwargs)
        self._model = model
        self._name_prefix = name_prefix
        self._json_via_response_format = json_via_response_format

    @property
    def name(self) -> str:
        return f"{self._name_prefix}:{self._model}"

    def _generate(
        self, system: str, prompt: str, max_tokens: int, json_mode: bool
    ) -> tuple[str, int, int]:
        sys = system
        kwargs: dict = {}
        if json_mode:
            if self._json_via_response_format:
                kwargs["response_format"] = {"type": "json_object"}
            else:
                sys = (
                    system + "\n\nRespond with ONLY valid JSON. No prose, no code fences."
                ).strip()
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt},
            ],
            **kwargs,
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        it = getattr(usage, "prompt_tokens", 0) if usage else 0
        ot = getattr(usage, "completion_tokens", 0) if usage else 0
        return text, it, ot
