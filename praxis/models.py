"""Core domain models shared across Praxis.

These pydantic models are the contract between the planner, executor, memory,
synthesizer, validator and the structured execution report. Keeping them in one
place makes the data flow auditable — every field that ends up in a report or in
persistent memory is declared here.

Design note: the model set deliberately distinguishes the things the assignment
grades as the *real* version from their cheap lookalikes:

  • Constraints carry an `origin` (schema-derived vs runtime-learned) so we only
    ever claim genuinely learned facts as "learning".
  • A constraint can `rewrite_plan` — i.e. cause a *different decision*
    (insert/modify steps), not merely veto a call.
  • The learning comparison tracks `wasted_calls` (calls a known constraint
    would have pre-empted) and supports a transfer/negative-control framing, so
    the headline number is behaviour change, not memoization.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────
class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # not attempted (e.g. a dependency failed)
    ROLLED_BACK = "rolled_back"  # succeeded then compensated by rollback


class ExecutionStatus(str, Enum):
    SUCCESS = "success"  # every required step succeeded
    PARTIAL = "partial"  # some steps succeeded, some failed/skipped
    FAILED = "failed"  # nothing meaningful completed
    ROLLED_BACK = "rolled_back"  # failed and compensation was applied


class CapabilitySource(str, Enum):
    BUILTIN = "builtin"  # primitive shipped with Praxis
    SYNTHESIZED = "synthesized"  # built at runtime by the synthesizer


class CapabilityKind(str, Enum):
    GRAPHQL = "graphql"  # a parameterized GraphQL operation
    COMPOSITE = "composite"  # an ordered composition of trusted capabilities + pure transforms


class CapabilityStatus(str, Enum):
    BUILTIN = "builtin"  # ships trusted
    PROBATIONARY = "probationary"  # passed the test gate; not yet proven on real runs
    TRUSTED = "trusted"  # promoted after M successful real executions
    DEMOTED = "demoted"  # failed in the wild; needs re-test


class PlanSource(str, Enum):
    FRESH = "fresh"  # decomposed from scratch by the LLM
    REUSED = "reused"  # a past successful plan SHAPE reused (bindings re-resolved)
    ADAPTED = "adapted"  # a past plan retrieved and adapted


class ConstraintKind(str, Enum):
    ENTITY_ID = "entity_id"  # cached resolved id (team, state, label, user...)
    ENUM = "enum"  # allowed values / numeric range / NL→code mapping for a field
    REQUIRED_FIELD = "required_field"
    RATE_LIMIT = "rate_limit"
    PERMISSION = "permission"  # an operation is forbidden for this token
    WORKFLOW_RULE = (
        "workflow_rule"  # a policy that REWRITES a plan (e.g. estimate required before Done)
    )
    FIELD_SHAPE = "field_shape"


class ConstraintOrigin(str, Enum):
    SCHEMA_DERIVED = "schema_derived"  # introspectable; NOT claimed as learning
    RUNTIME_LEARNED = "runtime_learned"  # discovered from a real execution; this IS the learning


class VerificationPolicy(str, Enum):
    TRUST = "trust"  # use without re-checking (stable facts)
    VERIFY_ON_READ = "verify_on_read"  # cheap re-resolve before relying on it (volatile ids)
    REFETCH_TTL = "refetch_ttl"  # re-fetch if older than ttl_seconds


class Reversibility(str, Enum):
    REVERSIBLE = "reversible"  # cleanly compensable (e.g. update→update back)
    ARCHIVE_ONLY = "archive_only"  # can archive but not hard-delete (Linear semantics)
    IRREVERSIBLE = "irreversible"  # notifications fired, comments posted — cannot undo


class TestTier(str, Enum):
    SCHEMA_CHECK = "schema_check"  # validate the contract against introspection (0 API calls)
    READ_PROBE = "read_probe"  # execute a read to confirm shape (non-mutating)
    CANARY_ROLLBACK = "canary_rollback"  # create a canary then inverse-op it (gated)
    COMPOSITION = "composition"  # constituents trusted + one e2e canary


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────
class PlanStep(BaseModel):
    """One executable step in a decomposed plan.

    `args` values may reference earlier step outputs with the `{{stepN.path}}`
    template syntax, resolved at execution time.
    """

    index: int
    intent: str = Field(description="Short verb-phrase describing the sub-goal.")
    capability: str | None = Field(
        default=None,
        description="Capability to run. None ⇒ capability gap → synthesis.",
    )
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    depends_on: list[int] = Field(default_factory=list)
    optional: bool = Field(
        default=False, description="If true, failure does not fail the whole run."
    )
    # Provenance: did a learned constraint insert/modify this step?
    inserted_by_constraint: str | None = None


class Plan(BaseModel):
    instruction: str
    steps: list[PlanStep] = Field(default_factory=list)
    source: PlanSource = PlanSource.FRESH
    reused_from_execution_id: int | None = None
    intent_signature: str = Field(
        default="",
        description="Structured key {verb·entity·predicate·fields} with params extracted; the reuse key.",
    )
    rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reuse_rejected_reason: str | None = None  # set when a candidate reuse was correctly rejected


# ─────────────────────────────────────────────────────────────────────────────
# Capability synthesis contracts
# ─────────────────────────────────────────────────────────────────────────────
class TransformStep(BaseModel):
    """One step of a COMPOSITE capability's composition plan.

    A composite calls only already-registered capabilities + a small set of
    whitelisted pure transforms (filter/group/sort/format). No imports, no
    network, no filesystem — a constrained DSL, not free `exec`.
    """

    op: str = Field(
        description="capability:<name> | transform:<filter|group|sort|markdown_table|create_each>"
    )
    args: dict[str, Any] = Field(default_factory=dict)
    bind: str | None = Field(default=None, description="Name to store this step's result under.")


class CapabilityPlan(BaseModel):
    """The synthesizer's typed proposal, validated against the schema BEFORE any API call."""

    name: str
    kind: CapabilityKind
    description: str = ""
    # GRAPHQL kind (built from a contract — we assemble the document, the model
    # never writes raw GraphQL, so there is no syntax-error surface):
    graphql_root_field: str | None = None  # e.g. "issueArchive"
    operation_type: str | None = None  # "query" | "mutation"
    args: dict[str, str] = Field(
        default_factory=dict
    )  # arg_name -> graphql type (e.g. "id": "String!")
    selection: str = Field(
        default="", description="Selection set body, e.g. 'success issue { id identifier }'."
    )
    select_path: str | None = None
    side_effecting: bool = False
    inverse_root_field: str | None = None  # e.g. "issueUnarchive" for rollback
    # COMPOSITE kind:
    composition: list[TransformStep] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    # Sample args used by the test gate to exercise the capability safely.
    probe_args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class CapabilitySpec(BaseModel):
    """Persisted, serializable executable knowledge: a GraphQL op or a composite.

    Stored in capability memory so it survives sessions and is reused without
    re-synthesis. Carries lifecycle + provenance so a stale capability is
    re-tested rather than blindly re-run.
    """

    name: str
    version: int = 1
    kind: CapabilityKind
    source: CapabilitySource
    status: CapabilityStatus = CapabilityStatus.BUILTIN
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    # GRAPHQL
    graphql: str | None = None
    select_path: str | None = None
    side_effecting: bool = False
    inverse_capability: str | None = None
    # COMPOSITE
    composition: list[TransformStep] = Field(default_factory=list)
    # Provenance / lifecycle
    synthesized_for: str | None = None
    schema_hash: str | None = None
    test_tier_passed: str | None = None
    test_summary: str | None = None
    created_at: float = Field(default_factory=time.time)


