"""Memory is structured knowledge — persists, accessors work, compaction summarises."""

from praxis.memory import Memory
from praxis.models import (
    Constraint,
    ConstraintKind,
    ConstraintOrigin,
)


def test_constraint_accessors_round_trip():
    m = Memory(":memory:")
    m.capability.upsert_constraint(
        Constraint(kind=ConstraintKind.ENTITY_ID, scope="team", key="Engineering", value="team_eng")
    )
    m.capability.upsert_constraint(
        Constraint(
            kind=ConstraintKind.ENUM, scope="field", key="issue.priority", value={"range": [0, 4]}
        )
    )
    m.capability.upsert_constraint(
        Constraint(
            kind=ConstraintKind.PERMISSION, scope="mutation", key="issueDelete", value="forbidden"
        )
    )
    assert m.capability.cached_entity_id("team", "Engineering") == "team_eng"
    assert m.capability.enum_constraint("issue.priority").value["range"] == [0, 4]
    assert m.capability.permission_forbidden("issueDelete") is True


def test_constraint_upsert_is_idempotent():
    m = Memory(":memory:")
    for _ in range(3):
        m.capability.upsert_constraint(
            Constraint(
                kind=ConstraintKind.ENTITY_ID, scope="team", key="Engineering", value="team_eng"
            )
        )
    assert m.store.counts()["constraints"] == 1


def test_only_runtime_learned_tagged_as_learning():
    m = Memory(":memory:")
    m.capability.upsert_constraint(
        Constraint(
            kind=ConstraintKind.WORKFLOW_RULE,
            scope="team",
            key="t",
            value={"requires": "estimate"},
            rewrites_plan=True,
            origin=ConstraintOrigin.RUNTIME_LEARNED,
        )
    )
    c = m.capability.get_constraints(kind=ConstraintKind.WORKFLOW_RULE)[0]
    assert c.origin == ConstraintOrigin.RUNTIME_LEARNED and c.rewrites_plan


def test_memory_persists_across_connections(tmp_path):
    path = tmp_path / "mem.sqlite"
    m1 = Memory(path)
    m1.capability.upsert_constraint(
        Constraint(kind=ConstraintKind.ENTITY_ID, scope="team", key="Engineering", value="team_eng")
    )
    m1.close()
    m2 = Memory(path)  # reopen — survives across "sessions"
    assert m2.capability.cached_entity_id("team", "Engineering") == "team_eng"


def test_snapshot_and_diff():
    m = Memory(":memory:")
    before = m.snapshot()
    m.capability.upsert_constraint(
        Constraint(kind=ConstraintKind.ENTITY_ID, scope="team", key="E", value="t")
    )
    after = m.snapshot()
    diff = Memory.diff(before, after)
    assert any("constraint" in line for line in diff.lines)
