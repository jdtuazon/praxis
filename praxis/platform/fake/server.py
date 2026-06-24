"""FakeLinear — an in-process GraphQL simulation of a Linear workspace.

Why this exists: the assignment requires real API calls in the *demo*, but a
serious engineering submission also needs deterministic, offline regression
tests that exercise the full agent loop (including capability synthesis, which
reasons over the live schema). FakeLinear is a real `graphql-core` schema, so:

  • introspection works  → the synthesizer reasons over a genuine schema;
  • execution works      → mutations actually mutate an in-memory store;
  • constraints are real → invalid priorities, missing fields, forbidden
    deletes and (optional) rate limits are enforced and surface as the same
    structured GraphQL errors the agent learns from.

It is NOT a mock of individual calls — it is a self-consistent API the agent
discovers and operates exactly as it would the real one. The production path
(`HttpxTransport`) is byte-for-byte identical; only the transport differs.
"""

from __future__ import annotations

import copy
from typing import Any

from graphql import GraphQLError, build_schema, graphql_sync

from .data import seed

SDL = """
schema { query: Query mutation: Mutation }

type Query {
  viewer: User!
  teams(first: Int): TeamConnection!
  team(id: String!): Team
  users(first: Int): UserConnection!
  workflowStates(first: Int, filter: WorkflowStateFilter): WorkflowStateConnection!
  issueLabels(first: Int): IssueLabelConnection!
  issues(first: Int, filter: IssueFilter): IssueConnection!
  issue(id: String!): Issue
  projects(first: Int): ProjectConnection!
  project(id: String!): Project
  documents(first: Int): DocumentConnection!
}

type Mutation {
  issueCreate(input: IssueCreateInput!): IssuePayload!
  issueUpdate(id: String!, input: IssueUpdateInput!): IssuePayload!
  issueArchive(id: String!): IssueArchivePayload!
  issueUnarchive(id: String!): IssueArchivePayload!
  issueDelete(id: String!): IssueDeletePayload!
  commentCreate(input: CommentCreateInput!): CommentPayload!
  projectCreate(input: ProjectCreateInput!): ProjectPayload!
  documentCreate(input: DocumentCreateInput!): DocumentPayload!
}

type PageInfo { hasNextPage: Boolean! endCursor: String }

type User { id: ID! name: String! email: String! displayName: String! }
type UserConnection { nodes: [User!]! pageInfo: PageInfo! }

type Team { id: ID! key: String! name: String! }
type TeamConnection { nodes: [Team!]! pageInfo: PageInfo! }

type WorkflowState { id: ID! name: String! type: String! team: Team! }
type WorkflowStateConnection { nodes: [WorkflowState!]! pageInfo: PageInfo! }
input WorkflowStateFilter { teamId: ID, type: String, name: String }

type IssueLabel { id: ID! name: String! color: String }
type IssueLabelConnection { nodes: [IssueLabel!]! pageInfo: PageInfo! }

type Issue {
  id: ID!
  identifier: String!
  title: String!
  description: String
  priority: Int!
  priorityLabel: String!
  estimate: Int
  url: String!
  archivedAt: String
  createdAt: String!
  team: Team!
  state: WorkflowState!
  assignee: User
  labels: IssueLabelConnection!
  comments: CommentConnection!
}
type IssueConnection { nodes: [Issue!]! pageInfo: PageInfo! }
input IssueFilter {
  teamId: ID
  assigneeId: ID
  assigneeIsNull: Boolean
  stateId: ID
  stateType: String
  priority: Int
  includeArchived: Boolean
}
input IssueCreateInput {
  teamId: ID!
  title: String!
  description: String
  priority: Int
  estimate: Int
  stateId: ID
  assigneeId: ID
  labelIds: [ID!]
}
input IssueUpdateInput {
  title: String
  description: String
  priority: Int
  estimate: Int
  stateId: ID
  assigneeId: ID
  labelIds: [ID!]
}
type IssuePayload { success: Boolean! issue: Issue }
type IssueArchivePayload { success: Boolean! }
type IssueDeletePayload { success: Boolean! }

type Comment { id: ID! body: String! createdAt: String! user: User issue: Issue }
type CommentConnection { nodes: [Comment!]! pageInfo: PageInfo! }
input CommentCreateInput { issueId: ID!, body: String! }
type CommentPayload { success: Boolean! comment: Comment }

type Project { id: ID! name: String! description: String state: String! url: String! }
type ProjectConnection { nodes: [Project!]! pageInfo: PageInfo! }
input ProjectCreateInput { name: String!, description: String, teamIds: [ID!] }
type ProjectPayload { success: Boolean! project: Project }

type Document { id: ID! title: String! content: String! url: String! createdAt: String! }
type DocumentConnection { nodes: [Document!]! pageInfo: PageInfo! }
input DocumentCreateInput { title: String!, content: String!, projectId: ID }
type DocumentPayload { success: Boolean! document: Document }
"""

PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}


def _err(message: str, code: str, **extensions: Any) -> GraphQLError:
    ext = {"code": code, "userPresentableMessage": message, **extensions}
    return GraphQLError(message, extensions=ext)


class FakeLinear:
    """A stateful, deterministic Linear simulation exposed via GraphQL."""

    def __init__(
        self,
        *,
        rate_limit_after: int | None = None,
        forbid_delete: bool = True,
        require_estimate_to_complete: set[str] | None = None,
    ) -> None:
        self._schema = build_schema(SDL)
        self.store = seed()
        self._counter = 100
        self._clock = 1_700_000_000  # deterministic monotonic clock
        # ── simulated constraints / faults ─────────────────────────────────
        self.rate_limit_after = rate_limit_after  # raise RATELIMITED after N writes
        self.forbid_delete = forbid_delete  # issueDelete → FORBIDDEN
        # Workspace policy NOT derivable from the schema: these teams require an
        # estimate before an issue may transition into a completed state. This is
        # the runtime-learned rule that makes the agent *rewrite its plan*.
        self.require_estimate_to_complete = (
            require_estimate_to_complete
            if require_estimate_to_complete is not None
            else {"team_eng"}
        )
        # ── observability for tests ────────────────────────────────────────
        self.calls = 0  # total GraphQL documents executed
        self.op_counts: dict[str, int] = {}  # per-mutation invocation counts
        self.side_effect_log: list[
            str
        ] = []  # notifications/webhooks that would fire (irreversible)
        self._writes = 0

    # ── public transport API ───────────────────────────────────────────────
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        result = graphql_sync(
            self._schema, query, variable_values=variables, root_value=self._root()
        )
        out: dict[str, Any] = {}
        if result.data is not None:
            out["data"] = result.data
        if result.errors:
            out["errors"] = [self._format_error(e) for e in result.errors]
        return out

    @staticmethod
    def _format_error(e: GraphQLError) -> dict[str, Any]:
        d: dict[str, Any] = {"message": e.message}
        if e.path:
            d["path"] = list(e.path)
        if e.extensions:
            d["extensions"] = dict(e.extensions)
        return d

    # ── helpers ──────────────────────────────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def _now(self) -> str:
        self._clock += 7
        # ISO-ish, deterministic
        return f"2026-06-24T00:{(self._clock // 60) % 60:02d}:{self._clock % 60:02d}.000Z"

    def _count_op(self, name: str) -> None:
        self.op_counts[name] = self.op_counts.get(name, 0) + 1

    def _bump_write(self) -> None:
        self._writes += 1
        if self.rate_limit_after is not None and self._writes > self.rate_limit_after:
            raise _err(
                "You have exceeded the rate limit for this resource.",
                "RATELIMITED",
                retryAfter=2,
            )

    def _team(self, tid: str) -> dict | None:
        return next((t for t in self.store["teams"] if t["id"] == tid), None)

    def _user(self, uid: str | None) -> dict | None:
        if not uid:
            return None
        return next((u for u in self.store["users"] if u["id"] == uid), None)

    def _state(self, sid: str) -> dict | None:
        return next((s for s in self.store["states"] if s["id"] == sid), None)

    def _label(self, lid: str) -> dict | None:
        return next((lb for lb in self.store["labels"] if lb["id"] == lid), None)

    def _issue(self, iid: str) -> dict | None:
        return next((i for i in self.store["issues"] if i["id"] == iid), None)

    # ── view builders (resolve relations eagerly into dicts) ─────────────────
    def _team_view(self, t: dict) -> dict:
        return {"id": t["id"], "key": t["key"], "name": t["name"]}

    def _user_view(self, u: dict | None) -> dict | None:
        if not u:
            return None
        return {
            "id": u["id"],
            "name": u["name"],
            "email": u["email"],
            "displayName": u["displayName"],
        }

    def _state_view(self, s: dict) -> dict:
        team = self._team(s["teamId"])
        return {"id": s["id"], "name": s["name"], "type": s["type"], "team": self._team_view(team)}

    def _label_view(self, lb: dict) -> dict:
        return {"id": lb["id"], "name": lb["name"], "color": lb.get("color")}

    def _conn(self, nodes: list) -> dict:
        return {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}

    def _issue_view(self, i: dict) -> dict:
        team = self._team(i["teamId"])
        state = self._state(i["stateId"])
        assignee = self._user(i.get("assigneeId"))
        labels = [
            self._label_view(self._label(lid)) for lid in i.get("labelIds", []) if self._label(lid)
        ]
        comments = [
            self._comment_view(c) for c in self.store["comments"] if c["issueId"] == i["id"]
        ]
        return {
            "id": i["id"],
            "identifier": i["identifier"],
            "title": i["title"],
            "description": i.get("description"),
            "priority": i.get("priority", 0),
            "priorityLabel": PRIORITY_LABELS.get(i.get("priority", 0), "No priority"),
            "estimate": i.get("estimate"),
            "url": f"https://linear.app/acme/issue/{i['identifier']}",
            "archivedAt": i.get("archivedAt"),
            "createdAt": i.get("createdAt", "2026-06-01T00:00:00.000Z"),
            "team": self._team_view(team),
            "state": self._state_view(state),
            "assignee": self._user_view(assignee),
            "labels": self._conn(labels),
            "comments": self._conn(comments),
        }

    def _comment_view(self, c: dict) -> dict:
        return {
            "id": c["id"],
            "body": c["body"],
            "createdAt": c["createdAt"],
            "user": self._user_view(self._user(c.get("userId"))),
            "issue": None,  # avoid cycles; agents don't need it
        }

    def _project_view(self, p: dict) -> dict:
        return {
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description"),
            "state": p.get("state", "planned"),
            "url": f"https://linear.app/acme/project/{p['id']}",
        }

    def _document_view(self, d: dict) -> dict:
        return {
            "id": d["id"],
            "title": d["title"],
            "content": d["content"],
            "url": f"https://linear.app/acme/document/{d['id']}",
            "createdAt": d["createdAt"],
        }

    # ── root resolver map ────────────────────────────────────────────────────
    def _root(self) -> dict:
        return {
            "viewer": lambda info: self._user_view(self.store["users"][0]),
            "teams": lambda info, first=None: self._conn(
                [self._team_view(t) for t in self.store["teams"]]
            ),
            "team": lambda info, id: self._team_view(self._team(id)) if self._team(id) else None,
            "users": lambda info, first=None: self._conn(
                [self._user_view(u) for u in self.store["users"]]
            ),
            "workflowStates": self._r_workflow_states,
            "issueLabels": lambda info, first=None: self._conn(
                [self._label_view(lb) for lb in self.store["labels"]]
            ),
            "issues": self._r_issues,
            "issue": lambda info, id: (
                self._issue_view(self._issue(id)) if self._issue(id) else None
            ),
            "projects": lambda info, first=None: self._conn(
                [self._project_view(p) for p in self.store["projects"]]
            ),
            "project": lambda info, id: next(
                (self._project_view(p) for p in self.store["projects"] if p["id"] == id), None
            ),
            "documents": lambda info, first=None: self._conn(
                [self._document_view(d) for d in self.store["documents"]]
            ),
            # mutations
            "issueCreate": self._m_issue_create,
            "issueUpdate": self._m_issue_update,
            "issueArchive": self._m_issue_archive,
            "issueUnarchive": self._m_issue_unarchive,
            "issueDelete": self._m_issue_delete,
            "commentCreate": self._m_comment_create,
            "projectCreate": self._m_project_create,
            "documentCreate": self._m_document_create,
        }

    # ── query resolvers ────────────────────────────────────────────────────
    def _r_workflow_states(self, info, first=None, filter=None):
        states = self.store["states"]
        f = filter or {}
        if f.get("teamId"):
            states = [s for s in states if s["teamId"] == f["teamId"]]
        if f.get("type"):
            states = [s for s in states if s["type"] == f["type"]]
        if f.get("name"):
            states = [s for s in states if s["name"].lower() == f["name"].lower()]
        return self._conn([self._state_view(s) for s in states])

    def _r_issues(self, info, first=None, filter=None):
        f = filter or {}
        issues = list(self.store["issues"])
        if not f.get("includeArchived"):
            issues = [i for i in issues if not i.get("archivedAt")]
        if f.get("teamId"):
            issues = [i for i in issues if i["teamId"] == f["teamId"]]
        if f.get("assigneeIsNull") is True:
            issues = [i for i in issues if not i.get("assigneeId")]
        if f.get("assigneeIsNull") is False:
            issues = [i for i in issues if i.get("assigneeId")]
        if f.get("assigneeId"):
            issues = [i for i in issues if i.get("assigneeId") == f["assigneeId"]]
        if f.get("stateId"):
            issues = [i for i in issues if i["stateId"] == f["stateId"]]
        if f.get("stateType"):
            issues = [
                i
                for i in issues
                if self._state(i["stateId"]) and self._state(i["stateId"])["type"] == f["stateType"]
            ]
        if f.get("priority") is not None:
            issues = [i for i in issues if i.get("priority") == f["priority"]]
        if first:
            issues = issues[:first]
        return self._conn([self._issue_view(i) for i in issues])

    # ── validation shared by create/update ───────────────────────────────────
    def _validate_issue_input(self, inp: dict, *, creating: bool) -> None:
        if creating:
            if not inp.get("teamId"):
                raise _err("Argument 'teamId' is required.", "INVALID_INPUT", field="teamId")
            if not inp.get("title"):
                raise _err("Argument 'title' is required.", "INVALID_INPUT", field="title")
        if inp.get("teamId") and not self._team(inp["teamId"]):
            raise _err(f"Team '{inp['teamId']}' not found.", "ENTITY_NOT_FOUND", field="teamId")
        if "priority" in inp and inp["priority"] is not None:
            p = inp["priority"]
            if not isinstance(p, int) or p < 0 or p > 4:
                raise _err(
                    "priority must be an integer between 0 (none) and 4 (low).",
                    "INVALID_INPUT",
                    field="priority",
                    allowed={"min": 0, "max": 4},
                )
        if inp.get("stateId") and not self._state(inp["stateId"]):
            raise _err(
                f"Workflow state '{inp['stateId']}' not found.", "ENTITY_NOT_FOUND", field="stateId"
            )
        if inp.get("assigneeId") and not self._user(inp["assigneeId"]):
            raise _err(
                f"User '{inp['assigneeId']}' not found.", "ENTITY_NOT_FOUND", field="assigneeId"
            )
        for lid in inp.get("labelIds") or []:
            if not self._label(lid):
                raise _err(f"Label '{lid}' not found.", "ENTITY_NOT_FOUND", field="labelIds")

    # ── mutation resolvers ───────────────────────────────────────────────────
    def _m_issue_create(self, info, input):
        self._count_op("issueCreate")
        self._validate_issue_input(input, creating=True)
        self._bump_write()
        team = self._team(input["teamId"])
        # default state = first unstarted/backlog state for the team
        state_id = input.get("stateId")
        if not state_id:
            cand = [
                s
                for s in self.store["states"]
                if s["teamId"] == team["id"] and s["type"] in ("unstarted", "backlog")
            ]
            state_id = cand[0]["id"] if cand else self.store["states"][0]["id"]
        seq = sum(1 for i in self.store["issues"] if i["teamId"] == team["id"]) + 1
        issue = {
            "id": self._next_id("issue"),
            "identifier": f"{team['key']}-{seq}",
            "title": input["title"],
            "description": input.get("description"),
            "priority": input.get("priority", 0) or 0,
            "estimate": input.get("estimate"),
            "teamId": team["id"],
            "stateId": state_id,
            "assigneeId": input.get("assigneeId"),
            "labelIds": list(input.get("labelIds") or []),
            "archivedAt": None,
            "createdAt": self._now(),
        }
        self.store["issues"].append(issue)
        # Creating an issue notifies subscribers — an irreversible side effect.
        self.side_effect_log.append(f"notification: issue {issue['identifier']} created")
        return {"success": True, "issue": self._issue_view(issue)}

    def _m_issue_update(self, info, id, input):
        self._count_op("issueUpdate")
        issue = self._issue(id)
        if not issue:
            raise _err(f"Issue '{id}' not found.", "ENTITY_NOT_FOUND", field="id")
        self._validate_issue_input(input, creating=False)
        # Workspace workflow policy: completing an issue in a team that requires
        # estimates is rejected unless the issue has (or is being given) one.
        target_state_id = input.get("stateId")
        if target_state_id:
            target = self._state(target_state_id)
            new_estimate = input.get("estimate", issue.get("estimate"))
            if (
                target
                and target["type"] == "completed"
                and issue["teamId"] in self.require_estimate_to_complete
                and new_estimate is None
            ):
                team = self._team(issue["teamId"])
                raise _err(
                    f"Issues in team {team['name']} must have an estimate before they can be completed.",
                    "WORKFLOW_RULE",
                    field="estimate",
                    requires="estimate",
                    before_state_type="completed",
                    team=issue["teamId"],
                )
        self._bump_write()
        for k in ("title", "description", "priority", "estimate", "stateId", "assigneeId"):
            if k in input and input[k] is not None:
                issue[k] = input[k]
        if input.get("labelIds") is not None:
            issue["labelIds"] = list(input["labelIds"])
        return {"success": True, "issue": self._issue_view(issue)}

    def _m_issue_archive(self, info, id):
        self._count_op("issueArchive")
        issue = self._issue(id)
        if not issue:
            raise _err(f"Issue '{id}' not found.", "ENTITY_NOT_FOUND", field="id")
        self._bump_write()
        issue["archivedAt"] = self._now()
        return {"success": True}

    def _m_issue_unarchive(self, info, id):
        self._count_op("issueUnarchive")
        issue = self._issue(id)
        if not issue:
            raise _err(f"Issue '{id}' not found.", "ENTITY_NOT_FOUND", field="id")
        self._bump_write()
        issue["archivedAt"] = None
        return {"success": True}

    def _m_issue_delete(self, info, id):
        self._count_op("issueDelete")
        if self.forbid_delete:
            raise _err(
                "Your API token does not have permission to permanently delete issues.",
                "FORBIDDEN",
                operation="issueDelete",
            )
        issue = self._issue(id)
        if not issue:
            raise _err(f"Issue '{id}' not found.", "ENTITY_NOT_FOUND", field="id")
        self._bump_write()
        self.store["issues"].remove(issue)
        return {"success": True}

    def _m_comment_create(self, info, input):
        self._count_op("commentCreate")
        if not input.get("body"):
            raise _err("Argument 'body' is required.", "INVALID_INPUT", field="body")
        issue = self._issue(input["issueId"])
        if not issue:
            raise _err(
                f"Issue '{input['issueId']}' not found.", "ENTITY_NOT_FOUND", field="issueId"
            )
        self._bump_write()
        comment = {
            "id": self._next_id("comment"),
            "issueId": issue["id"],
            "body": input["body"],
            "userId": self.store["users"][0]["id"],
            "createdAt": self._now(),
        }
        self.store["comments"].append(comment)
        # Posting a comment notifies watchers — irreversible once sent.
        self.side_effect_log.append(f"notification: comment on {issue['identifier']}")
        return {"success": True, "comment": self._comment_view(comment)}

    def _m_project_create(self, info, input):
        self._count_op("projectCreate")
        if not input.get("name"):
            raise _err("Argument 'name' is required.", "INVALID_INPUT", field="name")
        self._bump_write()
        project = {
            "id": self._next_id("project"),
            "name": input["name"],
            "description": input.get("description"),
            "state": "planned",
        }
        self.store["projects"].append(project)
        return {"success": True, "project": self._project_view(project)}

    def _m_document_create(self, info, input):
        self._count_op("documentCreate")
        if not input.get("title"):
            raise _err("Argument 'title' is required.", "INVALID_INPUT", field="title")
        if input.get("content") is None:
            raise _err("Argument 'content' is required.", "INVALID_INPUT", field="content")
        self._bump_write()
        doc = {
            "id": self._next_id("doc"),
            "title": input["title"],
            "content": input["content"],
            "createdAt": self._now(),
        }
        self.store["documents"].append(doc)
        return {"success": True, "document": self._document_view(doc)}

    # ── test/demo conveniences ───────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.store)
