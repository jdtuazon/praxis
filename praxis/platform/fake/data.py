"""Deterministic seed data for the FakeLinear simulation.

Mirrors the shape of a small Linear workspace so the offline test suite and the
`--offline` demo exercise realistic multi-step work (teams, states, assignees,
priorities, unassigned issues to triage, etc.).
"""

from __future__ import annotations

from typing import Any


def seed() -> dict[str, Any]:
    teams = [
        {"id": "team_eng", "key": "ENG", "name": "Engineering"},
        {"id": "team_des", "key": "DES", "name": "Design"},
    ]
    users = [
        {"id": "user_alice", "name": "Alice Reyes", "email": "alice@acme.test", "displayName": "alice"},
        {"id": "user_bob", "name": "Bob Santos", "email": "bob@acme.test", "displayName": "bob"},
        {"id": "user_carol", "name": "Carol Tan", "email": "carol@acme.test", "displayName": "carol"},
    ]
    # type ∈ backlog | unstarted | started | completed | canceled  (mirrors Linear)
    states = []
    for team in teams:
        for name, typ in [
            ("Backlog", "backlog"),
            ("Todo", "unstarted"),
            ("In Progress", "started"),
            ("Done", "completed"),
            ("Canceled", "canceled"),
        ]:
            states.append(
                {
                    "id": f"state_{team['key'].lower()}_{typ}",
                    "name": name,
                    "type": typ,
                    "teamId": team["id"],
                }
            )
    labels = [
        {"id": "label_bug", "name": "Bug", "color": "#e11d48"},
        {"id": "label_feature", "name": "Feature", "color": "#2563eb"},
        {"id": "label_improvement", "name": "Improvement", "color": "#16a34a"},
    ]

    def sid(team_key: str, typ: str) -> str:
        return f"state_{team_key.lower()}_{typ}"

    issues = [
        {
            "id": "issue_1", "identifier": "ENG-1", "title": "Search returns stale results",
            "description": "Cache not invalidated on update.", "priority": 2,
            "teamId": "team_eng", "stateId": sid("ENG", "started"), "assigneeId": "user_alice",
            "labelIds": ["label_bug"], "archivedAt": None,
        },
        {
            "id": "issue_2", "identifier": "ENG-2", "title": "Add dark mode toggle",
            "description": "Users want a dark theme.", "priority": 3,
            "teamId": "team_eng", "stateId": sid("ENG", "unstarted"), "assigneeId": None,
            "labelIds": ["label_feature"], "archivedAt": None,
        },
        {
            "id": "issue_3", "identifier": "ENG-3", "title": "Flaky integration test on CI",
            "description": "test_checkout fails ~10% of runs.", "priority": 1,
            "teamId": "team_eng", "stateId": sid("ENG", "backlog"), "assigneeId": None,
            "labelIds": ["label_bug"], "archivedAt": None,
        },
        {
            "id": "issue_4", "identifier": "ENG-4", "title": "Document the deploy runbook",
            "description": "", "priority": 4,
            "teamId": "team_eng", "stateId": sid("ENG", "unstarted"), "assigneeId": None,
            "labelIds": ["label_improvement"], "archivedAt": None,
        },
        {
            "id": "issue_5", "identifier": "ENG-5", "title": "Memory leak in worker pool",
            "description": "RSS grows under load.", "priority": 1,
            "teamId": "team_eng", "stateId": sid("ENG", "started"), "assigneeId": "user_bob",
            "labelIds": ["label_bug"], "archivedAt": None,
        },
        {
            "id": "issue_6", "identifier": "DES-1", "title": "Refresh onboarding illustrations",
            "description": "", "priority": 3,
            "teamId": "team_des", "stateId": sid("DES", "unstarted"), "assigneeId": None,
            "labelIds": ["label_improvement"], "archivedAt": None,
        },
    ]
    projects = [
        {"id": "project_road", "name": "Q3 Roadmap", "description": "Quarterly plan", "state": "started"},
    ]
    return {
        "teams": teams,
        "users": users,
        "states": states,
        "labels": labels,
        "issues": issues,
        "projects": projects,
        "comments": [],
        "documents": [],
    }
