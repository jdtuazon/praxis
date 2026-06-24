"""Cold-run digest over-planning: a synthesized digest/report capability already
persists its own document, so a planner-added trailing `create_document` whose
content doesn't bind (resolves empty) must be elided as redundant — not executed
into a failure that rolls back the whole (otherwise successful) run.
"""

from __future__ import annotations

from praxis.agents.executor import Executor
from praxis.capabilities import (
    CapabilityRegistry,
    ExecutionContext,
    Synthesizer,
    register_builtins,
)
from praxis.config import Settings
from praxis.llm.scripted import ScriptedLLM
from praxis.memory import Memory
from praxis.models import Plan, PlanStep, StepStatus
from praxis.platform.fake import FakeLinear
from praxis.platform.linear.client import LinearClient


def _executor_env():
    reg = CapabilityRegistry()
    mem = Memory(":memory:")
    register_builtins(reg, mem)
    client = LinearClient(FakeLinear())
    settings = Settings(llm_provider="scripted")
    ctx = ExecutionContext(client=client, registry=reg, memory=mem, settings=settings)
    synth = Synthesizer(ScriptedLLM(lambda s, p: None), client, reg, mem, settings)
    return Executor(reg, mem, settings), ctx, synth, client


def test_redundant_empty_create_document_is_elided():
    """First step creates a document; a second create_document bound to a non-existent
    output key (resolves empty) is redundant and must be elided, not failed."""
    executor, ctx, synth, client = _executor_env()
    plan = Plan(
        instruction="roll issues into a triage digest",
        steps=[
            PlanStep(
                index=0,
                intent="build and save the digest",
                capability="create_document",
                args={"title": "Triage digest", "content": "# Digest\n- ENG-1"},
                depends_on=[],
            ),
            PlanStep(
                index=1,
                intent="save the digest document",
                capability="create_document",
                args={"title": "Triage digest", "content": "{{step0.groupedContent}}"},
                depends_on=[0],
            ),
        ],
    )
    steps, _decisions, _synth = executor.execute(plan, ctx, synth)
    s0, s1 = steps[0], steps[1]

    assert s0.status == StepStatus.SUCCESS, "the real digest document is created"
    # the redundant second create_document must be elided as a no-op success, NOT failed
    assert s1.status == StepStatus.SUCCESS
    assert (
        "redundant" in (s1.result_summary or "").lower()
        or "elided" in (s1.result_summary or "").lower()
    )
    assert s1.api_calls == 0 and ctx.wasted_calls == 0  # nothing wasted on a dangling reference


def test_empty_create_document_without_prior_doc_still_fails():
    """The elision is narrow: an empty create_document with NO prior document this run
    is a genuine error and must still fail (not be silently elided)."""
    executor, ctx, synth, client = _executor_env()
    plan = Plan(
        instruction="save a digest",
        steps=[
            PlanStep(
                index=0,
                intent="save the digest",
                capability="create_document",
                args={"title": "Digest", "content": "{{step99.missing}}"},
                depends_on=[],
            ),
        ],
    )
    steps, _decisions, _synth = executor.execute(plan, ctx, synth)
    assert steps[0].status == StepStatus.FAILED
