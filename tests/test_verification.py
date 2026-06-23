"""Constraint verification policies are consumed, not decorative.

A cached entity under VERIFY_ON_READ is re-resolved (a non-saving call) rather
than trusted blindly; the default TRUST policy reuses it (a saving)."""

from conftest import make_agent

from praxis.agents.executor import _entity_key
from praxis.memory import Memory
from praxis.models import Constraint, ConstraintKind, VerificationPolicy
from praxis.platform.fake import FakeLinear


def _find_team_step(report):
    return next(s for s in report.steps if s.capability == "find_team")


def test_trust_policy_reuses_cache_but_verify_on_read_reresolves():
    mem = Memory(":memory:")
    instr = "Create a high-priority bug titled 'Boom' in Engineering"
    make_agent(mem, FakeLinear()).run(instr)  # caches find_team(Engineering) as TRUST

    # warm run under TRUST → find_team is served from memory (0 API calls)
    warm = make_agent(mem, FakeLinear()).run(instr)
    assert _find_team_step(warm).api_calls == 0

    # flip the cached entity to VERIFY_ON_READ → it must be re-resolved
    key = _entity_key("find_team", {"name": "Engineering"})
    mem.capability.upsert_constraint(Constraint(
        kind=ConstraintKind.ENTITY_ID, scope="entity", key=key,
        value={"id": "team_eng", "key": "ENG", "name": "Engineering"},
        verification_policy=VerificationPolicy.VERIFY_ON_READ))

    verified = make_agent(mem, FakeLinear()).run(instr)
    step = _find_team_step(verified)
    assert step.api_calls >= 1, "VERIFY_ON_READ must trigger a real re-resolve"
    assert any(p.kind == "reverify" for p in step.provenance)
