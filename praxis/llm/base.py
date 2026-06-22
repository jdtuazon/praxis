"""LLM provider abstraction.

Every reasoning component (planner, synthesizer, validator) talks to an `LLM`
object, never to a vendor SDK directly. This keeps the orchestrator
provider-agnostic and — crucially — lets tests inject a deterministic
`ScriptedLLM` so the full agent loop runs offline with no API keys.

The base class tracks token + call usage so the learning signal can attribute
*LLM* call savings (e.g. skipping re-planning) separately from *platform* API
call savings.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def snapshot(self) -> "LLMUsage":
        return LLMUsage(self.calls, self.input_tokens, self.output_tokens)

    def since(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            self.calls - other.calls,
            self.input_tokens - other.input_tokens,
            self.output_tokens - other.output_tokens,
        )


class LLMError(RuntimeError):
    pass


class LLM(ABC):
    def __init__(self) -> None:
        self.usage = LLMUsage()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def _generate(self, system: str, prompt: str, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens)."""

    def generate(self, system: str, prompt: str, *, max_tokens: int = 2048, json_mode: bool = False) -> str:
        text, it, ot = self._generate(system, prompt, max_tokens, json_mode)
        self.usage.calls += 1
        self.usage.input_tokens += it
        self.usage.output_tokens += ot
        return text

    def generate_json(self, system: str, prompt: str, *, max_tokens: int = 2048) -> object:
        """Generate and parse a JSON object/array, tolerating code fences & prose."""
        raw = self.generate(system, prompt, max_tokens=max_tokens, json_mode=True)
        return extract_json(raw)


def extract_json(raw: str) -> object:
    """Best-effort JSON extraction from an LLM response."""
    s = raw.strip()
    # Strip ```json ... ``` fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] block.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(s)):
            if s[i] == open_ch:
                depth += 1
            elif s[i] == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"Could not parse JSON from LLM response: {raw[:400]!r}")
