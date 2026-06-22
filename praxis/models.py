"""Core domain models shared across Praxis.

These pydantic models are the contract between the planner, executor, memory,
synthesizer, validator and the structured execution report. Keeping them in one
place makes the data flow auditable — every field that ends up in a report or in
persistent memory is declared here.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────
class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"          # not attempted (e.g. a dependency failed)
    ROLLED_BACK = "rolled_back"  # succeeded then undone by rollback


class ExecutionStatus(str, Enum):
    SUCCESS = "success"   # every step succeeded
    PARTIAL = "partial"   # some steps succeeded, some failed/skipped
    FAILED = "failed"     # nothing meaningful completed
    ROLLED_BACK = "rolled_back"


class CapabilitySource(str, Enum):
    BUILTIN = "builtin"          # primitive shipped with Praxis
    SYNTHESIZED = "synthesized"  # built at runtime by the synthesizer


class CapabilityKind(str, Enum):
    GRAPHQL = "graphql"    # a parameterized GraphQL operation
    FUNCTION = "function"  # synthesized Python that composes primitives + transforms


class PlanSource(str, Enum):
    FRESH = "fresh"        # decomposed from scratch by the LLM
    REUSED = "reused"      # a past successful plan reused verbatim
    ADAPTED = "adapted"    # a past plan retrieved and lightly adapted


class ConstraintKind(str, Enum):
    ENTITY_ID = "entity_id"          # cached resolved id (team, state, label, user...)
    ENUM = "enum"                    # allowed values / numeric range for a field
    REQUIRED_FIELD = "required_field"
    RATE_LIMIT = "rate_limit"
    PERMISSION = "permission"        # an operation is forbidden for this token
    FIELD_SHAPE = "field_shape"      # structural rule discovered from a validation error


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────
class PlanStep(BaseModel):
    """One executable step in a decomposed plan.

    `args` values may contain references to earlier step outputs using the
    `{{stepN.path}}` template syntax, resolved at execution time.
    """

    index: int
    intent: str = Field(description="Short verb-phrase describing the sub-goal.")
    capability: Optional[str] = Field(
        default=None,
        description="Name of the capability to run. None ⇒ capability gap → synthesis.",
    )
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    depends_on: list[int] = Field(default_factory=list)
    rollback_hint: Optional[str] = None
    optional: bool = Field(
        default=False,
        description="If true, failure does not fail the whole execution.",
    )


class Plan(BaseModel):
    instruction: str
    steps: list[PlanStep] = Field(default_factory=list)
    source: PlanSource = PlanSource.FRESH
    reused_from_execution_id: Optional[int] = None
    intent_signature: str = ""
    rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Capabilities & constraints (capability-memory payloads)
# ─────────────────────────────────────────────────────────────────────────────
class CapabilitySpec(BaseModel):
    """The persisted, serializable description of a capability.

    A capability is *executable knowledge*: either a parameterized GraphQL
    operation or a synthesized Python function. Stored in capability memory so it
    survives across sessions and is reused without re-synthesis.
    """

    name: str
    version: int = 1
    kind: CapabilityKind
    source: CapabilitySource
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    # For GRAPHQL capabilities:
    graphql: Optional[str] = None
    # `select_path` tells the executor where the meaningful payload lives in the
    # GraphQL response (e.g. "issueCreate.issue").
    select_path: Optional[str] = None
    # For FUNCTION capabilities: Python source defining `def run(ctx, **kwargs)`.
    code: Optional[str] = None
    # Provenance / testing
    synthesized_for: Optional[str] = None
    test_summary: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class Constraint(BaseModel):
    """A structured fact the agent learned about the platform at runtime.

    Read *before* execution to change behaviour: cached ids skip exploratory
    queries; enum ranges pre-validate args; permission facts avoid forbidden ops.
    """

    kind: ConstraintKind
    scope: str = Field(description="Namespace, e.g. 'team', 'field', 'mutation', 'global'.")
    key: str = Field(description="Identifier within the scope, e.g. 'Engineering' or 'issue.priority'.")
    value: Any = None
    description: str = ""
    discovered_from_execution: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    hits: int = Field(default=0, description="How many times this constraint helped a later run.")


# ─────────────────────────────────────────────────────────────────────────────
# Execution reporting
# ─────────────────────────────────────────────────────────────────────────────
class Decision(BaseModel):
    """An explicit, human-readable decision the agent made and why.

    These make the report explain itself: 'reused plan from #7', 'synthesized
    archive_issue because no capability matched', 'aborted after step 3 failed'.
    """

    summary: str
    rationale: str = ""
    stage: str = ""  # plan | resolve | synthesize | execute | validate | learn


class StepReport(BaseModel):
    index: int
    intent: str
    capability: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    duration_s: float = 0.0
    api_calls: int = 0
    result_summary: Optional[str] = None
    error: Optional[str] = None
    rolled_back: bool = False


class MemoryCounts(BaseModel):
    instructions: int = 0
    executions: int = 0
    capabilities: int = 0
    constraints: int = 0


class MemorySnapshot(BaseModel):
    counts: MemoryCounts = Field(default_factory=MemoryCounts)
    capability_names: list[str] = Field(default_factory=list)
    constraint_keys: list[str] = Field(default_factory=list)


class MemoryDiff(BaseModel):
    """What changed in memory because of this run, in plain language."""

    new_capabilities: list[str] = Field(default_factory=list)
    new_constraints: list[str] = Field(default_factory=list)
    updated_stats: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)  # rendered, human-readable deltas


class LearningComparison(BaseModel):
    """The measurable learning signal: this run vs prior runs of the same pattern."""

    instruction_signature: str = ""
    run_number: int = 1  # 1 == first time this pattern was seen
    is_repeat: bool = False
    # Current run metrics
    api_calls: int = 0
    llm_calls: int = 0
    duration_s: float = 0.0
    failed_steps: int = 0
    # Baseline (first run of this pattern)
    baseline_api_calls: Optional[int] = None
    baseline_llm_calls: Optional[int] = None
    baseline_duration_s: Optional[float] = None
    baseline_failed_steps: Optional[int] = None
    # Deltas + attribution
    api_calls_saved: int = 0
    llm_calls_saved: int = 0
    speedup_pct: Optional[float] = None
    attributions: list[str] = Field(default_factory=list)  # WHY it improved


class ExecutionReport(BaseModel):
    """The structured report returned after every run."""

    execution_id: Optional[int] = None
    instruction: str
    status: ExecutionStatus
    started_at: float
    finished_at: float
    duration_s: float = 0.0
    total_api_calls: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0

    plan: Plan
    steps: list[StepReport] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)

    synthesized_capabilities: list[str] = Field(default_factory=list)
    discovered_constraints: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_notes: list[str] = Field(default_factory=list)

    rollback_performed: bool = False
    rollback_steps: list[str] = Field(default_factory=list)

    memory_before: MemorySnapshot = Field(default_factory=MemorySnapshot)
    memory_after: MemorySnapshot = Field(default_factory=MemorySnapshot)
    memory_diff: MemoryDiff = Field(default_factory=MemoryDiff)
    learning: LearningComparison = Field(default_factory=LearningComparison)

    # Human-readable one-liner summarizing outcome.
    summary: str = ""

    def succeeded(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS
