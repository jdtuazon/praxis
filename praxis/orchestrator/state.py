"""Shared state for the LangGraph orchestration graph."""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from ..capabilities.registry import ExecutionContext
from ..models import ExecutionReport, Plan


class GraphState(TypedDict, total=False):
    instruction: str
    report: ExecutionReport          # mutated in place across nodes; finalized by the facade
    ctx: ExecutionContext
    plan: Plan
    t0: float
    api_before: int
    llm_before: int
    tokens_before: int
    do_rollback: bool
