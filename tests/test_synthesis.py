"""Synthesis must be real: reason → typed contract → schema-validate → test → register."""

import json

from praxis.capabilities import CapabilityRegistry, Synthesizer, register_builtins
from praxis.config import Settings
from praxis.llm.scripted import ScriptedLLM
from praxis.memory import Memory
from praxis.platform.fake import FakeLinear
from praxis.platform.linear.client import LinearClient


def _synth(responder):
    reg = CapabilityRegistry()
    mem = Memory(":memory:")
    register_builtins(reg, mem)
    client = LinearClient(FakeLinear())
    return Synthesizer(ScriptedLLM(responder), client, reg, mem, Settings(llm_provider="scripted")), mem, client


def test_hallucinated_field_dies_at_zero_api_cost():
    bad = json.dumps({"name": "c", "kind": "composite", "composition": [
        {"op": "capability:nonexistent_thing", "args": {}, "bind": "x"}]})
    good = json.dumps({"name": "good_digest", "kind": "composite", "input_schema": {},
        "composition": [
            {"op": "capability:query_issues", "args": {"filter": {}}, "bind": "issues"},
            {"op": "transform:group", "args": {"source": "{{issues}}", "by": "priorityLabel"}, "bind": "g"},
            {"op": "transform:markdown_table", "args": {"source": "{{g}}", "title": "T", "columns": ["identifier"]}, "bind": "t"},
            {"op": "capability:create_document", "args": {"title": "T", "content": "{{t}}"}, "bind": "doc"}],
        "probe_args": {}})
    n = {"i": 0}

    def responder(s, p):
        if "[[ROLE:SYNTHESIZER]]" in s:
            n["i"] += 1
            return bad if n["i"] == 1 else good
        return None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(gap_intent="build a digest", instruction="digest", keywords=["issue"])
    assert res.success and res.capability_name == "good_digest"
    assert len(res.attempts) == 2
    # attempt 1 failed at schema-check with ZERO api calls (no hallucinated execution)
    a1 = res.attempts[0]
    assert not a1.outcomes[0].passed and a1.outcomes[0].api_calls == 0
    assert "unknown capability" in a1.error
    # registered probationary with provenance
    spec = mem.capability.get_capability("good_digest")
    assert spec.status.value == "probationary" and spec.schema_hash


def test_graphql_contract_validates_args_against_real_schema():
    bad = json.dumps({"name": "mk_project", "kind": "graphql", "operation_type": "mutation",
        "graphql_root_field": "projectCreate", "args": {"name": "String!"},  # real arg is 'input'
        "selection": "success", "select_path": "projectCreate"})
    good = json.dumps({"name": "mk_project", "kind": "graphql", "operation_type": "mutation",
        "graphql_root_field": "projectCreate", "args": {"input": "ProjectCreateInput!"},
        "selection": "success project { id }", "select_path": "projectCreate.project",
        "side_effecting": True, "probe_args": {"input": {"name": "Probe"}}})
    n = {"i": 0}

    def responder(s, p):
        if "[[ROLE:SYNTHESIZER]]" in s:
            n["i"] += 1
            return bad if n["i"] == 1 else good
        return None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(gap_intent="create a project", instruction="make a project", keywords=["project"])
    assert res.success
    assert "not valid on 'projectCreate'" in res.attempts[0].error
    # the assembled GraphQL is built from the contract, not written by the model
    spec = mem.capability.get_capability("mk_project")
    assert "projectCreate(input: $input)" in spec.graphql


def test_failure_after_n_attempts_is_reported():
    junk = json.dumps({"name": "x", "kind": "graphql", "operation_type": "mutation",
        "graphql_root_field": "doesNotExist", "args": {}, "selection": "ok"})

    def responder(s, p):
        return junk if "[[ROLE:SYNTHESIZER]]" in s else None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(gap_intent="impossible", instruction="do impossible", keywords=["x"])
    assert not res.success
    assert len(res.attempts) == 3  # synthesis_max_attempts
    assert res.final_error and "does not exist" in res.final_error
