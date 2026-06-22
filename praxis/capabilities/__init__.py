"""Capability layer: registry, builtin primitives, runtime synthesis."""

from __future__ import annotations

from .registry import (
    Capability,
    CapabilityError,
    CapabilityRegistry,
    ExecutionContext,
    WHITELISTED_TRANSFORMS,
)
from .primitives import register_builtins
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
