"""Platform layer: transport abstraction + Linear client + FakeLinear."""

from __future__ import annotations

from .base import GraphQLTransport, PlatformError

__all__ = ["GraphQLTransport", "PlatformError"]