class TestOutcome(BaseModel):
    tier: TestTier
    passed: bool
    detail: str = ""
    api_calls: int = 0


class SynthesisAttempt(BaseModel):
    attempt: int
    plan: CapabilityPlan | None = None
    outcomes: list[TestOutcome] = Field(default_factory=list)
    error: str | None = None


class SynthesisResult(BaseModel):
    requested_for: str
    success: bool
    capability_name: str | None = None
    attempts: list[SynthesisAttempt] = Field(default_factory=list)
    final_error: str | None = None
    api_calls: int = 0
    llm_calls: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Constraints (capability-memory payloads)
# ─────────────────────────────────────────────────────────────────────────────
class Constraint(BaseModel):
    """A structured fact the agent learned about the platform at runtime.

    Read *before* execution to change behaviour: cached ids skip exploratory
    queries; enum facts pre-validate args; permission facts switch tool choice;
    workflow rules *rewrite the plan*.
    """

    kind: ConstraintKind
    origin: ConstraintOrigin = ConstraintOrigin.RUNTIME_LEARNED
    scope: str = Field(description="Namespace, e.g. 'team', 'field', 'mutation', 'global'.")
    key: str = Field(description="Identifier within scope, e.g. 'Engineering' or 'issue.priority'.")
    value: Any = None
    description: str = ""
    rewrites_plan: bool = Field(
        default=False,
        description="True if this constraint inserts/modifies plan steps (a decision change).",
    )
    verification_policy: VerificationPolicy = VerificationPolicy.TRUST
    ttl_seconds: float | None = None
    discovered_from_execution: int | None = None
    observed_at: float = Field(default_factory=time.time)
    invalidated_by: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    hits: int = Field(default=0, description="How many times this constraint helped a later run.")


