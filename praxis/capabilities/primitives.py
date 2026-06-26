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

from typing import Any

from ..models import (
    AppliedEffect,
    CapabilityKind,
    CapabilitySource,
    CapabilitySpec,
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
        raise PlatformError(
            f"missing required argument(s): {', '.join(missing)}", code="INVALID_INPUT"
        )


# ── transport portability ────────────────────────────────────────────────────
# FakeLinear ships a *simplified* filter/input schema (flat `teamId`, an
# `includeArchived` filter field, container-less documents). Real Linear uses
# nested comparator filters and requires a document container. These helpers let
# the builtins stay portable: offline behaviour is untouched (the deterministic
# ScriptedLLM already emits the flat shape FakeLinear understands), while live
# calls are translated to the real Linear schema.
def _is_live(ctx: ExecutionContext) -> bool:
    return type(getattr(ctx.client, "_t", None)).__name__ != "FakeLinear"


_STATE_TYPE_ALIASES = {
    "in-progress": "started",
    "in progress": "started",
    "inprogress": "started",
    "started": "started",
    "doing": "started",
    "in-review": "started",
    "in review": "started",
    "done": "completed",
    "completed": "completed",
    "complete": "completed",
    "todo": "unstarted",
    "to-do": "unstarted",
    "unstarted": "unstarted",
    "backlog": "backlog",
    "canceled": "canceled",
    "cancelled": "canceled",
}


def _parse_filter_string(s: str) -> dict:
    """Best-effort parse of a loose 'key:value' filter string an LLM might emit,
    e.g. 'state:in-progress assignee:me' -> a flat filter dict."""
    flat: dict[str, Any] = {}
    for tok in s.replace(",", " ").split():
        if ":" not in tok:
            continue
        k, _, v = tok.partition(":")
        k, v = k.strip().lower(), v.strip().lower()
        if k in ("assignee", "assigneeid", "assigned"):
            if v in ("me", "@me", "self", "viewer"):
                flat["assigneeIsMe"] = True
            elif v in ("none", "null", "nobody", "unassigned"):
                flat["assigneeIsNull"] = True
            else:
                flat["assigneeId"] = v
        elif k in ("state", "status", "statetype"):
            flat["stateType"] = _STATE_TYPE_ALIASES.get(v, v)
        elif k in ("team", "teamid"):
            flat["teamId"] = v
        elif k in ("priority", "prio"):
            try:
                flat["priority"] = int(v)
            except ValueError:
                pass
    return flat


def _to_linear_issue_filter(f: Any) -> dict:
    """Translate a flat/loose/nested filter into real Linear's nested IssueFilter."""
    if f is None:
        return {}
    if isinstance(f, str):
        f = _parse_filter_string(f)
    if not isinstance(f, dict):
        return {}
    out: dict[str, Any] = {}
    flat: dict[str, Any] = {}
    for k, v in f.items():
        # already-nested comparator shapes pass straight through
        if k in ("team", "assignee", "state", "labels", "creator", "project") and isinstance(
            v, dict
        ):
            out[k] = v
        else:
            flat[k] = v
    if flat.get("teamId"):
        out["team"] = {"id": {"eq": flat["teamId"]}}
    if flat.get("assigneeIsMe") is True:
        out["assignee"] = {"isMe": {"eq": True}}
    elif flat.get("assigneeIsNull") is True:
        out["assignee"] = {"null": True}
    elif flat.get("assigneeIsNull") is False:
        out["assignee"] = {"null": False}
    elif flat.get("assigneeId"):
        out["assignee"] = {"id": {"eq": flat["assigneeId"]}}
    if flat.get("stateId"):
        out.setdefault("state", {})["id"] = {"eq": flat["stateId"]}
    if flat.get("stateType"):
        out.setdefault("state", {})["type"] = {"eq": flat["stateType"]}
    if flat.get("priority") is not None and "priority" not in out:
        out["priority"] = {"eq": flat["priority"]}
    # `includeArchived` is a top-level arg on issues(...), never a filter field.
    return out


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
    # NOTE: real Linear's WorkflowStateFilter has no `teamId` field (it nests as
    # `team: { id: { eq } }`), while FakeLinear's simplified schema uses `teamId`.
    # To stay portable across both transports we fetch unfiltered and filter the
    # (small) set client-side by the resolved `team.id`.
    q = "query{ workflowStates{ nodes { id name type team { id } } } }"
    nodes = ctx.client.execute(q)["workflowStates"]["nodes"]
    return [s for s in nodes if (s.get("team") or {}).get("id") == teamId]


def find_workflow_state(
    ctx: ExecutionContext,
    *,
    teamId: str,
    name: str | None = None,
    type: str | None = None,
    **_,
) -> dict:
    states = list_workflow_states(ctx, teamId=teamId)
    if name:
        for s in states:
            if s["name"].lower() == name.lower():
                return s
    if type:
        for s in states:
            if s["type"] == type:
                return s
    raise PlatformError(
        f"No workflow state name={name} type={type} in team {teamId}", code="ENTITY_NOT_FOUND"
    )


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


def query_issues(ctx: ExecutionContext, *, filter: dict | None = None, **_) -> list:
    q = "query($f: IssueFilter){ issues(filter:$f){ nodes {" + _ISSUE_FIELDS + "} } }"
    # Live Linear needs nested comparator filters; FakeLinear keeps the flat shape
    # its deterministic planner emits. Normalise only on the live transport.
    f = _to_linear_issue_filter(filter) if _is_live(ctx) else (filter or {})
    return ctx.client.execute(q, {"f": f})["issues"]["nodes"]


def get_issue(ctx: ExecutionContext, *, id: str, **_) -> dict | None:
    q = "query($id: String!){ issue(id:$id){" + _ISSUE_FIELDS + "} }"
    return ctx.client.execute(q, {"id": id})["issue"]


def find_issue(ctx: ExecutionContext, *, identifier: str, **_) -> dict:
    # NOTE: `includeArchived` is NOT a field of real Linear's IssueFilter (it is a
    # top-level arg on `issues(...)`). Querying with an empty filter is portable
    # across real Linear and FakeLinear and covers all active issues.
    for issue in query_issues(ctx, filter=None):
        if issue["identifier"].lower() == identifier.lower():
            return issue
    raise PlatformError(f"No issue with identifier '{identifier}'", code="ENTITY_NOT_FOUND")


# ── write primitives ─────────────────────────────────────────────────────────
def create_issue(ctx: ExecutionContext, **a) -> dict:
    _required(a, "teamId", "title")
    inp = {
        k: a[k]
        for k in (
            "teamId",
            "title",
            "description",
            "priority",
            "estimate",
            "stateId",
            "assigneeId",
            "labelIds",
        )
        if a.get(k) is not None
    }
    if ctx.dry_run:
        return {"_dry_run": True, "input": inp}
    q = (
        "mutation($input: IssueCreateInput!){ issueCreate(input:$input){ success issue {"
        + _ISSUE_FIELDS
        + "} } }"
    )
    issue = ctx.client.execute(q, {"input": inp})["issueCreate"]["issue"]
    ctx.record_effect(
        AppliedEffect(
            step_index=-1,
            description=f"created issue {issue['identifier']}",
            reversibility=Reversibility.ARCHIVE_ONLY,
            compensating_capability="archive_issue",
            compensating_args={"id": issue["id"]},
        )
    )
    return issue


def update_issue(ctx: ExecutionContext, *, id: str, **a) -> dict:
    fields = {
        k: a[k]
        for k in (
            "title",
            "description",
            "priority",
            "estimate",
            "stateId",
            "assigneeId",
            "labelIds",
        )
        if a.get(k) is not None
    }
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
                    prior["assigneeId"] = (
                        before["assignee"]["id"] if before.get("assignee") else None
                    )
                else:
                    prior[k] = before.get(k)
    q = (
        "mutation($id: String!, $input: IssueUpdateInput!){ issueUpdate(id:$id, input:$input){ success issue {"
        + _ISSUE_FIELDS
        + "} } }"
    )
    issue = ctx.client.execute(q, {"id": id, "input": fields})["issueUpdate"]["issue"]
    if prior:
        ctx.record_effect(
            AppliedEffect(
                step_index=-1,
                description=f"updated {issue['identifier']} ({', '.join(fields)})",
                reversibility=Reversibility.REVERSIBLE,
                compensating_capability="update_issue",
                compensating_args={"id": id, **prior},
            )
        )
    return issue


def archive_issue(ctx: ExecutionContext, *, id: str, **_) -> dict:
    if ctx.dry_run:
        return {"_dry_run": True, "id": id}
    res = ctx.client.execute(
        "mutation($id: String!){ issueArchive(id:$id){ success } }", {"id": id}
    )
    ctx.record_effect(
        AppliedEffect(
            step_index=-1,
            description=f"archived issue {id}",
            reversibility=Reversibility.REVERSIBLE,
            compensating_capability="unarchive_issue",
            compensating_args={"id": id},
        )
    )
    return res["issueArchive"]


def unarchive_issue(ctx: ExecutionContext, *, id: str, **_) -> dict:
    if ctx.dry_run:
        return {"_dry_run": True, "id": id}
    return ctx.client.execute(
        "mutation($id: String!){ issueUnarchive(id:$id){ success } }", {"id": id}
    )["issueUnarchive"]


def add_comment(ctx: ExecutionContext, *, issueId: str, body: str, **_) -> dict:
    _required({"issueId": issueId, "body": body}, "issueId", "body")
    if ctx.dry_run:
        return {"_dry_run": True, "issueId": issueId}
    q = "mutation($input: CommentCreateInput!){ commentCreate(input:$input){ success comment { id } } }"
    res = ctx.client.execute(q, {"input": {"issueId": issueId, "body": body}})
    ctx.record_effect(
        AppliedEffect(
            step_index=-1,
            description=f"commented on {issueId} (notification sent)",
            reversibility=Reversibility.IRREVERSIBLE,  # a sent notification cannot be unsent
        )
    )
    return res["commentCreate"]


def create_document(
    ctx: ExecutionContext, *, title: str, content: str, projectId: str | None = None, **_
) -> dict:
    _required({"title": title, "content": content}, "title", "content")
    if ctx.dry_run:
        return {"_dry_run": True, "title": title, "content_len": len(content or "")}
    inp = {"title": title, "content": content}
    if projectId:
        inp["projectId"] = projectId
    elif _is_live(ctx):
        # Real Linear requires exactly one container (project/team/issue/...);
        # FakeLinear accepts a standalone document. Anchor live docs to a team.
        teams = list_teams(ctx)
        if teams:
            inp["teamId"] = teams[0]["id"]
    q = "mutation($input: DocumentCreateInput!){ documentCreate(input:$input){ success document { id title url content } } }"
    res = ctx.client.execute(q, {"input": inp})
    ctx.record_effect(
        AppliedEffect(
            step_index=-1,
            description=f"created document '{title}'",
            reversibility=Reversibility.IRREVERSIBLE,  # FakeLinear/Linear have no document delete here
        )
    )
    return res["documentCreate"]["document"]


# ── spec definitions ──────────────────────────────────────────────────────────
def _spec(name, desc, schema, *, side_effecting=False, inverse=None) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        kind=CapabilityKind.GRAPHQL,
        source=CapabilitySource.BUILTIN,
        status=CapabilityStatus.BUILTIN,
        description=desc,
        input_schema=schema,
        side_effecting=side_effecting,
        inverse_capability=inverse,
    )


