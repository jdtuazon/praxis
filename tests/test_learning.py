"""The measurable learning signal, asserted with real numbers + a negative control.

These are the tests that prove the system *learns* rather than *memoizes*:
behaviour changes (a different plan), wasted calls vanish, the change is caused
by a specific memory artifact (wiping it reverts the behaviour), and knowledge
transfers to never-seen related instructions.
"""

from conftest import make_agent

from praxis.memory import Memory
from praxis.models import ExecutionStatus
from praxis.platform.fake import FakeLinear


def test_workflow_rule_is_learned_and_rewrites_the_plan():
    mem = Memory(":memory:")
    cold = make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")
    warm = make_agent(mem, FakeLinear()).run("Mark my in-progress work as completed")

    # COLD: the Done transition fails on the (unknown) workflow rule → 1 wasted call.
    assert cold.wasted_calls == 1
    assert cold.status == ExecutionStatus.PARTIAL

    # WARM: the agent rewrote its plan — it now inserts an estimate step.
    assert warm.wasted_calls == 0
    assert warm.status == ExecutionStatus.SUCCESS
    assert any(s.inserted_by_constraint for s in warm.plan.steps), "plan should be rewritten by the learned rule"
    assert warm.learning.wasted_calls_saved == 1


def test_negative_control_wiping_constraints_reverts_behaviour():
    mem = Memory(":memory:")
    make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")
    warm = make_agent(mem, FakeLinear()).run("Mark my in-progress work as completed")
    assert warm.wasted_calls == 0

    mem.wipe_constraints()  # drop ONLY the learned world-model
    control = make_agent(mem, FakeLinear()).run("Mark my in-progress work as completed")

    # The wasted call returns and the plan no longer inserts the estimate step:
    # the behaviour change was *caused* by the learned constraint, not luck.
    assert control.wasted_calls == 1
    assert not any(s.inserted_by_constraint for s in control.plan.steps)


def test_workflow_rewrite_never_overwrites_a_user_supplied_value():
    """Regression: the inserted estimate step must not clobber an explicit estimate."""
    mem = Memory(":memory:")
    make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")  # learn the rule
    fake = FakeLinear()
    make_agent(mem, fake).run("Mark ENG-1 as done and set the estimate to 5 points")
    eng1 = next(i for i in fake.store["issues"] if i["identifier"] == "ENG-1")
    assert eng1["estimate"] == 5, "user's estimate must survive the rule rewrite"


def test_workflow_rewrite_preserves_a_legitimate_zero_value():
    """Regression: a real estimate of 0 must not be treated as 'unset' and overwritten."""
    mem = Memory(":memory:")
    make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")  # learn the rule
    fake = FakeLinear()
    # ENG-1 already has an estimate of 0 (a legitimate value).
    next(i for i in fake.store["issues"] if i["identifier"] == "ENG-1")["estimate"] = 0
    make_agent(mem, fake).run("Mark ENG-1 as done")
    eng1 = next(i for i in fake.store["issues"] if i["identifier"] == "ENG-1")
    assert eng1["estimate"] == 0, "a legitimate 0 estimate must be preserved, not clobbered with the default"


def test_workflow_rule_is_team_scoped_not_applied_blindly():
    """Regression: a rule learned for Engineering must not mutate a Design issue."""
    mem = Memory(":memory:")
    make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")  # learn rule for team_eng
    fake = FakeLinear()
    report = make_agent(mem, fake).run("Mark DES-1 as done")  # Design has no such rule
    des1 = next(i for i in fake.store["issues"] if i["identifier"] == "DES-1")
    assert des1.get("estimate") is None, "Design issue must not be given an estimate it never required"
    assert report.status == ExecutionStatus.SUCCESS


def test_correctness_postcondition_warm_run_actually_completes_the_issue():
    """Fewer wasted calls must not come at the cost of correctness."""
    mem = Memory(":memory:")
    make_agent(mem, FakeLinear()).run("Move my in-progress issue to Done")
    fake = FakeLinear()
    make_agent(mem, fake).run("Mark my in-progress work as completed")
    # alice's in-progress issue (ENG-1) should now be in a completed state with an estimate.
    eng1 = next(i for i in fake.store["issues"] if i["id"] == "issue_1")
    assert eng1["estimate"] is not None
    state = next(s for s in fake.store["states"] if s["id"] == eng1["stateId"])
    assert state["type"] == "completed"


def test_synthesis_then_transfer_to_related_instruction():
    mem = Memory(":memory:")
    fake = FakeLinear()
    cold = make_agent(mem, fake).run("Roll up all issues into a triage digest grouped by priority")
    transfer = make_agent(mem, fake).run("Create a digest of issues grouped by assignee")

    assert cold.synthesized_capabilities == ["issue_digest"]
    # the related instruction pays NO synthesis cost — it reuses the capability
    assert transfer.synthesized_capabilities == []
    assert transfer.total_llm_calls < cold.total_llm_calls
    assert transfer.total_api_calls < cold.total_api_calls
    assert transfer.learning.mode == "transfer"
    # both digests were actually written
    assert len(fake.store["documents"]) == 2


def test_exact_repeat_reuses_plan_and_skips_planning_llm():
    mem = Memory(":memory:")
    instr = "Create a high-priority bug titled 'Login times out' in Engineering"
    cold = make_agent(mem, FakeLinear()).run(instr)
    warm = make_agent(mem, FakeLinear()).run(instr)
    assert warm.plan.source.value == "reused"
    assert warm.total_llm_calls == 0, "an exact repeat should not call the planner LLM again"
    assert warm.total_api_calls <= cold.total_api_calls


def test_synthesized_capability_promoted_after_proven():
    mem = Memory(":memory:")
    fake = FakeLinear()
    for _ in range(3):
        make_agent(mem, fake).run("Roll up all issues into a triage digest grouped by priority")
    spec = mem.capability.get_capability("issue_digest")
    assert spec.status.value == "trusted", "a synthesized capability should be promoted after repeated success"
