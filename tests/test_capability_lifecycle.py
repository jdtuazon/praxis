"""A synthesized capability must only be trusted on the strength of *clean*
successes — runs that failed and were rolled back are not evidence of health."""

from praxis.agents.learner import Learner
from praxis.capabilities.registry import ExecutionContext
from praxis.config import Settings
from praxis.memory import Memory
from praxis.models import (
    CapabilityKind,
    CapabilitySource,
    CapabilitySpec,
    CapabilityStatus,
    Plan,
    StepReport,
    StepStatus,
)


def _learn_once(learner, mem, status):
    ctx = ExecutionContext(
        client=None, registry=None, memory=mem, settings=Settings(llm_provider="scripted")
    )
    plan = Plan(instruction="x", intent_signature="sig")
    steps = [StepReport(index=0, intent="use foo", capability="foo", status=status)]
    learner.learn(ctx, execution_id=1, plan=plan, steps=steps)


def test_rolled_back_runs_do_not_promote_or_inflate_health():
    mem = Memory(":memory:")
    mem.capability.save_capability(
        CapabilitySpec(
            name="foo",
            kind=CapabilityKind.COMPOSITE,
            source=CapabilitySource.SYNTHESIZED,
            status=CapabilityStatus.PROBATIONARY,
        )
    )
    learner = Learner(mem, Settings(llm_provider="scripted"))

    # Two failed-then-rolled-back runs must NOT promote the capability.
    _learn_once(learner, mem, StepStatus.ROLLED_BACK)
    _learn_once(learner, mem, StepStatus.ROLLED_BACK)
    assert mem.capability.get_capability("foo").status == CapabilityStatus.PROBATIONARY
    assert mem.capability.success_count("foo") == 0
    # health is not falsely 100%
    assert mem.capability.capability_health("foo")["success_rate"] is None


def test_clean_successes_still_promote():
    mem = Memory(":memory:")
    mem.capability.save_capability(
        CapabilitySpec(
            name="foo",
            kind=CapabilityKind.COMPOSITE,
            source=CapabilitySource.SYNTHESIZED,
            status=CapabilityStatus.PROBATIONARY,
        )
    )
    learner = Learner(mem, Settings(llm_provider="scripted"))
    _learn_once(learner, mem, StepStatus.SUCCESS)
    _learn_once(learner, mem, StepStatus.SUCCESS)
    assert mem.capability.get_capability("foo").status == CapabilityStatus.TRUSTED


def test_real_failure_demotes_and_does_not_promote():
    mem = Memory(":memory:")
    mem.capability.save_capability(
        CapabilitySpec(
            name="foo",
            kind=CapabilityKind.COMPOSITE,
            source=CapabilitySource.SYNTHESIZED,
            status=CapabilityStatus.TRUSTED,
        )
    )
    learner = Learner(mem, Settings(llm_provider="scripted"))
    _learn_once(learner, mem, StepStatus.FAILED)
    assert mem.capability.get_capability("foo").status == CapabilityStatus.DEMOTED
