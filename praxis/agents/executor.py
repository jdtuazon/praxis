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


def _find_issue_in_context(ctx, issue_id):
    """Find an already-fetched issue dict (by id) anywhere in run context — no API call."""
    if not issue_id:
        return None

    def walk(v):
        if isinstance(v, dict):
            if v.get("id") == issue_id and "identifier" in v:
                return v
            for x in v.values():
                r = walk(x)
                if r:
                    return r
        elif isinstance(v, list):
            for x in v:
                r = walk(x)
                if r:
                    return r
        return None

    return walk(ctx.vars)


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

            # 3b) a constraint-inserted precondition step is CONDITIONAL: verify the
            # target issue's team actually has the rule (team is unknown at plan time).
            if step.inserted_by_constraint and cap_name == "update_issue":
                applies, why = self._workflow_rule_applies(ctx, args)
                if not applies:
                    sr.status = StepStatus.SUCCESS
                    sr.result_summary = f"no-op — {why}"
                    decisions.append(Decision(stage="execute",
                                              summary="Skipped the inserted precondition step (rule not applicable here)",
                                              rationale=why))
                    ctx.vars[f"step{step.index}"] = {"_noop": True}
                    reports[step.index] = sr
                    continue
                att = CallAttribution(kind="pre_validated", ref=f"constraint:{step.inserted_by_constraint}",
                                      detail="set field required by a learned workflow rule (verified for this team)")
                ctx.note_saving(att)
                sr.provenance.append(att)

            # 4) resolver cache: skip the API call if this entity is already known —
            # but honour the constraint's verification policy (a volatile id under
            # VERIFY_ON_READ, or an expired REFETCH_TTL, is re-resolved as a
            # NON-saving call rather than trusted blindly).
            if cap_name in RESOLVER_CAPS:
                key = _entity_key(cap_name, args)
                row = self.memory.capability.constraint_row(kind=ConstraintKind.ENTITY_ID, scope="entity", key=key)
                if row is not None and not self._must_reverify(row):
                    ctx.vars[f"step{step.index}"] = self.memory.store.loads(row["value_json"])
                    att = CallAttribution(kind="cached_entity", ref=f"entity/{key}",
                                          detail=f"reused cached result; skipped {cap_name} API call")
                    sr.provenance.append(att)
                    ctx.note_saving(att)
                    self.memory.capability.bump_hit(kind=ConstraintKind.ENTITY_ID, scope="entity", key=key)
                    sr.status = StepStatus.SUCCESS
                    sr.result_summary = f"{_summarize(self.memory.store.loads(row['value_json']))} (from memory)"
                    reports[step.index] = sr
                    continue
                if row is not None:  # stale-but-likely → re-resolve (counted, not saved); learner re-caches
                    sr.provenance.append(CallAttribution(kind="reverify", ref=f"entity/{key}",
                                                         detail="cache present but verification policy required a re-resolve"))

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

    @staticmethod
    def _must_reverify(row) -> bool:
        """Decide whether a cached entity must be re-resolved before trusting it."""
        import time as _t

        policy = row["verification_policy"]
        if policy == "verify_on_read":
            return True
        if policy == "refetch_ttl" and row["ttl_seconds"]:
            return (_t.time() - row["observed_at"]) > row["ttl_seconds"]
        return False  # trust (stable workspace ids)

    # ── conditional applicability of a constraint-inserted precondition step ──
    def _workflow_rule_applies(self, ctx, args: dict) -> tuple[bool, str]:
        """Is the inserted precondition genuinely required for THIS issue's team?

        Resolves the target issue from run context (no extra API call) and checks
        the team-scoped WORKFLOW_RULE. Returns (applies, reason)."""
        field = next((k for k in args if k != "id"), None)
        issue = _find_issue_in_context(ctx, args.get("id"))
        if not issue:
            return True, "could not resolve issue context — applying precondition defensively"
        team_id = (issue.get("team") or {}).get("id")
        if issue.get(field) not in (None, "", 0):
            return False, f"issue already has {field}={issue.get(field)}"
        rules = self.memory.capability.workflow_rules(team_id) if team_id else []
        if any((r.value or {}).get("requires") == field for r in rules):
            self.memory.capability.bump_hit(kind=ConstraintKind.WORKFLOW_RULE, scope="team", key=team_id)
            return True, f"team {team_id} requires {field} before this transition"
        return False, f"team {team_id} has no '{field}' rule"

    # ── pre-validation against learned constraints (enum + required-field) ───
    def _prevalidate(self, cap_name: str, args: dict[str, Any], ctx: ExecutionContext, sr: StepReport) -> dict[str, Any]:
        if cap_name not in ("create_issue", "update_issue"):
            return args
        entity = "issue"
        # Enum constraints for ANY field present (not hard-coded to priority):
        # map NL→code and clamp out-of-range values from learned ENUM facts.
        for arg in list(args):
            c = self.memory.capability.enum_constraint(f"{entity}.{arg}")
            if not c or not isinstance(c.value, dict):
                continue
            val = args[arg]
            mapping = c.value.get("map") or {}
            rng = c.value.get("range")
            if isinstance(val, str) and val.lower() in mapping:
                args = {**args, arg: mapping[val.lower()]}
                self._note(sr, ctx, f"{entity}.{arg}", f"mapped '{val}' → {args[arg]} from learned enum")
            elif rng and isinstance(val, int) and not (rng[0] <= val <= rng[1]):
                clamped = max(rng[0], min(rng[1], val))
                args = {**args, arg: clamped}
                # Honest: this overrides an explicit out-of-range value — flag it, don't hide it.
                sr.error = (sr.error or "") + f"note: clamped {arg} {val}→{clamped} to learned range {rng}; "
                self._note(sr, ctx, f"{entity}.{arg}", f"clamped {arg} {val}→{clamped} (learned range {rng}); avoided a failed call")
                self.memory.capability.bump_hit(kind=ConstraintKind.ENUM, scope="field", key=f"{entity}.{arg}")
        # Required-field constraints: advise (don't fabricate) when a known-required field is absent.
        for c in self.memory.capability.get_constraints(scope="mutation", key=cap_name, kind=ConstraintKind.REQUIRED_FIELD):
            for field in (c.value or []):
                if field not in args:
                    sr.provenance.append(CallAttribution(
                        kind="pre_validated", ref=f"constraint:mutation/{cap_name}",
                        detail=f"memory flags '{field}' as required for {cap_name} but it is absent"))
        return args

    @staticmethod
    def _note(sr: StepReport, ctx: ExecutionContext, key: str, detail: str) -> None:
        att = CallAttribution(kind="pre_validated", ref=f"constraint:field/{key}", detail=detail)
        sr.provenance.append(att)
        ctx.note_saving(att)