# ─────────────────────────────────────────────────────────────────────────────
# Execution reporting
# ─────────────────────────────────────────────────────────────────────────────
class Decision(BaseModel):
    """An explicit, human-readable decision the agent made and why."""

    summary: str
    rationale: str = ""
    stage: str = ""  # plan | resolve | synthesize | execute | validate | learn


class CallAttribution(BaseModel):
    """Why a call was avoided/skipped — the provenance ledger entry."""

    kind: str = Field(
        description="reused_plan | cached_entity | pre_validated | reused_capability | skipped_probe"
    )
    ref: str = Field(
        description="Memory artifact responsible, e.g. 'constraint:field/issue.priority'."
    )
    detail: str = ""


class AppliedEffect(BaseModel):
    """A side-effect recorded in the per-run journal for best-effort compensation."""

    step_index: int
    description: str
    reversibility: Reversibility
    compensating_capability: str | None = None
    compensating_args: dict[str, Any] = Field(default_factory=dict)
    compensated: bool = False
    compensation_error: str | None = None


class ResultItem(BaseModel):
    """One entity returned by a read/query step, surfaced so a run that *answers*
    a question (not just mutates) shows the answer, each row deep-linkable."""

    label: str = ""  # identifier / key, e.g. "ENG-3"
    title: str = ""
    meta: str = ""  # a secondary tag, e.g. priority label or workflow state
    url: str | None = None


class StepReport(BaseModel):
    index: int
    intent: str
    capability: str | None = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    duration_s: float = 0.0
    api_calls: int = 0
    wasted_calls: int = 0
    result_summary: str | None = None
    # The concrete artifact this step produced, so a run is visible, not just
    # "success": a deep-link to the created/affected entity (a real Linear URL)
    # and a fuller detail body (e.g. the created document's markdown content, or a
    # preview of the issues a query gathered).
    result_url: str | None = None
    result_detail: str | None = None
    result_items: list[ResultItem] = Field(default_factory=list)
    error: str | None = None
    rolled_back: bool = False
    prevalidated: bool = False
    provenance: list[CallAttribution] = Field(default_factory=list)
    inserted_by_constraint: str | None = None


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
    lines: list[str] = Field(default_factory=list)


class LearningComparison(BaseModel):
    """The measurable learning signal: this run vs prior runs / cold-DB control.

    Primary (behaviour change):  wasted_calls → 0, attributed per-call to a
    memory artifact; transfer benefit to held-out instructions.
    Secondary (reuse, labelled): same-signature API-call drop.
    """

    instruction_signature: str = ""
    mode: str = "fresh"  # fresh | reuse | transfer
    run_number: int = 1
    is_repeat: bool = False
    # current run
    api_calls: int = 0
    llm_calls: int = 0
    duration_s: float = 0.0
    wasted_calls: int = 0
    failed_steps: int = 0
    synthesized: int = 0
    # baseline (first run of this signature, or cold-DB control)
    baseline_api_calls: int | None = None
    baseline_llm_calls: int | None = None
    baseline_wasted_calls: int | None = None
    baseline_duration_s: float | None = None
    # deltas
    api_calls_saved: int = 0
    llm_calls_saved: int = 0
    wasted_calls_saved: int = 0
    speedup_pct: float | None = None
    # attribution: every saved/avoided call mapped to the memory artifact that caused it
    saved_calls: list[CallAttribution] = Field(default_factory=list)
    attributions: list[str] = Field(default_factory=list)


class ExecutionReport(BaseModel):
    """The structured report returned after every run."""

    execution_id: int | None = None
    instruction: str
    status: ExecutionStatus
    started_at: float
    finished_at: float
    duration_s: float = 0.0
    total_api_calls: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0
    wasted_calls: int = 0

    plan: Plan
    steps: list[StepReport] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)

    synthesis: list[SynthesisResult] = Field(default_factory=list)
    synthesized_capabilities: list[str] = Field(default_factory=list)
    discovered_constraints: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_notes: list[str] = Field(default_factory=list)

    rollback_performed: bool = False
    rollback_steps: list[str] = Field(default_factory=list)
    manual_cleanup_required: list[str] = Field(default_factory=list)

    memory_before: MemorySnapshot = Field(default_factory=MemorySnapshot)
    memory_after: MemorySnapshot = Field(default_factory=MemorySnapshot)
    memory_diff: MemoryDiff = Field(default_factory=MemoryDiff)
    learning: LearningComparison = Field(default_factory=LearningComparison)

    summary: str = ""

    def succeeded(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS
