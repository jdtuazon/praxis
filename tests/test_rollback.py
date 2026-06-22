"""Partial failure must never silently half-complete; rollback is best-effort
compensation with an explicit reversibility taxonomy."""

from conftest import make_agent

from praxis.memory import Memory
from praxis.models import ExecutionStatus, StepStatus
from praxis.platform.fake import FakeLinear


def test_partial_failure_triggers_compensation_and_flags_irreversible():
    fake = FakeLinear()
    agent = make_agent(Memory(":memory:"), fake)
    report = agent.run(
        "Triage ENG-3: move it to In Progress, comment 'Picked up for this sprint', and assign it to Dave"
    )
    # The assign fails (Dave doesn't exist) → required step fails → rollback.
    assert report.status == ExecutionStatus.ROLLED_BACK
    assert report.rollback_performed

    # reversible effect (the state change) was compensated …
    assert any("ENG-3" in r or "stateId" in r for r in report.rollback_steps)
    rolled = [s for s in report.steps if s.status == StepStatus.ROLLED_BACK]
    assert rolled, "the successful state change should be rolled back"

    # … the irreversible effect (the posted comment) is surfaced, NOT swallowed.
    assert any("comment" in m.lower() for m in report.manual_cleanup_required)

    # post-condition: the issue was actually reverted to its original (backlog) state.
    eng3 = next(i for i in fake.store["issues"] if i["identifier"] == "ENG-3")
    state = next(s for s in fake.store["states"] if s["id"] == eng3["stateId"])
    assert state["type"] == "backlog"


def test_failed_step_skips_dependents_not_silently_pressing_on():
    fake = FakeLinear()
    report = make_agent(Memory(":memory:"), fake).run(
        "Triage ENG-3: move it to In Progress, comment 'x', and assign it to Dave"
    )
    statuses = {s.intent: s.status for s in report.steps}
    assert any(st == StepStatus.FAILED for st in statuses.values())
    # the dependent assignment step is skipped, not attempted blindly
    assert any(st == StepStatus.SKIPPED for st in statuses.values())
