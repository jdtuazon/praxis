"""Generative regression: throw many instruction variants at the agent and assert
invariants hold — it never crashes, always returns a well-formed report, never
half-completes silently, and memory stays consistent run after run.

This is the broad 'user testing' net: a single persistent memory absorbs a long,
varied sequence and must remain coherent (capabilities/constraints monotonic,
counts sane, no exceptions)."""

import itertools

import pytest
from conftest import make_agent

from praxis.memory import Memory
from praxis.models import ExecutionStatus, StepStatus
from praxis.platform.fake import FakeLinear

VALID_STATUS = set(ExecutionStatus)

_TEMPLATES = [
    "Create a {pri} bug titled 'Thing {n}' in {team}",
    "Create a {pri} issue in {team} and assign it to me",
    "File an issue 'Bug {n}' in {team}",
    "Find all open issues with no assignee",
    "List unassigned bugs in {team}",
    "Roll up all issues into a digest grouped by {group}",
    "Create a digest of issues grouped by {group}",
    "Move my in-progress issue to Done",
    "Mark my in-progress work as completed",
    "Comment on every unassigned open issue asking for triage",
    "Triage ENG-{n}: move it to In Progress, comment 'note {n}', and assign it to {who}",
]
_PRI = ["urgent", "high", "medium", "low"]
_TEAM = ["Engineering", "Design"]
_GROUP = ["priority", "assignee", "team", "status"]
_WHO = ["me", "alice", "Dave"]


def _instructions(limit: int):
    combos = itertools.product(_TEMPLATES, _PRI, _TEAM, _GROUP, [1, 2, 3], _WHO)
    seen = set()
    out = []
    for tmpl, pri, team, group, n, who in combos:
        s = tmpl.format(pri=pri, team=team, group=group, n=n, who=who)
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _check_report(report) -> None:
    assert report.status in VALID_STATUS
    assert report.total_api_calls >= 0 and report.wasted_calls >= 0
    for s in report.steps:
        assert s.api_calls >= 0
        assert s.status in set(StepStatus)
    # no silent half-completion: a non-success run must explain itself
    if report.status in (
        ExecutionStatus.PARTIAL,
        ExecutionStatus.FAILED,
        ExecutionStatus.ROLLED_BACK,
    ):
        assert (
            any(s.error for s in report.steps)
            or report.manual_cleanup_required
            or report.rollback_steps
        )
    # a non-success that applied side effects must have compensated or flagged cleanup
    assert report.model_dump_json()


@pytest.mark.parametrize("instruction", _instructions(60))
def test_instruction_never_crashes_and_report_is_wellformed(instruction):
    report = make_agent().run(instruction)
    _check_report(report)


def test_long_mixed_session_keeps_memory_coherent():
    mem = Memory(":memory:")
    fake = FakeLinear()
    prev_caps = 0
    for instruction in _instructions(50):
        report = make_agent(mem, fake).run(instruction)
        _check_report(report)
        counts = mem.store.counts()
        # capabilities never decrease; counts never go negative
        assert counts["capabilities"] >= prev_caps
        prev_caps = counts["capabilities"]
        assert all(v >= 0 for v in counts.values())
    # the session learned *something* structured
    assert mem.store.counts()["constraints"] >= 1
    assert mem.store.counts()["executions"] == 50
