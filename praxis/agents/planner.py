"""Planner — decomposes an instruction into an executable plan.

Memory makes the planner behave differently over time:
  • exact repeats reuse the cached plan SHAPE verbatim → the planning LLM call is
    skipped entirely (a clean, labelled "reuse" saving);
  • related instructions (same intent-signature, different text) reuse the shape
    as a strong hint so the structure stays consistent while content re-binds;
  • learned WORKFLOW_RULE constraints *rewrite the plan* — e.g. inserting an
    estimate step before a "move to Done" transition. That is a different
    decision, not merely a faster path, and it is the headline learning effect.
"""

from __future__ import annotations

from typing import Optional

from ..llm.base import LLM
from ..memory import compute_signature
from ..models import (
    CallAttribution,
    Constraint,
    ConstraintKind,
    Decision,
    Plan,
    PlanSource,
    PlanStep,
)

PLANNER_SYSTEM = """[[ROLE:PLANNER]] You are Praxis's planner for the Linear platform.
Decompose the user's instruction into an ordered list of executable steps. Each step names ONE capability
and its arguments. Steps may reference an earlier step's output with {{stepN.path}} (e.g. {{step0.id}}).
If a sub-goal needs an operation no capability covers, set "capability": null — it will be synthesized.

Return ONLY JSON:
{
  "rationale": "one sentence",
  "steps": [
    {"index": 0, "intent": "resolve the team", "capability": "find_team", "args": {"name": "Engineering"}, "depends_on": []},
    {"index": 1, "intent": "create the issue", "capability": "create_issue",
     "args": {"teamId": "{{step0.id}}", "title": "Login times out", "priority": 2}, "depends_on": [0], "optional": false}
  ]
}
Priority integers: 1=Urgent, 2=High, 3=Medium, 4=Low, 0=None. Resolve 'me' with the `viewer` capability.
Use create_each-style compound work via a synthesized capability (capability:null) when many items are involved.
"""


class Planner:
    def __init__(self, llm: LLM, memory) -> None:
        self.llm = llm
        self.memory = memory

    def plan(self, instruction: str, *, available_caps: list[str]) -> tuple[Plan, list[Decision]]:
        decisions: list[Decision] = []
        sig = compute_signature(instruction)
        reusable = self.memory.execution.find_reusable_plan(instruction)

        if reusable and reusable.origin_instruction.strip().lower() == instruction.strip().lower():
            # Exact repeat → reuse the cached plan verbatim, skip the planning LLM call.
            plan = reusable.plan.model_copy(deep=True)
            plan.instruction = instruction
            plan.source = PlanSource.REUSED
            plan.reused_from_execution_id = reusable.execution_id
            plan.intent_signature = sig
            plan.confidence = min(0.99, 0.7 + 0.05 * reusable.success_count)
            decisions.append(Decision(
                stage="plan",
                summary=f"Reused cached plan shape from execution #{reusable.execution_id} (no re-planning)",
                rationale=f"Exact-signature match '{sig}', proven {reusable.success_count}×.",
            ))
        else:
            hint = None
            if reusable:
                hint = reusable.plan
                decisions.append(Decision(
                    stage="plan",
                    summary=f"Adapted plan shape from execution #{reusable.execution_id}",
                    rationale=f"Same intent-signature '{sig}', different parameters → reuse structure, re-bind content.",
                ))
            plan = self._fresh_plan(instruction, available_caps, hint)
            plan.source = PlanSource.ADAPTED if reusable else PlanSource.FRESH
            plan.reused_from_execution_id = reusable.execution_id if reusable else None
            plan.intent_signature = sig

        # Constraint-driven plan rewriting (the decision change).
        self._apply_workflow_rules(plan, decisions)
        return plan, decisions

    # ── fresh decomposition ────────────────────────────────────────────────
    def _fresh_plan(self, instruction: str, available_caps: list[str], hint: Optional[Plan]) -> Plan:
        prompt = f"INSTRUCTION: {instruction}\n\nAVAILABLE CAPABILITIES: {', '.join(available_caps)}\n"
        if hint:
            shape = " → ".join(f"{s.capability or 'SYNTHESIZE'}" for s in hint.steps)
            prompt += f"\nA known-good plan shape for this kind of instruction (adapt the arguments): {shape}\n"
        data = self.llm.generate_json(PLANNER_SYSTEM, prompt, max_tokens=1500)
        steps_raw = data.get("steps", []) if isinstance(data, dict) else []
        steps = []
        for i, s in enumerate(steps_raw):
            steps.append(PlanStep(
                index=s.get("index", i),
                intent=s.get("intent", ""),
                capability=s.get("capability"),
                args=s.get("args", {}) or {},
                depends_on=s.get("depends_on", []) or [],
                optional=bool(s.get("optional", False)),
            ))
        return Plan(
            instruction=instruction,
            steps=steps,
            rationale=data.get("rationale", "") if isinstance(data, dict) else "",
            confidence=0.6,
        )

    # ── constraint-driven rewriting ──────────────────────────────────────────
    def _apply_workflow_rules(self, plan: Plan, decisions: list[Decision]) -> None:
        """Insert/modify steps based on learned WORKFLOW_RULE constraints.

        Demo case: a team requires an estimate before an issue may transition to a
        completed state. If memory holds that rule, insert a set-estimate step
        ahead of any 'move to Done' update — turning a previously-failing call
        into a successful one *before* it is ever attempted.
        """
        rules = self.memory.capability.get_constraints(kind=ConstraintKind.WORKFLOW_RULE)
        if not rules:
            return
        estimate_rules = [r for r in rules if isinstance(r.value, dict) and r.value.get("requires") == "estimate"]
        if not estimate_rules:
            return

        new_steps: list[PlanStep] = []
        changed = False
        next_index = max((s.index for s in plan.steps), default=-1) + 1
        for step in plan.steps:
            moves_to_done = (
                step.capability == "update_issue"
                and ("stateId" in step.args)
                and ("estimate" not in step.args)
                and any(w in (step.intent or "").lower() for w in ("done", "complete", "close", "finish"))
            )
            if moves_to_done:
                rule = estimate_rules[0]
                default_estimate = (rule.value or {}).get("default_estimate", 1)
                # Insert an estimate step targeting the same issue, before the transition.
                target = step.args.get("id", "")
                est_step = PlanStep(
                    index=next_index,
                    intent="set estimate (required before Done by learned workflow rule)",
                    capability="update_issue",
                    args={"id": target, "estimate": default_estimate},
                    depends_on=list(step.depends_on),
                    inserted_by_constraint=f"team/{rule.key}:estimate-before-done",
                )
                next_index += 1
                step.depends_on = list(set(step.depends_on) | {est_step.index})
                new_steps.append(est_step)
                changed = True
                self.memory.capability.bump_hit(kind=ConstraintKind.WORKFLOW_RULE, scope=rule.scope, key=rule.key)
            new_steps.append(step)

        if changed:
            plan.steps = new_steps
            decisions.append(Decision(
                stage="plan",
                summary="Rewrote the plan: inserted an estimate step before the Done transition",
                rationale="Learned WORKFLOW_RULE: this team rejects completing an issue without an estimate. "
                          "Pre-empting the failure instead of hitting it.",
            ))
