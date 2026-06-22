"""FakeLinear must ENFORCE what real Linear enforces (it is not a flattering mock)."""

import pytest

from praxis.platform.base import PlatformError
from praxis.platform.fake import FakeLinear
from praxis.platform.linear.client import LinearClient


@pytest.fixture
def client():
    return LinearClient(FakeLinear())


def test_introspection_works(client):
    sdl = client.introspect_sdl()
    assert "type Mutation" in sdl and "issueArchive" in sdl and "documentCreate" in sdl


def test_query_with_filter_and_relations(client):
    data = client.execute(
        "query{ issues(filter:{assigneeIsNull:true}){ nodes { identifier assignee { id } state { type } } } }"
    )
    nodes = data["issues"]["nodes"]
    assert nodes and all(n["assignee"] is None for n in nodes)


def test_priority_enum_validation(client):
    with pytest.raises(PlatformError) as e:
        client.execute("mutation($i: IssueCreateInput!){issueCreate(input:$i){success}}",
                       {"i": {"teamId": "team_eng", "title": "x", "priority": 9}})
    assert e.value.code == "INVALID_INPUT"
    assert e.value.extensions.get("allowed") == {"min": 0, "max": 4}


def test_delete_is_forbidden(client):
    with pytest.raises(PlatformError) as e:
        client.execute('mutation{issueDelete(id:"issue_1"){success}}')
    assert e.value.code == "FORBIDDEN"


def test_workflow_rule_estimate_before_done(client):
    done = "state_eng_completed"
    with pytest.raises(PlatformError) as e:
        client.execute("mutation($id: ID!, $i: IssueUpdateInput!){issueUpdate(id:$id,input:$i){success}}",
                       {"id": "issue_5", "i": {"stateId": done}})
    assert e.value.code == "WORKFLOW_RULE"
    # setting an estimate first lets it through
    client.execute("mutation($id: ID!, $i: IssueUpdateInput!){issueUpdate(id:$id,input:$i){success}}",
                   {"id": "issue_5", "i": {"estimate": 3}})
    r = client.execute("mutation($id: ID!, $i: IssueUpdateInput!){issueUpdate(id:$id,input:$i){success issue{state{type}}}}",
                       {"id": "issue_5", "i": {"stateId": done}})
    assert r["issueUpdate"]["issue"]["state"]["type"] == "completed"


def test_api_calls_counted_at_transport(client):
    client.execute("{ teams { nodes { id } } }")
    client.execute("{ users { nodes { id } } }")
    assert client.api_calls == 2


def test_create_logs_irreversible_side_effect():
    fake = FakeLinear()
    LinearClient(fake).execute("mutation($i: IssueCreateInput!){issueCreate(input:$i){success}}",
                               {"i": {"teamId": "team_eng", "title": "boom"}})
    assert any("notification" in s for s in fake.side_effect_log)
