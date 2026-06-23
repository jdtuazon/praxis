"""Deterministic intent-signature canonicalizer.

The signature is the *primary reuse key* for plans (embedding/TF-IDF similarity
is only a tie-breaker). It canonicalizes an instruction to a structured shape —
{verb · entity · predicates · mutation-fields} — with concrete parameters
(team names, priority values, counts) deliberately *extracted out*. That is what
lets a plan learned for "create a high-priority bug in Engineering" transfer to
"file an urgent ticket in Design": same signature, different bindings re-resolved
at execution time.

It is rule-based (not LLM-based) on purpose: retrieval must be deterministic so
the learning numbers are reproducible and the cache can never silently misfire.
"""

from __future__ import annotations

import re

_VERBS = [
    ("aggregate", ["group", "summar", "digest", "roll up", "rollup", "roll-up", "report", "breakdown", "rebalance"]),
    ("archive", ["archive"]),
    ("delete", ["delete", "remove permanently", "purge"]),
    ("comment", ["comment", "leave a note", "ping", "remind"]),
    ("update", ["update", "change", "set", "move", "assign", "reassign", "close", "complete", "mark", "transition", "prioriti"]),
    ("create", ["create", "make", "file", "add", "open a", "log a", "raise", "new "]),
    ("query", ["find", "list", "show", "get", "search", "count", "which", "what", "how many", "fetch", "look up"]),
]

_ENTITIES = [
    ("document", ["document", "page", "summary", "digest", "write-up", "writeup"]),
    ("project", ["project", "roadmap", "milestone"]),
    ("issue", ["issue", "bug", "ticket", "task", "story", "defect"]),
]

_PREDICATES = [
    ("assignee:null", ["no assignee", "nobody", "unassigned", "without an assignee", "not assigned", "no one"]),
    ("assignee:me", ["assigned to me", "my ", "mine"]),
    ("state:open", ["open", "active", "in progress", "in-progress", "not done", "unstarted", "todo"]),
    ("state:done", ["done", "completed", "closed", "finished"]),
    ("age:stale", ["stale", "old", "no activity", "days", "weeks", "untouched", "inactive"]),
    ("priority:high", ["urgent", "high priority", "high-priority", "p1", "p0", "critical", "important"]),
    ("group:assignee", ["by assignee", "per assignee", "grouped by assignee"]),
    ("group:priority", ["by priority", "per priority", "grouped by priority"]),
    ("group:team", ["by team", "per team", "grouped by team"]),
    ("group:state", ["by status", "by state", "per state"]),
]

_FIELDS = [
    ("priority", ["priority", "urgent", "p1", "p0", "critical", "high", "medium", "low"]),
    ("assignee", ["assign", "assignee", "owner"]),
    ("state", ["move", "state", "status", "done", "in progress", "todo", "complete", "close"]),
    ("estimate", ["estimate", "points", "sizing"]),
    ("label", ["label", "tag"]),
    ("comment", ["comment", "note"]),
]


def _earliest(text: str, table: list[tuple[str, list[str]]]) -> str | None:
    """Return the table entry whose needle appears earliest in the text.

    Position-based (not table-order) so the *leading* verb wins — 'find ... no
    assignee' is a query, not an update, even though 'assign' appears later.
    """
    best_name, best_pos = None, len(text) + 1
    for name, needles in table:
        for n in needles:
            pos = text.find(n)
            if pos != -1 and pos < best_pos:
                best_name, best_pos = name, pos
    return best_name


def _match_all(text: str, table: list[tuple[str, list[str]]]) -> list[str]:
    return [name for name, needles in table if any(n in text for n in needles)]


def compute_signature(instruction: str) -> str:
    """Return a normalized, parameter-free signature string for an instruction."""
    text = " " + instruction.lower().strip() + " "

    verb = _earliest(text, _VERBS) or "act"
    # Aggregation dominates: "create a digest grouped by X" is an aggregation,
    # not a create, regardless of which verb word appears first.
    if any(n in text for n in _VERBS[0][1]):
        verb = "aggregate"
    # "add a comment/note" is a comment, not a create (the create-ish "add" only
    # means create when an issue-like object is being created).
    if verb == "create" and any(w in text for w in ("comment", " note ")) \
            and not any(n in text for n in ("bug", "issue", "ticket", "task", "story", "defect", "project")):
        verb = "comment"
    entity = _earliest(text, _ENTITIES) or "issue"
    predicates = sorted(set(_match_all(text, _PREDICATES)))
    # Mutation-field tags only matter for write verbs; queries/aggregations are
    # characterised by their predicates, not the fields they touch.
    fields = sorted(set(_match_all(text, _FIELDS))) if verb in {"create", "update", "comment", "archive"} else []

    parts = [verb, entity]
    if predicates:
        parts.append("pred[" + ",".join(predicates) + "]")
    if fields:
        parts.append("fields[" + ",".join(fields) + "]")
    return "·".join(parts)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())
