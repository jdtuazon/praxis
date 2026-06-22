"""Executor — runs the plan, honouring memory, and never half-completes silently.

For each step it: resolves `{{stepN.path}}` references; fills capability gaps by
delegating to the synthesizer; consults memory *before* acting (cached entity
ids skip resolver calls; enum facts pre-validate args; permission facts switch
tooling); executes; and accounts for every API call — including "wasted" calls
(a call that failed on a rule memory could have pre-empted). A failed required
step skips its dependents rather than pressing on blindly.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..capabilities.registry import CapabilityRegistry, ExecutionContext
from ..capabilities.synthesis import Synthesizer
from ..memory.signature import tokenize
from ..models import (
    CallAttribution,
    CapabilitySource,
    ConstraintKind,
    Decision,
    Plan,
    PlanStep,
    StepReport,
    StepStatus,
    SynthesisResult,
)
from ..platform.base import PlatformError

# Capabilities whose result is a stable workspace entity → cacheable across runs.
RESOLVER_CAPS = {"viewer", "find_team", "find_workflow_state", "find_user"}
# Error codes that a learned constraint could have pre-empted (→ "wasted" calls).
LEARNABLE_CODES = {"INVALID_INPUT", "FORBIDDEN", "WORKFLOW_RULE", "RATELIMITED"}
_STOPWORDS = {"the", "a", "an", "all", "to", "of", "and", "with", "for", "in", "on", "by", "into", "every", "each", "no"}


def _entity_key(cap: str, args: dict[str, Any]) -> str:
    items = ",".join(f"{k}={args[k]}" for k in sorted(args) if not str(args[k]).startswith("{{"))
    return f"{cap}({items})"


def _summarize(result: Any) -> str:
    if isinstance(result, dict):
        for k in ("identifier", "title", "name", "displayName", "id"):
            if k in result:
                return f"{k}={result[k]}"
        if "errors" in result and "results" in result:
            return f"{result.get('succeeded', 0)} ok, {result.get('failed', 0)} failed"
        return "ok"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    return str(result)[:60]


def derive_keywords(text: str) -> list[str]:
    return [t for t in dict.fromkeys(tokenize(text)) if t not in _STOPWORDS and len(t) > 2][:8]


class Executor:
    def __init__(self, registry: CapabilityRegistry, memory, settings) -> None:
        self.registry = registry
        self.memory = memory
        self.settings = settings

    def execute(
        self, plan: Plan, ctx: ExecutionContext, synthesizer: Synthesizer
    ) -> tuple[list[StepReport], list[Decision], list[SynthesisResult]]:
        reports: dict[int, StepReport] = {}
        failed: set[int] = set()
        decisions: list[Decision] = []
        synth_results: list[SynthesisResult] = []

        for step in plan.steps:
            sr = StepReport(index=step.index, intent=step.intent, capability=step.capability,
                            inserted_by_constraint=step.inserted_by_constraint)

            if any(d in failed for d in step.depends_on):
                sr.status = StepStatus.SKIPPED
                sr.result_summary = "skipped — a prerequisite step failed"
                reports[step.index] = sr
                if not step.optional:
                    failed.add(step.index)
                continue

            # 1) resolve a capability gap via synthesis
            cap_name = step.capability
            if cap_name is None or not self.registry.has(cap_name):
                kw = derive_keywords(f"{step.intent} {plan.instruction}")
                res = synthesizer.synthesize(gap_intent=step.intent, instruction=plan.instruction, keywords=kw)
                synth_results.append(res)
                if res.success:
                    cap_name = res.capability_name
                    sr.capability = cap_name
                    decisions.append(Decision(
                        stage="synthesize",
                        summary=f"Synthesized '{cap_name}' for sub-goal: {step.intent}",
                        rationale=f"No existing capability matched; built+tested in {len(res.attempts)} attempt(s).",
                    ))
                else:
                    sr.status = StepStatus.FAILED
                    sr.error = f"capability synthesis failed: {res.final_error}"
                    reports[step.index] = sr
                    if not step.optional:
                        failed.add(step.index)
                    continue
            else:
                # The planner reused a previously-synthesized capability → no re-synthesis (transfer).
                spec = self.memory.capability.get_capability(cap_name)
                if spec and spec.source == CapabilitySource.SYNTHESIZED:
                    att = CallAttribution(kind="reused_capability", ref=f"capability/{cap_name}",
                                          detail="reused a previously-synthesized capability; skipped re-synthesis")
                    ctx.note_saving(att)
                    sr.provenance.append(att)

            # 2) permission pre-check (switch/skip a forbidden op rather than fail on it)
            if self.memory.capability.permission_forbidden(cap_name):
                att = CallAttribution(kind="pre_validated", ref=f"constraint:permission/{cap_name}",
                                      detail="known-forbidden operation avoided")
                ctx.note_saving(att)
                sr.provenance.append(att)
                sr.status = StepStatus.SKIPPED
                sr.result_summary = f"avoided forbidden operation '{cap_name}' (learned permission boundary)"
                decisions.append(Decision(stage="execute", summary=f"Skipped forbidden op '{cap_name}'",
                                          rationale="Memory records this token cannot perform it."))
                reports[step.index] = sr
                continue

            # 3) resolve arg templates + pre-validate against enum constraints
            args = ctx.resolve(step.args, ctx.vars)
            args = self._prevalidate(cap_name, args, ctx, sr)

            # 4) resolver cache: skip the API call if this entity is already known
            if cap_name in RESOLVER_CAPS:
                key = _entity_key(cap_name, args)
                cached = self.memory.capability.cached_entity_id("entity", key)
                if cached is not None:
                    ctx.vars[f"step{step.index}"] = cached
                    att = CallAttribution(kind="cached_entity", ref=f"entity/{key}",
                                          detail=f"reused cached result; skipped {cap_name} API call")
                    sr.provenance.append(att)
                    ctx.note_saving(att)
                    self.memory.capability.bump_hit(kind=ConstraintKind.ENTITY_ID, scope="entity", key=key)
                    sr.status = StepStatus.SUCCESS
                    sr.result_summary = f"{_summarize(cached)} (from memory)"
                    reports[step.index] = sr
                    continue

            # 5) execute
            before = ctx.client.api_calls
            journal_before = len(ctx.journal)
            t0 = time.time()
            try:
                result = self.registry.run(cap_name, ctx, **args)
                sr.api_calls = ctx.client.api_calls - before
                sr.duration_s = round(time.time() - t0, 4)
                sr.attempts = 1
                # tag any side effects this step produced, so rollback maps to steps
                for e in ctx.journal[journal_before:]:
                    e.step_index = step.index
                ctx.vars[f"step{step.index}"] = result
                sr.status = StepStatus.SUCCESS
                sr.result_summary = _summarize(result)
                if cap_name in RESOLVER_CAPS:
                    ctx.observe_failure({"type": "resolver_success", "key": _entity_key(cap_name, args),
                                         "value": result, "capability": cap_name})
                # surface fan-out partial failures (never silent)
                if isinstance(result, dict) and result.get("errors"):
                    for err in result["errors"]:
                        if (err.get("code") or "") in LEARNABLE_CODES:
                            ctx.wasted_calls += 1
                            sr.wasted_calls += 1
                            ctx.observe_failure({"type": "platform_error", "capability": cap_name,
                                                 "code": err.get("code"), "message": err.get("error"), "args": args})
                    if result.get("failed"):
                        sr.result_summary += f" — {result['failed']} item(s) failed (reported, not swallowed)"
            except PlatformError as e:
                sr.api_calls = ctx.client.api_calls - before
                sr.duration_s = round(time.time() - t0, 4)
                sr.attempts = 1
                sr.status = StepStatus.FAILED
                sr.error = f"[{e.code}] {e}"
                if (e.code or "") in LEARNABLE_CODES:
                    sr.wasted_calls = 1
                    ctx.wasted_calls += 1
                    ctx.observe_failure({"type": "platform_error", "capability": cap_name, "code": e.code,
                                         "message": str(e), "extensions": e.extensions, "args": args})
                if not step.optional:
                    failed.add(step.index)

            reports[step.index] = sr

        ordered = [reports[s.index] for s in plan.steps]
        return ordered, decisions, synth_results

    # ── pre-validation against learned enum constraints ─────────────────────
    def _prevalidate(self, cap_name: str, args: dict[str, Any], ctx: ExecutionContext, sr: StepReport) -> dict[str, Any]:
        if cap_name not in ("create_issue", "update_issue") or "priority" not in args:
            return args
        c = self.memory.capability.enum_constraint("issue.priority")
        if not c or not isinstance(c.value, dict):
            return args
        val = args["priority"]
        mapping = c.value.get("map") or {}
        rng = c.value.get("range")
        # NL → code mapping (e.g. "urgent" → 1) learned from a prior response.
        if isinstance(val, str) and val.lower() in mapping:
            args = {**args, "priority": mapping[val.lower()]}
            att = CallAttribution(kind="pre_validated", ref="constraint:field/issue.priority",
                                  detail=f"mapped '{val}' → {args['priority']} from learned enum")
            sr.provenance.append(att); ctx.note_saving(att)
        elif rng and isinstance(val, int) and not (rng[0] <= val <= rng[1]):
            clamped = max(rng[0], min(rng[1], val))
            args = {**args, "priority": clamped}
            att = CallAttribution(kind="pre_validated", ref="constraint:field/issue.priority",
                                  detail=f"clamped priority {val} → {clamped} (learned range {rng}); avoided a failed call")
            sr.provenance.append(att); ctx.note_saving(att)
            self.memory.capability.bump_hit(kind=ConstraintKind.ENUM, scope="field", key="issue.priority")
        return args
