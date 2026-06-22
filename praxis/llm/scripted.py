"""Deterministic, offline LLM used by the test suite and the `--offline` demo.

`ScriptedLLM` routes each prompt through a user-supplied responder function and
returns canned text. This is what lets the *entire* agent loop — planning,
synthesis, validation, learning — run with zero network and produce identical,
assertable results every time. The live demo uses a real provider; this exists
so regression tests can prove the learning signal with hard numbers.
"""

from __future__ import annotations

from typing import Callable, Optional

from .base import LLM

Responder = Callable[[str, str], Optional[str]]


class ScriptedLLM(LLM):
    def __init__(self, responder: Responder, model: str = "scripted-1") -> None:
        super().__init__()
        self._responder = responder
        self._model = model
        self.prompts: list[tuple[str, str]] = []  # full call log for assertions

    @property
    def name(self) -> str:
        return f"scripted:{self._model}"

    def _generate(self, system: str, prompt: str, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
        self.prompts.append((system, prompt))
        text = self._responder(system, prompt)
        if text is None:
            raise AssertionError(
                "ScriptedLLM had no scripted response for prompt:\n"
                f"--- system ---\n{system[:300]}\n--- prompt ---\n{prompt[:600]}"
            )
        # Deterministic, content-derived token estimate (no Math.random equivalent).
        it = max(1, len(system) + len(prompt)) // 4
        ot = max(1, len(text)) // 4
        return text, it, ot
