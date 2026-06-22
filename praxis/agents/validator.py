"""Validator — decides the run's status, scores confidence, and calls rollback.

Confidence scoring (nice-to-have) is honest about uncertainty: a run leaning on
a freshly-synthesized *probationary* capability, or that hit avoidable failures,
is reported as less confident even if it "worked". When a required step fails
after side effects were applied, the validator triggers best-effort compensation
so the workspace is not left half-mutated.
"""

from __future__ import annotations

from ..capabilities.registry import ExecutionContext
from ..models import (
    CapabilitySource,
    CapabilityStatus,
    Decision,
    ExecutionStatus,
    Plan,
    Reversibility,
    StepReport,
    StepStatus,
)


class Validator:
    def __init__(self, registry, memory) -> None:
        self.registry = registry
        self.memory = memory

    def assess(self, plan: Plan, steps: list[StepReport]) -> tuple[ExecutionStatus, float, list[str]]:
        required = [s for s in plan.steps if not s.optional]
        required_idx = {s.index for s in required}
        by_idx = {s.index: s for s in steps}

        successes = [s for s in steps if s.status == StepStatus.SUCCESS]
        req_failed = [s for s in steps if s.index in required_idx and s.status in (StepStatus.FAILED, StepStatus.SKIPPED)]

        if not req_failed:
            status = ExecutionStatus.SUCCESS
        elif successes:
            status = ExecutionStatus.PARTIAL
        else:
            status = ExecutionStatus.FAILED

        # ── confidence ──────────────────────────────────────────────────────
        notes: list[str] = []
        conf = {ExecutionStatus.SUCCESS: 0.95, ExecutionStatus.PARTIAL: 0.55, ExecutionStatus.FAILED: 0.15}[status]
        if req_failed:
            notes.append(f"{len(req_failed)} required step(s) did not succeed")
        wasted = sum(s.wasted_calls for s in steps)
        if wasted:
            conf -= 0.05 * wasted
            notes.append(f"{wasted} avoidable failed call(s) this run")
        # probationary synthesized capabilities → lower confidence
        for s in steps:
            if not s.capability:
                continue
            spec = self.memory.capability.get_capability(s.capability)
            if spec and spec.source == CapabilitySource.SYNTHESIZED and spec.status == CapabilityStatus.PROBATIONARY:
                conf -= 0.1
                notes.append(f"used probationary capability '{s.capability}' (not yet proven on repeated runs)")
        if plan.source.value in ("reused", "adapted"):
            conf += 0.03
            notes.append(f"plan {plan.source.value} from prior successful execution")
        conf = max(0.05, min(0.99, conf))
        return status, round(conf, 2), notes

    def should_rollback(self, status: ExecutionStatus, ctx: ExecutionContext) -> bool:
        applied = [e for e in ctx.journal if not e.compensated]
        return status in (ExecutionStatus.FAILED, ExecutionStatus.PARTIAL) and bool(applied)


def compensate(ctx: ExecutionContext) -> tuple[list[str], list[str], list[Decision]]:
    """Best-effort compensation in reverse order. Returns (rolled_back, manual_cleanup, decisions).

    Reversible/archive-only effects are compensated by running their inverse
    capability. Irreversible effects (sent notifications, posted comments) are
    surfaced for manual cleanup — never silently treated as undone.
    """
    rolled_back: list[str] = []
    manual_cleanup: list[str] = []
    decisions: list[Decision] = []
    for effect in reversed(ctx.journal):
        if effect.compensated:
            continue
        if effect.reversibility == Reversibility.IRREVERSIBLE or not effect.compensating_capability:
            manual_cleanup.append(f"{effect.description} [{effect.reversibility.value}]")
            continue
        try:
            ctx.registry.run(effect.compensating_capability, ctx, **effect.compensating_args)
            effect.compensated = True
            rolled_back.append(effect.description)
        except Exception as e:  # noqa: BLE001 — a failed compensation must be reported loudly
            effect.compensation_error = str(e)
            manual_cleanup.append(f"{effect.description} (compensation FAILED: {e})")
    if rolled_back or manual_cleanup:
        decisions.append(Decision(
            stage="validate",
            summary=f"Rolled back {len(rolled_back)} effect(s); {len(manual_cleanup)} need manual cleanup",
            rationale="Required step failed after side effects were applied → best-effort compensation.",
        ))
    return rolled_back, manual_cleanup, decisions
