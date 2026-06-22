"""Builtin (trusted) atomic capabilities — the alphabet the planner composes.

These are hand-written, shipped, and trusted (not synthesized). They are
deliberately *atomic* (resolve one entity, create one issue, post one comment):
anything compound — bulk operations, aggregation, digests — must be *composed*
or *synthesized*, which is where the real synthesis work lives.

Every side-effecting primitive (a) honours `ctx.dry_run` so it can be validated
without mutating, and (b) records an `AppliedEffect` on the run journal with a
reversibility class + compensating action, so rollback is best-effort but real.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import (
    AppliedEffect,
    CapabilitySource,
    CapabilitySpec,
    CapabilityKind,
    CapabilityStatus,
    Reversibility,
)
from ..platform.base import PlatformError
from .registry import Capability, CapabilityRegistry, ExecutionContext


# ── GraphQL fragments ─────────────────────────────────────────────────────────
_ISSUE_FIELDS = """
  id identifier title description priority priorityLabel estimate url archivedAt createdAt
  team { id key name } state { id name type } assignee { id displayName name }
  labels { nodes { id name } } comments { nodes { id } }
"""


def _required(args: dict, *keys: str) -> None:
    missing = [k for k in keys if args.get(k) in (None, "")]
    if missing:
        raise PlatformError(f"missing required argument(s): {', '.join(missing)}", code="INVALID_INPUT")


# ── read primitives ─────────────────────────────────────────────────────────
def list_teams(ctx: ExecutionContext, **a) -> Any:
    return ctx.client.execute("{ teams { nodes { id key name } } }")["teams"]["nodes"]


def find_team(ctx: ExecutionContext, *, name: str, **_) -> dict:
    teams = list_teams(ctx)
    low = name.lower()
    for t in teams:
        if t["name"].lower() == low or t["key"].lower() == low:
            return t
    for t in teams:  # fuzzy contains
        if low in t["name"].lower():
            return t
    raise PlatformError(f"No team matching '{name}'", code="ENTITY_NOT_FOUND")


def list_workflow_states(ctx: ExecutionContext, *, teamId: str, **_) -> list:
    q = "query($f: WorkflowStateFilter){ workflowStates(filter:$f){ nodes { id name type team { id } } } }"
    return ctx.client.execute(q, {"f": {"teamId": teamId}})["workflowStates"]["nodes"]


def find_workflow_state(ctx: ExecutionContext, *, teamId: str, name: Optional[str] = None,
                        type: Optional[str] = None, **_) -> dict:
    states = list_workflow_states(ctx, teamId=teamId)
    if name:
        for s in states:
            if s["name"].lower() == name.lower():
                return s
    if type:
        for s in states:
            if s["type"] == type:
                return s
    raise PlatformError(f"No workflow state name={name} type={type} in team {teamId}", code="ENTITY_NOT_FOUND")


def list_users(ctx: ExecutionContext, **a) -> list:
    return ctx.client.execute("{ users { nodes { id name displayName email } } }")["users"]["nodes"]


def find_user(ctx: ExecutionContext, *, name: str, **_) -> dict:
    users = list_users(ctx)
    low = name.lower()
    for u in users:
        if low in (u["displayName"].lower(), u["name"].lower(), u["email"].lower()):
            return u
    for u in users:
        if low in u["name"].lower() or low in u["displayName"].lower():
            return u
    raise PlatformError(f"No user matching '{name}'", code="ENTITY_NOT_FOUND")


def viewer(ctx: ExecutionContext, **a) -> dict:
    return ctx.client.execute("{ viewer { id name displayName email } }")["viewer"]


def query_issues(ctx: ExecutionContext, *, filter: Optional[dict] = None, **_) -> list:
    q = "query($f: IssueFilter){ issues(filter:$f){ nodes {" + _ISSUE_FIELDS + "} } }"
    return ctx.client.execute(q, {"f": filter or {}})["issues"]["nodes"]


def get_issue(ctx: ExecutionContext, *, id: str, **_) -> Optional[dict]:
    q = "query($id: ID!){ issue(id:$id){" + _ISSUE_FIELDS + "} }"
    return ctx.client.execute(q, {"id": id})["issue"]


# ── write primitives ─────────────────────────────────────────────────────────
def create_issue(ctx: ExecutionContext, **a) -> dict:
    _required(a, "teamId", "title")
    inp = {k: a[k] for k in ("teamId", "title", "description", "priority", "estimate",
                             "stateId", "assigneeId", "labelIds") if a.get(k) is not None}
    if ctx.dry_run:
        return {"_dry_run": True, "input": inp}
    q = "mutation($input: IssueCreateInput!){ issueCreate(input:$input){ success issue {" + _ISSUE_FIELDS + "} } }"
    issue = ctx.client.execute(q, {"input": inp})["issueCreate"]["issue"]
    ctx.record_effect(AppliedEffect(
        step_index=-1, description=f"created issue {issue['identifier']}",
        reversibility=Reversibility.ARCHIVE_ONLY,
        compensating_capability="archive_issue", compensating_args={"id": issue["id"]},
    ))
    return issue


def update_issue(ctx: ExecutionContext, *, id: str, **a) -> dict:
    fields = {k: a[k] for k in ("title", "description", "priority", "estimate",
                                "stateId", "assigneeId", "labelIds") if a.get(k) is not None}
    if ctx.dry_run:
        return {"_dry_run": True, "id": id, "input": fields}
    # Snapshot prior values for reversible compensation (rollback has a real cost).
    prior: dict[str, Any] = {}
    if ctx.settings is None or getattr(ctx.settings, "require_rollback_journal", True):
        before = get_issue(ctx, id=id)
        if before:
            for k in fields:
                if k == "stateId":
                    prior["stateId"] = before["state"]["id"]
                elif k == "assigneeId":
                    prior["assigneeId"] = before["assignee"]["id"] if before.get("assignee") else None
                else:
                    prior[k] = before.get(k)
    q = "mutation($id: ID!, $input: IssueUpdateInput!){ issueUpdate(id:$id, input:$input){ success issue {" + _ISSUE_FIELDS + "} } }"
    issue = ctx.client.execute(q, {"id": id, "input": fields})["issueUpdate"]["issue"]
    if prior:
        ctx.record_effect(AppliedEffect(
            step_index=-1, description=f"updated {issue['identifier']} ({', '.join(fields)})",
            reversibility=Reversibility.REVERSIBLE,
            compensating_capability="update_issue", compensating_args={"id": id, **prior},
        ))
    return issue


def archive_issue(ctx: ExecutionContext, *, id: str, **_) -> dict:
    if ctx.dry_run:
        return {"_dry_run": True, "id": id}
    res = ctx.client.execute("mutation($id: ID!){ issueArchive(id:$id){ success } }", {"id": id})
    ctx.record_effect(AppliedEffect(
        step_index=-1, description=f"archived issue {id}",
        reversibility=Reversibility.REVERSIBLE,
        compensating_capability="unarchive_issue", compensating_args={"id": id},
    ))
    return res["issueArchive"]


def unarchive_issue(ctx: ExecutionContext, *, id: str, **_) -> dict:
    if ctx.dry_run:
        return {"_dry_run": True, "id": id}
    return ctx.client.execute("mutation($id: ID!){ issueUnarchive(id:$id){ success } }", {"id": id})["issueUnarchive"]


def add_comment(ctx: ExecutionContext, *, issueId: str, body: str, **_) -> dict:
    _required({"issueId": issueId, "body": body}, "issueId", "body")
    if ctx.dry_run:
        return {"_dry_run": True, "issueId": issueId}
    q = "mutation($input: CommentCreateInput!){ commentCreate(input:$input){ success comment { id } } }"
    res = ctx.client.execute(q, {"input": {"issueId": issueId, "body": body}})
    ctx.record_effect(AppliedEffect(
        step_index=-1, description=f"commented on {issueId} (notification sent)",
        reversibility=Reversibility.IRREVERSIBLE,  # a sent notification cannot be unsent
    ))
    return res["commentCreate"]


def create_document(ctx: ExecutionContext, *, title: str, content: str, projectId: Optional[str] = None, **_) -> dict:
    _required({"title": title, "content": content}, "title", "content")
    if ctx.dry_run:
        return {"_dry_run": True, "title": title, "content_len": len(content or "")}
    inp = {"title": title, "content": content}
    if projectId:
        inp["projectId"] = projectId
    q = "mutation($input: DocumentCreateInput!){ documentCreate(input:$input){ success document { id title url } } }"
    res = ctx.client.execute(q, {"input": inp})
    ctx.record_effect(AppliedEffect(
        step_index=-1, description=f"created document '{title}'",
        reversibility=Reversibility.IRREVERSIBLE,  # FakeLinear/Linear have no document delete here
    ))
    return res["documentCreate"]["document"]


# ── spec definitions ──────────────────────────────────────────────────────────
def _spec(name, desc, schema, *, side_effecting=False, inverse=None) -> CapabilitySpec:
    return CapabilitySpec(
        name=name, kind=CapabilityKind.GRAPHQL, source=CapabilitySource.BUILTIN,
        status=CapabilityStatus.BUILTIN, description=desc, input_schema=schema,
        side_effecting=side_effecting, inverse_capability=inverse,
    )


BUILTINS: list[tuple[CapabilitySpec, Any]] = [
    (_spec("list_teams", "List all teams.", {}), list_teams),
    (_spec("find_team", "Resolve a team by name or key.", {"name": "string"}), find_team),
    (_spec("list_workflow_states", "List a team's workflow states.", {"teamId": "string"}), list_workflow_states),
    (_spec("find_workflow_state", "Resolve a workflow state by name or type within a team.",
           {"teamId": "string", "name": "string?", "type": "string?"}), find_workflow_state),
    (_spec("list_users", "List workspace users.", {}), list_users),
    (_spec("find_user", "Resolve a user by name/displayName/email.", {"name": "string"}), find_user),
    (_spec("viewer", "Get the authenticated user (resolves 'me').", {}), viewer),
    (_spec("query_issues", "Query issues with an optional filter.", {"filter": "IssueFilter?"}), query_issues),
    (_spec("get_issue", "Fetch a single issue by id.", {"id": "string"}), get_issue),
    (_spec("create_issue", "Create an issue.",
           {"teamId": "string", "title": "string", "description": "string?", "priority": "int?",
            "estimate": "int?", "stateId": "string?", "assigneeId": "string?", "labelIds": "list?"},
           side_effecting=True, inverse="archive_issue"), create_issue),
    (_spec("update_issue", "Update fields on an issue.",
           {"id": "string", "title": "string?", "description": "string?", "priority": "int?",
            "estimate": "int?", "stateId": "string?", "assigneeId": "string?", "labelIds": "list?"},
           side_effecting=True, inverse="update_issue"), update_issue),
    (_spec("archive_issue", "Archive an issue.", {"id": "string"}, side_effecting=True, inverse="unarchive_issue"), archive_issue),
    (_spec("unarchive_issue", "Unarchive an issue.", {"id": "string"}, side_effecting=True), unarchive_issue),
    (_spec("add_comment", "Add a comment to an issue.", {"issueId": "string", "body": "string"}, side_effecting=True), add_comment),
    (_spec("create_document", "Create a document/page.", {"title": "string", "content": "string", "projectId": "string?"}, side_effecting=True), create_document),
]


def register_builtins(registry: CapabilityRegistry, memory=None) -> None:
    """Register all builtins into the registry (and record specs in memory for visibility)."""
    for spec, func in BUILTINS:
        registry.register(Capability(spec=spec, func=func))
        if memory is not None:
            memory.capability.save_capability(spec)
