"""Capability registry, execution context, and the composition-DSL interpreter.

A *capability* is executable knowledge. Three runtime forms:

  • builtin  — trusted Python shipped with Praxis (atomic Linear ops);
  • graphql  — a synthesized, parameterized GraphQL operation (from a schema-
    validated contract);
  • composite — a synthesized ordered composition of *already-trusted*
    capabilities + a small set of whitelisted pure transforms (filter/group/
    sort/markdown_table/create_each). No imports, no `exec`, no filesystem,
    no network — a constrained DSL, which is the safety boundary for runtime-
    synthesized behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..models import AppliedEffect, CallAttribution, CapabilityKind, CapabilitySpec, TransformStep
from ..platform.base import PlatformError

# ── whitelisted pure transforms ─────────────────────────────────────────────
_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _dig(obj: Any, path: str) -> Any:
    """Navigate a dotted path through dicts/objects/lists."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            cur = getattr(cur, part, None)
    return cur


class CapabilityError(RuntimeError):
    pass


@dataclass
class ExecutionContext:
    """Run-scoped state threaded through every capability invocation."""

    client: Any                       # LinearClient
    registry: "CapabilityRegistry"
    memory: Any = None                # praxis.memory.Memory
    settings: Any = None
    vars: dict[str, Any] = field(default_factory=dict)
    journal: list[AppliedEffect] = field(default_factory=list)
    dry_run: bool = False             # when True, side-effecting ops are validated, not executed
    probe_marker: str = "[PRAXIS-PROBE]"
    # run-scoped accounting consumed by the learner / report
    attributions: list[CallAttribution] = field(default_factory=list)
    wasted_calls: int = 0
    observations: list[dict] = field(default_factory=list)  # raw learnable failures for the learner

    def record_effect(self, effect: AppliedEffect) -> None:
        self.journal.append(effect)

    def note_saving(self, attribution: CallAttribution) -> None:
        self.attributions.append(attribution)

    def observe_failure(self, obs: dict) -> None:
        self.observations.append(obs)

    def resolve(self, value: Any, scope: dict[str, Any]) -> Any:
        """Resolve {{path}} templates in strings (and recursively in dicts/lists)."""
        if isinstance(value, str):
            m = _TEMPLATE_RE.fullmatch(value.strip())
            if m:  # whole-string reference → preserve type
                return _dig(scope, m.group(1))
            return _TEMPLATE_RE.sub(lambda mm: str(_dig(scope, mm.group(1))), value)
        if isinstance(value, dict):
            return {k: self.resolve(v, scope) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v, scope) for v in value]
        return value


@dataclass
class Capability:
    """A runtime-bound, executable capability."""

    spec: CapabilitySpec
    func: Optional[Callable[..., Any]] = None  # builtins only

    @property
    def name(self) -> str:
        return self.spec.name

    def run(self, ctx: ExecutionContext, /, **args: Any) -> Any:
        if self.func is not None:
            return self.func(ctx, **args)
        if self.spec.kind == CapabilityKind.GRAPHQL:
            return self._run_graphql(ctx, args)
        if self.spec.kind == CapabilityKind.COMPOSITE:
            return self._run_composite(ctx, args)
        raise CapabilityError(f"Capability '{self.name}' has no executable form.")

    # ── GraphQL form ──────────────────────────────────────────────────────
    def _run_graphql(self, ctx: ExecutionContext, args: dict[str, Any]) -> Any:
        if self.spec.side_effecting and ctx.dry_run:
            return {"_dry_run": True, "args": args}
        data = ctx.client.execute(self.spec.graphql, args)
        if self.spec.select_path:
            data = _dig(data, self.spec.select_path)
        return data

    # ── Composite form (the constrained DSL) ────────────────────────────────
    def _run_composite(self, ctx: ExecutionContext, args: dict[str, Any]) -> Any:
        scope: dict[str, Any] = {"args": args}
        last: Any = None
        for step in self.spec.composition:
            last = self._run_step(ctx, step, scope)
            if step.bind:
                scope[step.bind] = last
        return last

    def _run_step(self, ctx: ExecutionContext, step: TransformStep, scope: dict[str, Any]) -> Any:
        kind, _, name = step.op.partition(":")
        resolved_args = ctx.resolve(step.args, scope)
        if kind == "capability":
            return ctx.registry.run(name, ctx, **resolved_args)
        if kind == "transform":
            return _TRANSFORMS[name](ctx, scope, resolved_args)
        raise CapabilityError(f"Unknown composition op '{step.op}'")


