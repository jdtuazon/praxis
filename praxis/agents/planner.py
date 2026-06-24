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

from ..llm.base import LLM
from ..memory import compute_signature
from ..models import (
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

When the goal is to produce a digest / report / summary / rollup DOCUMENT from many items
(gather → filter/group → format → save), plan it as a SINGLE step with "capability": null. One
synthesized capability does the whole job end-to-end, INCLUDING creating the document. Do NOT add a
separate create_document step after such a step — the synthesized capability already persists its own
output, so a second create_document just duplicates the document and usually binds its `content` to a
field the prior step never returned. Only use a standalone create_document step when its `content`
comes from explicit arguments, not from a synthesized gather/format step.
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
            decisions.append(
                Decision(
                    stage="plan",
                    summary=f"Reused cached plan shape from execution #{reusable.execution_id} (no re-planning)",
                    rationale=f"Exact-signature match '{sig}', proven {reusable.success_count}×.",
                )
            )
        else:
            hint = None
            if reusable:
                hint = reusable.plan
                decisions.append(
                    Decision(
                        stage="plan",
                        summary=f"Adapted plan shape from execution #{reusable.execution_id}",
                        rationale=f"Same intent-signature '{sig}', different parameters → reuse structure, re-bind content.",
                    )
                )
            plan = self._fresh_plan(instruction, available_caps, hint)
            plan.source = PlanSource.ADAPTED if reusable else PlanSource.FRESH
            plan.reused_from_execution_id = reusable.execution_id if reusable else None
            plan.intent_signature = sig

        # Constraint-driven plan rewriting (the decision change).
        self._apply_workflow_rules(plan, decisions)
        return plan, decisions

    # ── fresh decomposition ────────────────────────────────────────────────
    def _capability_catalog(self, available_caps: list[str]) -> str:
        """Render name(args) — description for each capability so the LLM binds args correctly."""
        specs = {s.name: s for s in self.memory.capability.list_capabilities()}
        lines = []
        for name in available_caps:
            spec = specs.get(name)
            if spec:
                args = ", ".join(spec.input_schema) if spec.input_schema else ""
                lines.append(f"- {name}({args}) — {spec.description}")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    def _fresh_plan(self, instruction: str, available_caps: list[str], hint: Plan | None) -> Plan:
        prompt = f"INSTRUCTION: {instruction}\n\nAVAILABLE CAPABILITIES:\n{self._capability_catalog(available_caps)}\n"
        if hint:
            shape = " → ".join(f"{s.capability or 'SYNTHESIZE'}" for s in hint.steps)
            prompt += f"\nA known-good plan shape for this kind of instruction (adapt the arguments): {shape}\n"
        data = self.llm.generate_json(PLANNER_SYSTEM, prompt, max_tokens=1500)
        steps_raw = data.get("steps", []) if isinstance(data, dict) else []
        steps = []
        for i, s in enumerate(steps_raw):
            steps.append(
                PlanStep(
                    index=s.get("index", i),
                    intent=s.get("intent", ""),
                    capability=s.get("capability"),
                    args=s.get("args", {}) or {},
                    depends_on=s.get("depends_on", []) or [],
                    optional=bool(s.get("optional", False)),
                )
            )
        return Plan(
            instruction=instruction,
            steps=steps,
            rationale=data.get("rationale", "") if isinstance(data, dict) else "",
            confidence=0.6,
        )

    # ── constraint-driven rewriting ──────────────────────────────────────────
    def _apply_workflow_rules(self, plan: Plan, decisions: list[Decision]) -> None:
        """Insert a precondition step ahead of a state transition that a learned
        WORKFLOW_RULE requires (generic: `requires <field> before <state-type>`).

        Correctness guarantees:
          • never inserts if another step already sets that field on the same
            target (no duplicate / no overwriting a user-supplied value);
          • the inserted step is *conditional* — its `inserted_by_constraint` tag
            tells the executor to verify, at run time, that the target issue's
            team actually has the rule (team is unknown at plan time). If not, the
            executor no-ops it. This keeps the rewrite visible without applying a
            rule team-blindly.
        """
        rules = [
            r
            for r in self.memory.capability.get_constraints(kind=ConstraintKind.WORKFLOW_RULE)
            if isinstance(r.value, dict) and r.value.get("requires") and r.value.get("before")
        ]
        if not rules:
            return
        rule = rules[0]
        req_field = rule.value["requires"]
        default_val = rule.value.get("default_value", rule.value.get("default_estimate", 1))

        new_steps: list[PlanStep] = []
        changed = False
        next_index = max((s.index for s in plan.steps), default=-1) + 1
        for step in plan.steps:
            transitions = (
                step.capability == "update_issue"
                and "stateId" in step.args
                and req_field not in step.args
                and any(
                    w in (step.intent or "").lower()
                    for w in ("done", "complete", "close", "finish")
                )
            )
            target = step.args.get("id", "")
            # Does another step already set this field on the same target? Then
            # depend on it instead of inserting a (possibly overwriting) duplicate.
            sibling = next(
                (
                    s
                    for s in plan.steps
                    if s is not step
                    and s.capability == "update_issue"
                    and s.args.get("id") == target
                    and req_field in s.args
                ),
                None,
            )
            if transitions and sibling is None:
                est_step = PlanStep(
                    index=next_index,
                    intent=f"set {req_field} (a learned rule requires it before this transition)",
                    capability="update_issue",
                    args={"id": target, req_field: default_val},
                    depends_on=list(step.depends_on),
                    inserted_by_constraint=f"workflow_rule:{req_field}-before-{rule.value['before']}",
                )
                next_index += 1
                step.depends_on = list(set(step.depends_on) | {est_step.index})
                new_steps.append(est_step)
                changed = True
            elif transitions and sibling is not None:
                step.depends_on = list(set(step.depends_on) | {sibling.index})
            new_steps.append(step)

        if changed:
            plan.steps = new_steps
            decisions.append(
                Decision(
                    stage="plan",
                    summary=f"Rewrote the plan: inserted a '{req_field}' step before the transition",
                    rationale="Learned WORKFLOW_RULE pre-empts a failure the agent hit before "
                    "(verified against the issue's team at execution time).",
                )
            )
