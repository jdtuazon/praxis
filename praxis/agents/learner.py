"""Learner — turns a finished run into structured knowledge that changes the next.

It does the work that separates "memory" from "a log":
  • extracts CONSTRAINTS from failures (enum ranges, workflow rules, permission
    boundaries, rate limits) and from successes (cached entity ids, the
    workspace's priority vocabulary observed in responses);
  • updates per-capability stats and PROMOTES a probationary synthesized
    capability to trusted once it has proven itself on real runs;
  • computes the learning comparison (wasted-call avoidance + reuse savings,
    each attributed to the memory artifact responsible).
"""

from __future__ import annotations

from typing import Any

from ..capabilities.registry import ExecutionContext
from ..models import (
    CapabilitySource,
    CapabilityStatus,
    Constraint,
    ConstraintKind,
    ConstraintOrigin,
    LearningComparison,
    Plan,
    StepReport,
    StepStatus,
    VerificationPolicy,
)


class Learner:
    def __init__(self, memory, settings) -> None:
        self.memory = memory
        self.settings = settings

    # ── learning comparison (the measurable signal) ────────────────────────
    def compare(self, plan: Plan, *, api_calls: int, llm_calls: int, wasted_calls: int,
                duration_s: float, failed_steps: int, synthesized: int, ctx: ExecutionContext) -> LearningComparison:
        sig = plan.intent_signature
        run_number = self.memory.execution.run_number(sig)
        baseline = self.memory.execution.first_run(sig)
        mode = {"reused": "reuse", "adapted": "transfer", "fresh": "fresh"}.get(plan.source.value, "fresh")
        # Reusing a capability synthesized for a *related* instruction is transfer,
        # even when this exact signature is new.
        if mode == "fresh" and any(a.kind == "reused_capability" for a in ctx.attributions):
            mode = "transfer"

        cmp = LearningComparison(
            instruction_signature=sig, mode=mode, run_number=run_number, is_repeat=run_number > 1,
            api_calls=api_calls, llm_calls=llm_calls, wasted_calls=wasted_calls,
            duration_s=round(duration_s, 4), failed_steps=failed_steps, synthesized=synthesized,
            saved_calls=list(ctx.attributions),
        )
        if baseline:
            cmp.baseline_api_calls = baseline.api_calls
            cmp.baseline_llm_calls = baseline.llm_calls
            cmp.baseline_wasted_calls = baseline.wasted_calls
            cmp.baseline_duration_s = baseline.duration_s
            cmp.api_calls_saved = max(0, baseline.api_calls - api_calls)
            cmp.llm_calls_saved = max(0, baseline.llm_calls - llm_calls)
            cmp.wasted_calls_saved = max(0, baseline.wasted_calls - wasted_calls)
            if baseline.duration_s > 0:
                cmp.speedup_pct = round(100 * (baseline.duration_s - duration_s) / baseline.duration_s, 1)

        # human-readable attributions
        for att in ctx.attributions:
            cmp.attributions.append(f"{att.kind}: {att.detail} ({att.ref})")
        if cmp.wasted_calls_saved:
            cmp.attributions.append(
                f"avoided {cmp.wasted_calls_saved} previously-wasted call(s) via learned constraints"
            )
        if mode == "transfer":
            cmp.attributions.append("transfer: applied knowledge from a related instruction's prior runs")
        return cmp

    # ── knowledge extraction (writes to memory) ─────────────────────────────
    def learn(self, ctx: ExecutionContext, *, execution_id: int, plan: Plan, steps: list[StepReport]) -> list[str]:
        discovered: list[str] = []

        # 1) constraints from observations (failures + resolver successes)
        for obs in ctx.observations:
            if obs.get("type") == "resolver_success":
                self.memory.capability.upsert_constraint(Constraint(
                    kind=ConstraintKind.ENTITY_ID, origin=ConstraintOrigin.RUNTIME_LEARNED,
                    scope="entity", key=obs["key"], value=obs["value"],
                    description=f"cached {obs['capability']} result",
                    verification_policy=VerificationPolicy.TRUST,
                    discovered_from_execution=execution_id,
                ))
            elif obs.get("type") == "platform_error":
                c = self._constraint_from_error(obs, execution_id)
                if c:
                    self.memory.capability.upsert_constraint(c)
                    discovered.append(f"{c.kind.value}: {c.scope}/{c.key} — {c.description}")

        # 2) learn the workspace's priority vocabulary from successful responses
        self._learn_priority_vocab(ctx, execution_id, discovered)

        # 3) update capability stats + promote probationary → trusted.
        # Only clean evidence counts: a SUCCESS is success, a FAILED is failure.
        # SKIPPED (never attempted) and ROLLED_BACK (the run failed and was
        # compensated for *other* reasons) are excluded entirely — counting them
        # as success would inflate health and wrongly promote a capability whose
        # runs actually failed; counting them as failure would penalise it unfairly.
        for s in steps:
            if not s.capability or s.status in (StepStatus.SKIPPED, StepStatus.ROLLED_BACK):
                continue
            self.memory.capability.record_capability_use(
                s.capability, plan.intent_signature,
                success=(s.status == StepStatus.SUCCESS),
                duration=s.duration_s, api_calls=s.api_calls,
            )
            self._maybe_promote(s.capability, discovered)
            self._maybe_demote(s.capability, s.status, discovered)
        return discovered

    def _constraint_from_error(self, obs: dict, execution_id: int) -> Constraint | None:
        code = obs.get("code")
        ext = obs.get("extensions", {}) or {}
        args = obs.get("args", {}) or {}
        if code == "WORKFLOW_RULE":
            team = ext.get("team") or args.get("teamId") or "unknown"
            return Constraint(
                kind=ConstraintKind.WORKFLOW_RULE, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="team", key=team, rewrites_plan=True,
                value={"requires": ext.get("requires", "estimate"),
                       "before": ext.get("before_state_type", "completed"), "default_estimate": 1},
                description=f"{ext.get('requires','estimate')} required before {ext.get('before_state_type','completed')} transition",
                discovered_from_execution=execution_id,
            )
        if code == "INVALID_INPUT" and ext.get("field") == "priority" and ext.get("allowed"):
            allowed = ext["allowed"]
            existing = self.memory.capability.enum_constraint("issue.priority")
            value = dict(existing.value) if existing and isinstance(existing.value, dict) else {}
            value["range"] = [allowed.get("min", 0), allowed.get("max", 4)]
            return Constraint(
                kind=ConstraintKind.ENUM, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="field", key="issue.priority", value=value,
                description=f"priority must be in {value['range']}",
                discovered_from_execution=execution_id,
            )
        if code == "INVALID_INPUT" and ext.get("field"):
            return Constraint(
                kind=ConstraintKind.REQUIRED_FIELD, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="mutation", key=obs.get("capability", "unknown"), value=[ext["field"]],
                description=f"field '{ext['field']}' is required/invalid: {obs.get('message','')[:80]}",
                discovered_from_execution=execution_id,
            )
        if code == "FORBIDDEN":
            op = ext.get("operation") or obs.get("capability", "unknown")
            return Constraint(
                kind=ConstraintKind.PERMISSION, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="mutation", key=op, value="forbidden",
                description=f"token may not perform '{op}'",
                discovered_from_execution=execution_id,
            )
        if code == "RATELIMITED":
            return Constraint(
                kind=ConstraintKind.RATE_LIMIT, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="global", key="writes", value={"retry_after": ext.get("retryAfter", 2)},
                description="write rate limit observed", verification_policy=VerificationPolicy.REFETCH_TTL,
                ttl_seconds=600, discovered_from_execution=execution_id,
            )
        return None

    def _learn_priority_vocab(self, ctx: ExecutionContext, execution_id: int, discovered: list[str]) -> None:
        observed: dict[str, int] = {}
        for v in ctx.vars.values():
            for issue in _iter_issues(v):
                label, pr = issue.get("priorityLabel"), issue.get("priority")
                if label and isinstance(pr, int):
                    observed[label.lower()] = pr
        if not observed:
            return
        existing = self.memory.capability.enum_constraint("issue.priority")
        value = dict(existing.value) if existing and isinstance(existing.value, dict) else {}
        mp = dict(value.get("map") or {})
        # natural-language synonyms → codes (the workspace's vocabulary)
        synonyms = {"urgent": "urgent", "critical": "urgent", "p1": "urgent",
                    "high": "high", "medium": "medium", "low": "low", "no priority": "none"}
        for label, code in observed.items():
            mp[label] = code
            for syn, canon in synonyms.items():
                if canon in label or label in canon:
                    mp[syn] = code
        if mp != (value.get("map") or {}):
            value["map"] = mp
            value.setdefault("range", [0, 4])
            self.memory.capability.upsert_constraint(Constraint(
                kind=ConstraintKind.ENUM, origin=ConstraintOrigin.RUNTIME_LEARNED,
                scope="field", key="issue.priority", value=value,
                description="learned priority vocabulary from responses",
                discovered_from_execution=execution_id,
            ))
            discovered.append("enum: field/issue.priority — learned priority vocabulary from responses")

    def _maybe_promote(self, capability: str, discovered: list[str]) -> None:
        spec = self.memory.capability.get_capability(capability)
        if not spec or spec.source != CapabilitySource.SYNTHESIZED:
            return
        if spec.status == CapabilityStatus.PROBATIONARY:
            if self.memory.capability.success_count(capability) >= int(getattr(self.settings, "capability_promote_after", 2)):
                self.memory.capability.set_status(capability, CapabilityStatus.TRUSTED)
                discovered.append(f"promoted capability '{capability}' probationary → trusted")

    def _maybe_demote(self, capability: str, status, discovered: list[str]) -> None:
        if status != StepStatus.FAILED:
            return
        spec = self.memory.capability.get_capability(capability)
        if spec and spec.source == CapabilitySource.SYNTHESIZED and spec.status in (
            CapabilityStatus.TRUSTED, CapabilityStatus.PROBATIONARY
        ):
            self.memory.capability.set_status(capability, CapabilityStatus.DEMOTED)
            discovered.append(f"demoted capability '{capability}' → needs re-test (failed in the wild)")


def _iter_issues(value: Any):
    """Yield issue-like dicts from a step result (single issue, list, or nested)."""
    if isinstance(value, dict):
        if "priorityLabel" in value:
            yield value
        for v in value.values():
            yield from _iter_issues(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_issues(v)
