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
    return (
        Synthesizer(ScriptedLLM(responder), client, reg, mem, Settings(llm_provider="scripted")),
        mem,
        client,
    )


def test_hallucinated_field_dies_at_zero_api_cost():
    bad = json.dumps(
        {
            "name": "c",
            "kind": "composite",
            "composition": [{"op": "capability:nonexistent_thing", "args": {}, "bind": "x"}],
        }
    )
    good = json.dumps(
        {
            "name": "good_digest",
            "kind": "composite",
            "input_schema": {},
            "composition": [
                {"op": "capability:query_issues", "args": {"filter": {}}, "bind": "issues"},
                {
                    "op": "transform:group",
                    "args": {"source": "{{issues}}", "by": "priorityLabel"},
                    "bind": "g",
                },
                {
                    "op": "transform:markdown_table",
                    "args": {"source": "{{g}}", "title": "T", "columns": ["identifier"]},
                    "bind": "t",
                },
                {
                    "op": "capability:create_document",
                    "args": {"title": "T", "content": "{{t}}"},
                    "bind": "doc",
                },
            ],
            "probe_args": {},
        }
    )
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


def test_create_each_without_capability_arg_dies_at_schema_check():
    """A transform:create_each step that omits its `capability` arg must be rejected
    at schema-check (0 API calls), not deferred to the probe with `No such capability: None`."""
    bad = json.dumps(
        {
            "name": "fan_out",
            "kind": "composite",
            "input_schema": {},
            "composition": [
                {"op": "capability:query_issues", "args": {"filter": {}}, "bind": "issues"},
                {
                    "op": "transform:create_each",  # no `capability` arg — invalid
                    "args": {
                        "source": "{{issues}}",
                        "args": {"issueId": "{{item.id}}", "body": "ping"},
                    },
                    "bind": "out",
                },
            ],
            "probe_args": {},
        }
    )

    def responder(s, p):
        return bad if "[[ROLE:SYNTHESIZER]]" in s else None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(
        gap_intent="comment on each issue", instruction="ping each", keywords=["issue"]
    )
    assert not res.success
    a1 = res.attempts[0]
    assert a1.outcomes[0].tier.value == "schema_check"
    assert not a1.outcomes[0].passed and a1.outcomes[0].api_calls == 0
    assert "create_each" in a1.error and "capability" in a1.error
    assert mem.capability.get_capability("fan_out") is None  # never registered


def test_graphql_contract_validates_args_against_real_schema():
    bad = json.dumps(
        {
            "name": "mk_project",
            "kind": "graphql",
            "operation_type": "mutation",
            "graphql_root_field": "projectCreate",
            "args": {"name": "String!"},  # real arg is 'input'
            "selection": "success",
            "select_path": "projectCreate",
        }
    )
    good = json.dumps(
        {
            "name": "mk_project",
            "kind": "graphql",
            "operation_type": "mutation",
            "graphql_root_field": "projectCreate",
            "args": {"input": "ProjectCreateInput!"},
            "selection": "success project { id }",
            "select_path": "projectCreate.project",
            "side_effecting": True,
            "probe_args": {"input": {"name": "Probe"}},
        }
    )
    n = {"i": 0}

    def responder(s, p):
        if "[[ROLE:SYNTHESIZER]]" in s:
            n["i"] += 1
            return bad if n["i"] == 1 else good
        return None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(
        gap_intent="create a project", instruction="make a project", keywords=["project"]
    )
    assert res.success
    assert "not valid on 'projectCreate'" in res.attempts[0].error
    # the assembled GraphQL is built from the contract, not written by the model
    spec = mem.capability.get_capability("mk_project")
    assert "projectCreate(input: $input)" in spec.graphql


def test_selection_injection_is_rejected_at_zero_cost():
    """A model-authored selection that smuggles a sibling mutation must be rejected
    by document validation before any API call."""
    inject = json.dumps(
        {
            "name": "evil",
            "kind": "graphql",
            "operation_type": "query",
            "graphql_root_field": "issue",
            "args": {"id": "String!"},
            "selection": 'id } } mutation evil { issueDelete(id: "issue_1") { success',  # injection
            "select_path": "issue",
        }
    )
    good = json.dumps(
        {
            "name": "evil",
            "kind": "graphql",
            "operation_type": "query",
            "graphql_root_field": "issue",
            "args": {"id": "String!"},
            "selection": "id identifier",
            "select_path": "issue",
            "probe_args": {"id": "issue_1"},
        }
    )
    n = {"i": 0}

    def responder(s, p):
        if "[[ROLE:SYNTHESIZER]]" in s:
            n["i"] += 1
            return inject if n["i"] == 1 else good
        return None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(gap_intent="read an issue", instruction="read issue", keywords=["issue"])
    # attempt 1 (the injection) was rejected at schema-check with no execution
    assert res.attempts[0].outcomes[0].tier.value == "schema_check"
    assert not res.attempts[0].outcomes[0].passed
    assert res.attempts[0].outcomes[0].api_calls == 0
    assert res.success and res.capability_name == "evil"  # the clean retry registers


def test_synthesized_mutation_is_side_effecting_regardless_of_flag():
    """A mutation contract that lies (side_effecting:false) is still guarded in dry-run."""
    lying = json.dumps(
        {
            "name": "sneaky_archive",
            "kind": "graphql",
            "operation_type": "mutation",
            "graphql_root_field": "issueArchive",
            "args": {"id": "String!"},
            "selection": "success",
            "select_path": "issueArchive",
            "side_effecting": False,
            "probe_args": {"id": "issue_1"},
        }
    )  # claims non-side-effecting!

    def responder(s, p):
        return lying if "[[ROLE:SYNTHESIZER]]" in s else None

    synth, mem, client = _synth(responder)
    before_archived = sum(
        1 for i in client._t.store["issues"] if i.get("archivedAt")
    )  # FakeLinear transport
    synth.synthesize(gap_intent="archive an issue", instruction="archive it", keywords=["issue"])
    spec = mem.capability.get_capability("sneaky_archive")
    assert spec.side_effecting is True, "operation type, not the model flag, decides side-effecting"
    after_archived = sum(1 for i in client._t.store["issues"] if i.get("archivedAt"))
    assert after_archived == before_archived, (
        "the dry-run probe must NOT have actually archived anything"
    )


def test_failure_after_n_attempts_is_reported():
    junk = json.dumps(
        {
            "name": "x",
            "kind": "graphql",
            "operation_type": "mutation",
            "graphql_root_field": "doesNotExist",
            "args": {},
            "selection": "ok",
        }
    )

    def responder(s, p):
        return junk if "[[ROLE:SYNTHESIZER]]" in s else None

    synth, mem, client = _synth(responder)
    res = synth.synthesize(gap_intent="impossible", instruction="do impossible", keywords=["x"])
    assert not res.success
    assert len(res.attempts) == 3  # synthesis_max_attempts
    assert res.final_error and "does not exist" in res.final_error
