"""Deterministic offline 'brain' for the ScriptedLLM.

This reproduces what a real LLM would return for the demo instruction families,
so the *entire* agent loop — planning, synthesis, learning — runs with zero
network and identical, assertable results. Live mode (`praxis run` with an API
key) uses a real LLM and handles arbitrary instructions; this module exists so
regression tests can prove the learning numbers and the demo is reproducible.

It is intentionally rule-based and scoped to the demo families (create / query /
aggregate-digest / transition / triage). Unknown instructions fall back to a
read-only query so offline mode degrades safely rather than fabricating writes.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..memory.signature import compute_signature

_KNOWN_TEAMS = {"engineering": "Engineering", "eng": "Engineering", "design": "Design", "des": "Design"}
_PRIORITY = [(("urgent", "critical", "p1", "p0"), 1), (("high", "p2"), 2), (("medium", "p3"), 3), (("low", "p4"), 4)]
_ID_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")
_QUOTE_RE = re.compile(r"['\"‘’“”]([^'\"‘’“”]{3,})['\"‘’“”]")


def _instruction(prompt: str) -> str:
    m = re.search(r"INSTRUCTION:\s*(.+)", prompt)
    return (m.group(1).strip() if m else prompt).splitlines()[0]


def _team(text: str) -> str:
    low = text.lower()
    for kw, name in _KNOWN_TEAMS.items():
        if kw in low:
            return name
    return "Engineering"


def _priority(text: str) -> Optional[int]:
    low = text.lower()
    for words, code in _PRIORITY:
        if any(w in low for w in words):
            return code
    return None


def _title(text: str) -> str:
    q = _QUOTE_RE.search(text)
    if q:
        return q.group(1)
    m = re.search(r"(?:titled|called|named)\s+(.+)$", text, re.I)
    if m:
        return m.group(1).strip(" .")
    # fall back: strip leading verb/articles
    cleaned = re.sub(r"^(create|file|add|open|log|raise|make)\s+(a|an|the)?\s*", "", text, flags=re.I)
    cleaned = re.sub(r"\b(in|for|to)\s+(the\s+)?(engineering|design)\s*(team)?\b.*$", "", cleaned, flags=re.I)
    return (cleaned.strip(" .") or "New issue")[:80]


def _group_by(text: str) -> tuple[str, str]:
    low = text.lower()
    if "assignee" in low:
        return "assignee.displayName", "assignee"
    if "team" in low:
        return "team.name", "team"
    if "state" in low or "status" in low:
        return "state.name", "status"
    return "priorityLabel", "priority"


def _plan(steps: list[dict], rationale: str) -> str:
    for i, s in enumerate(steps):
        s.setdefault("index", i)
        s.setdefault("depends_on", [])
        s.setdefault("optional", False)
    return json.dumps({"rationale": rationale, "steps": steps})


# ── plan builders per family ─────────────────────────────────────────────────
def _build_plan(instruction: str, available_caps: Optional[set[str]] = None) -> str:
    available_caps = available_caps or set()
    sig = compute_signature(instruction)
    verb = sig.split("·", 1)[0]
    low = instruction.lower()

    if verb == "aggregate":
        by_path, by_label = _group_by(instruction)
        title = _title(instruction) if _QUOTE_RE.search(instruction) else f"Issue digest by {by_label}"
        # Reuse an already-known digest capability instead of re-synthesizing (transfer).
        cap = "issue_digest" if "issue_digest" in available_caps else None
        return _plan([
            {"intent": f"build a digest document grouped by {by_label}", "capability": cap,
             "args": {"group_by": by_path, "title": title}},
        ], f"aggregation/digest grouped by {by_label}"
           + ("" if cap else " — needs a synthesized composite"))

    if verb == "create":
        steps = [{"intent": "resolve the team", "capability": "find_team", "args": {"name": _team(instruction)}}]
        issue_args = {"teamId": "{{step0.id}}", "title": _title(instruction)}
        pr = _priority(instruction)
        if pr is not None:
            issue_args["priority"] = pr
        deps = [0]
        if re.search(r"assign(ed)?\s+(it\s+)?to\s+me|\bto me\b", low):
            steps.append({"intent": "resolve me", "capability": "viewer", "args": {}})
            issue_args["assigneeId"] = "{{step1.id}}"
            deps = [0, 1]
        steps.append({"intent": "create the issue", "capability": "create_issue", "args": issue_args, "depends_on": deps})
        return _plan(steps, "create an issue in a resolved team")

    if verb == "query":
        f: dict = {}
        if "assignee:null" in sig:
            f["assigneeIsNull"] = True
        return _plan([{"intent": "query issues", "capability": "query_issues", "args": {"filter": f}}],
                     "read-only issue query")

    # update / comment / transition / triage
    ident = _ID_RE.search(instruction)
    steps: list[dict] = []
    if ident:
        steps.append({"intent": f"resolve issue {ident.group(1)}", "capability": "find_issue",
                      "args": {"identifier": ident.group(1)}})
        target, team_ref, base = "{{step0.id}}", "{{step0.team.id}}", 0
    else:
        steps.append({"intent": "resolve me", "capability": "viewer", "args": {}})
        steps.append({"intent": "find my in-progress issues", "capability": "query_issues",
                      "args": {"filter": {"assigneeId": "{{step0.id}}", "stateType": "started"}}, "depends_on": [0]})
        target, team_ref, base = "{{step1.0.id}}", "{{step1.0.team.id}}", 1

    def nxt() -> int:
        return len(steps)

    # set estimate
    mest = re.search(r"estimat\w*\s+(?:it\s+)?(?:at\s+|to\s+|of\s+)?(\d+)", low) or re.search(r"(\d+)\s*(?:points|story points|pts)", low)
    if mest:
        steps.append({"intent": "set the estimate", "capability": "update_issue",
                      "args": {"id": target, "estimate": int(mest.group(1))}, "depends_on": [base]})
    # move to done / complete
    if any(w in low for w in ("done", "complete", "close", "finish")):
        steps.append({"intent": "resolve the Done state", "capability": "find_workflow_state",
                      "args": {"teamId": team_ref, "type": "completed"}, "depends_on": [base]})
        ds = nxt() - 1
        steps.append({"intent": "move the issue to Done", "capability": "update_issue",
                      "args": {"id": target, "stateId": f"{{{{step{ds}.id}}}}"}, "depends_on": [base, ds]})
    # move to in progress / start
    elif any(w in low for w in ("in progress", "in-progress", "start working", "pick up", "picked up", "start ")):
        steps.append({"intent": "resolve the In Progress state", "capability": "find_workflow_state",
                      "args": {"teamId": team_ref, "name": "In Progress"}, "depends_on": [base]})
        ss = nxt() - 1
        steps.append({"intent": "move the issue to In Progress", "capability": "update_issue",
                      "args": {"id": target, "stateId": f"{{{{step{ss}.id}}}}"}, "depends_on": [base, ss]})
    # comment
    q = _QUOTE_RE.search(instruction)
    if "comment" in low or "note" in low or (q and "titled" not in low):
        body = q.group(1) if q else "Please provide a status update."
        steps.append({"intent": "leave a comment", "capability": "add_comment",
                      "args": {"issueId": target, "body": body}, "depends_on": [base]})
    # assign to <name>
    massign = re.search(r"assign(?:\s+it)?\s+to\s+([a-z]+)", low)
    if massign and massign.group(1) not in ("me",):
        steps.append({"intent": f"resolve user {massign.group(1)}", "capability": "find_user",
                      "args": {"name": massign.group(1)}, "depends_on": [base]})
        us = nxt() - 1
        steps.append({"intent": "assign the issue", "capability": "update_issue",
                      "args": {"id": target, "assigneeId": f"{{{{step{us}.id}}}}"}, "depends_on": [base, us]})
    elif re.search(r"assign(?:\s+it)?\s+to\s+me", low):
        steps.append({"intent": "resolve me", "capability": "viewer", "args": {}})
        us = nxt() - 1
        steps.append({"intent": "assign the issue to me", "capability": "update_issue",
                      "args": {"id": target, "assigneeId": f"{{{{step{us}.id}}}}"}, "depends_on": [base, us]})

    if len(steps) <= (1 if ident else 2):  # nothing actionable detected → safe read-only fallback
        return _plan([{"intent": "query issues", "capability": "query_issues", "args": {"filter": {}}}],
                     "fallback read-only query")
    return _plan(steps, "compound update/triage decomposed into atomic steps")


# ── synthesizer ──────────────────────────────────────────────────────────────
def _build_capability_plan(prompt: str) -> str:
    gap = ""
    m = re.search(r"CAPABILITY GAP[^:]*:\s*(.+)", prompt)
    if m:
        gap = m.group(1).strip().splitlines()[0]
    low = (gap + " " + _instruction(prompt)).lower()
    if any(w in low for w in ("digest", "group", "summar", "roll", "report", "breakdown")):
        by_path, _ = _group_by(low)
        return json.dumps({
            "name": "issue_digest", "kind": "composite",
            "description": "Group issues and write a markdown digest document. Parameterized by group_by/title.",
            "rationale": "multi-query gather + in-memory grouping + a document write — cannot be a single API call",
            "input_schema": {"group_by": "string", "title": "string"},
            "composition": [
                {"op": "capability:query_issues", "args": {"filter": {}}, "bind": "issues"},
                {"op": "transform:group", "args": {"source": "{{issues}}", "by": "{{args.group_by}}",
                                                   "null_label": "Unassigned"}, "bind": "groups"},
                {"op": "transform:markdown_table", "args": {"source": "{{groups}}", "title": "{{args.title}}",
                                                            "columns": ["identifier", "title", "priorityLabel"]}, "bind": "table"},
                {"op": "capability:create_document", "args": {"title": "{{args.title}}", "content": "{{table}}"}, "bind": "doc"},
            ],
            "probe_args": {"group_by": by_path, "title": "Probe Digest"},
        })
    # generic: comment on each matching issue
    if "comment" in low or "each" in low or "every" in low:
        return json.dumps({
            "name": "comment_on_each", "kind": "composite",
            "description": "Post a comment on each issue in a set.",
            "rationale": "fan-out over many items — a composition, not one call",
            "input_schema": {"filter": "object", "body": "string"},
            "composition": [
                {"op": "capability:query_issues", "args": {"filter": "{{args.filter}}"}, "bind": "issues"},
                {"op": "transform:create_each", "args": {"source": "{{issues}}", "capability": "add_comment",
                                                         "args": {"issueId": "{{item.id}}", "body": "{{args.body}}"}}, "bind": "posted"},
            ],
            "probe_args": {"filter": {}, "body": "[PRAXIS-PROBE]"},
        })
    return json.dumps({"name": "noop", "kind": "graphql", "operation_type": "query",
                       "graphql_root_field": "viewer", "args": {}, "selection": "id", "select_path": "viewer"})


def make_offline_responder():
    """Return a ScriptedLLM responder implementing the offline planner + synthesizer."""

    def responder(system: str, prompt: str) -> Optional[str]:
        if "[[ROLE:PLANNER]]" in system:
            # Catalog lines look like "- capability_name(args) — description".
            available = set(re.findall(r"^- (\w+)\(", prompt, re.MULTILINE))
            available |= set(re.findall(r"^- (\w+)$", prompt, re.MULTILINE))
            return _build_plan(_instruction(prompt), available)
        if "[[ROLE:SYNTHESIZER]]" in system:
            return _build_capability_plan(prompt)
        return None

    return responder