BUILTINS: list[tuple[CapabilitySpec, Any]] = [
    (_spec("list_teams", "List all teams.", {}), list_teams),
    (_spec("find_team", "Resolve a team by name or key.", {"name": "string"}), find_team),
    (
        _spec("list_workflow_states", "List a team's workflow states.", {"teamId": "string"}),
        list_workflow_states,
    ),
    (
        _spec(
            "find_workflow_state",
            "Resolve a workflow state by name or type within a team.",
            {"teamId": "string", "name": "string?", "type": "string?"},
        ),
        find_workflow_state,
    ),
    (_spec("list_users", "List workspace users.", {}), list_users),
    (
        _spec("find_user", "Resolve a user by name/displayName/email.", {"name": "string"}),
        find_user,
    ),
    (_spec("viewer", "Get the authenticated user (resolves 'me').", {}), viewer),
    (
        _spec("query_issues", "Query issues with an optional filter.", {"filter": "IssueFilter?"}),
        query_issues,
    ),
    (_spec("get_issue", "Fetch a single issue by id.", {"id": "string"}), get_issue),
    (
        _spec(
            "find_issue",
            "Resolve an issue by its identifier (e.g. ENG-3).",
            {"identifier": "string"},
        ),
        find_issue,
    ),
    (
        _spec(
            "create_issue",
            "Create an issue.",
            {
                "teamId": "string",
                "title": "string",
                "description": "string?",
                "priority": "int?",
                "estimate": "int?",
                "stateId": "string?",
                "assigneeId": "string?",
                "labelIds": "list?",
            },
            side_effecting=True,
            inverse="archive_issue",
        ),
        create_issue,
    ),
    (
        _spec(
            "update_issue",
            "Update fields on an issue.",
            {
                "id": "string",
                "title": "string?",
                "description": "string?",
                "priority": "int?",
                "estimate": "int?",
                "stateId": "string?",
                "assigneeId": "string?",
                "labelIds": "list?",
            },
            side_effecting=True,
            inverse="update_issue",
        ),
        update_issue,
    ),
    (
        _spec(
            "archive_issue",
            "Archive an issue.",
            {"id": "string"},
            side_effecting=True,
            inverse="unarchive_issue",
        ),
        archive_issue,
    ),
    (
        _spec("unarchive_issue", "Unarchive an issue.", {"id": "string"}, side_effecting=True),
        unarchive_issue,
    ),
    (
        _spec(
            "add_comment",
            "Add a comment to an issue.",
            {"issueId": "string", "body": "string"},
            side_effecting=True,
        ),
        add_comment,
    ),
    (
        _spec(
            "create_document",
            "Create a document/page.",
            {"title": "string", "content": "string", "projectId": "string?"},
            side_effecting=True,
        ),
        create_document,
    ),
]


def register_builtins(registry: CapabilityRegistry, memory=None) -> None:
    """Register all builtins into the registry (and record specs in memory for visibility)."""
    for spec, func in BUILTINS:
        registry.register(Capability(spec=spec, func=func))
        if memory is not None:
            memory.capability.save_capability(spec)