# ── transform implementations ────────────────────────────────────────────────
def _t_filter(ctx, scope, a):
    src = a.get("source", [])
    if isinstance(src, dict) and "nodes" in src:
        src = src["nodes"]
    where = a.get("where", [])
    if isinstance(where, dict):
        where = [where]
    out = [item for item in (src or []) if all(_match_pred(item, p) for p in where)]
    return out


def _match_pred(item: dict, p: dict) -> bool:
    field_name, op, value = p.get("field"), p.get("op", "eq"), p.get("value")
    cur = _dig(item, field_name) if field_name else None
    if op == "is_null":
        return cur is None
    if op == "not_null":
        return cur is not None
    if op == "eq":
        return cur == value
    if op == "ne":
        return cur != value
    if op == "in":
        return cur in (value or [])
    if op == "gte":
        return cur is not None and cur >= value
    if op == "lte":
        return cur is not None and cur <= value
    if op == "empty":
        return not cur
    if op == "non_empty":
        return bool(cur)
    return False


def _t_group(ctx, scope, a):
    src = a.get("source", [])
    if isinstance(src, dict) and "nodes" in src:
        src = src["nodes"]
    by = a.get("by", "")
    groups: dict[str, list] = {}
    for item in src or []:
        key = _dig(item, by)
        if key is None:
            key = a.get("null_label", "Unassigned")
        groups.setdefault(str(key), []).append(item)
    return groups


def _t_sort(ctx, scope, a):
    src = list(a.get("source", []) or [])
    by = a.get("by", "")
    return sorted(src, key=lambda x: (_dig(x, by) is None, _dig(x, by)), reverse=bool(a.get("desc")))


def _t_count(ctx, scope, a):
    src = a.get("source", [])
    if isinstance(src, dict) and "nodes" in src:
        src = src["nodes"]
    return len(src or [])


def _t_markdown_table(ctx, scope, a):
    """Render a grouped dict OR a flat list into a markdown document body."""
    src = a.get("source")
    columns = a.get("columns", ["identifier", "title", "priorityLabel"])
    title = a.get("title", "")
    lines: list[str] = []
    if title:
        lines.append(f"# {title}\n")

    def render_rows(items: list[dict]) -> list[str]:
        rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
        for it in items:
            rows.append("| " + " | ".join(str(_dig(it, c) if "." in c else it.get(c, "")) for c in columns) + " |")
        return rows

    if isinstance(src, dict):  # grouped
        for group_key, items in src.items():
            lines.append(f"\n## {group_key} ({len(items)})\n")
            lines.extend(render_rows(items))
    else:
        lines.extend(render_rows(src or []))
    return "\n".join(lines)


def _t_create_each(ctx, scope, a):
    """For each item in `source`, invoke `capability` with a templated arg map."""
    src = a.get("source", [])
    if isinstance(src, dict) and "nodes" in src:
        src = src["nodes"]
    cap = a.get("capability")
    arg_template = a.get("args", {})
    results = []
    errors = []
    for item in src or []:
        item_scope = dict(scope)
        item_scope["item"] = item
        call_args = ctx.resolve(arg_template, item_scope)
        try:
            results.append(ctx.registry.run(cap, ctx, **call_args))
        except PlatformError as e:  # partial failure within a fan-out is reported, not swallowed
            errors.append({"item": item.get("identifier", item.get("id")), "error": str(e), "code": e.code})
    return {"results": results, "errors": errors, "succeeded": len(results), "failed": len(errors)}


_TRANSFORMS: dict[str, Callable] = {
    "filter": _t_filter,
    "group": _t_group,
    "sort": _t_sort,
    "count": _t_count,
    "markdown_table": _t_markdown_table,
    "create_each": _t_create_each,
}
WHITELISTED_TRANSFORMS = set(_TRANSFORMS)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._caps[cap.name] = cap

    def register_spec(self, spec: CapabilitySpec, func: Optional[Callable] = None) -> None:
        self.register(Capability(spec=spec, func=func))

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Optional[Capability]:
        return self._caps.get(name)

    def names(self) -> list[str]:
        return sorted(self._caps)

    def specs(self) -> list[CapabilitySpec]:
        return [c.spec for c in self._caps.values()]

    def run(self, name: str, ctx: ExecutionContext, /, **args: Any) -> Any:
        cap = self._caps.get(name)
        if not cap:
            raise CapabilityError(f"No such capability: {name}")
        return cap.run(ctx, **args)
