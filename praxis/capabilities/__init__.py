"""Capability layer: registry, builtin primitives, runtime synthesis."""

from __future__ import annotations

from .primitives import register_builtins
from .registry import (
    WHITELISTED_TRANSFORMS,
    Capability,
    CapabilityError,
    CapabilityRegistry,
    ExecutionContext,
)
from .synthesis import Synthesizer

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityRegistry",
    "ExecutionContext",
    "WHITELISTED_TRANSFORMS",
    "register_builtins",
    "Synthesizer",
]
