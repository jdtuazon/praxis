"""The Praxis agent: a LangGraph state machine coordinating specialist components.

Flow:  plan → execute → validate → (compensate?) → learn → END

Each node is a thin closure over a specialist (Planner, Executor+Synthesizer,
Validator, Learner). LangGraph is used as the deterministic, inspectable control
spine — the conditional edge into compensation is a genuine branch, not a
straight line. The learner node closes the self-improvement loop: every run
ends by writing structured knowledge that changes the next run.
"""

from __future__ import annotations

import time
from typing import Optional

from langgraph.graph import END, START, StateGraph

from ..agents.executor import Executor
from ..agents.learner import Learner
from ..agents.planner import Planner
from ..agents.validator import Validator, compensate
from ..capabilities import CapabilityRegistry, ExecutionContext, Synthesizer, register_builtins
from ..capabilities.registry import Capability
from ..config import Settings
from ..llm.base import LLM
from ..memory import Memory, compute_signature
from ..models import (
    CapabilityKind,
    CapabilitySource,
    ExecutionReport,
    ExecutionStatus,
    StepStatus,
)
from .state import GraphState


class PraxisAgent:
    """End-to-end agent: natural-language instruction → platform execution + learning."""

    def __init__(self, *, llm: LLM, client, memory: Memory, settings: Settings) -> None:
        self.llm = llm
        self.client = client
        self.memory = memory
        self.settings = settings

        self.registry = CapabilityRegistry()
        register_builtins(self.registry, memory)
        self._load_synthesized_capabilities()

        self.planner = Planner(llm, memory)
        self.synthesizer = Synthesizer(llm, client, self.registry, memory, settings)
        self.executor = Executor(self.registry, memory, settings)
        self.validator = Validator(self.registry, memory)
        self.learner = Learner(memory, settings)
        self._graph = self._build_graph()

    # ── load previously-synthesized capabilities from memory ────────────────
    def _load_synthesized_capabilities(self) -> None:
        for spec in self.memory.capability.list_capabilities(source=CapabilitySource.SYNTHESIZED):
            # Stale-schema guard: a synthesized GraphQL cap built against a
            # different schema is marked for re-test rather than blindly reused.
            if spec.kind == CapabilityKind.GRAPHQL and spec.schema_hash and spec.schema_hash != self.client.schema_hash():
                continue
            self.registry.register(Capability(spec=spec))

    # ── graph wiring ─────────────────────────────────────────────────────────
    def _build_graph(self):
        g = StateGraph(GraphState)
        g.add_node("plan", self._node_plan)
        g.add_node("execute", self._node_execute)
        g.add_node("validate", self._node_validate)
        g.add_node("compensate", self._node_compensate)
        g.add_node("learn", self._node_learn)
        g.add_edge(START, "plan")
        g.add_edge("plan", "execute")
        g.add_edge("execute", "validate")
        g.add_conditional_edges("validate", lambda s: "compensate" if s.get("do_rollback") else "learn",
                                {"compensate": "compensate", "learn": "learn"})
        g.add_edge("compensate", "learn")
        g.add_edge("learn", END)
        return g.compile()

    # ── nodes ─────────────────────────────────────────────────────────────────
    def _node_plan(self, state: GraphState) -> dict:
        report = state["report"]
        plan, decisions = self.planner.plan(state["instruction"], available_caps=self.registry.names())
        report.plan = plan
        report.decisions.extend(decisions)
        return {"plan": plan}

    def _node_execute(self, state: GraphState) -> dict:
        report, ctx, plan = state["report"], state["ctx"], state["plan"]
        steps, decisions, synth = self.executor.execute(plan, ctx, self.synthesizer)
        report.steps = steps
        report.decisions.extend(decisions)
        report.synthesis = synth
        report.synthesized_capabilities = [r.capability_name for r in synth if r.success and r.capability_name]
        return {}

    def _node_validate(self, state: GraphState) -> dict:
        report, ctx, plan = state["report"], state["ctx"], state["plan"]
        status, conf, notes = self.validator.assess(plan, report.steps)
        report.status = status
        report.confidence = conf
        report.confidence_notes = notes
        return {"do_rollback": self.validator.should_rollback(status, ctx)}

    def _node_compensate(self, state: GraphState) -> dict:
        report, ctx = state["report"], state["ctx"]
        rolled, manual, decisions = compensate(ctx)
        report.rollback_performed = bool(rolled or manual)
        report.rollback_steps = rolled
        report.manual_cleanup_required = manual
        report.decisions.extend(decisions)
        compensated_idx = {e.step_index for e in ctx.journal if e.compensated}
        for s in report.steps:
            if s.index in compensated_idx and s.status == StepStatus.SUCCESS:
                s.rolled_back = True
                s.status = StepStatus.ROLLED_BACK
        if report.rollback_performed:
            report.status = ExecutionStatus.ROLLED_BACK
        return {}

    def _node_learn(self, state: GraphState) -> dict:
        report, ctx, plan = state["report"], state["ctx"], state["plan"]
        duration = time.time() - state["t0"]
        report.total_api_calls = self.client.api_calls - state["api_before"]
        report.total_llm_calls = self.llm.usage.calls - state["llm_before"]
        report.total_tokens = self.llm.usage.total_tokens - state["tokens_before"]
        report.wasted_calls = ctx.wasted_calls
        report.duration_s = round(duration, 4)
        failed_steps = sum(1 for s in report.steps if s.status in (StepStatus.FAILED, StepStatus.SKIPPED))

        # learning comparison BEFORE recording this run (baseline = first prior run)
        report.learning = self.learner.compare(
            plan, api_calls=report.total_api_calls, llm_calls=report.total_llm_calls,
            wasted_calls=report.wasted_calls, duration_s=duration, failed_steps=failed_steps,
            synthesized=len(report.synthesized_capabilities), ctx=ctx,
        )
        # record execution → exec id, then extract knowledge with provenance
        exec_id = self.memory.execution.record_execution(report)
        report.execution_id = exec_id
        report.discovered_constraints = self.learner.learn(ctx, execution_id=exec_id, plan=plan, steps=report.steps)
        return {}

    # ── public API ─────────────────────────────────────────────────────────
    def run(self, instruction: str) -> ExecutionReport:
        memory_before = self.memory.snapshot()
        ctx = ExecutionContext(client=self.client, registry=self.registry,
                               memory=self.memory, settings=self.settings)
        report = ExecutionReport(
            instruction=instruction, status=ExecutionStatus.FAILED,
            started_at=time.time(), finished_at=0.0, plan=_empty_plan(instruction),
        )
        state: GraphState = {
            "instruction": instruction, "report": report, "ctx": ctx,
            "t0": time.time(), "api_before": self.client.api_calls, "llm_before": self.llm.usage.calls,
            "tokens_before": self.llm.usage.total_tokens,
        }
        self._graph.invoke(state)

        report.finished_at = time.time()
        memory_after = self.memory.snapshot()
        report.memory_before = memory_before
        report.memory_after = memory_after
        report.memory_diff = Memory.diff(memory_before, memory_after)
        report.summary = _summarize_report(report)
        return report


def _empty_plan(instruction: str):
    from ..models import Plan
    return Plan(instruction=instruction, intent_signature=compute_signature(instruction))


def _summarize_report(report: ExecutionReport) -> str:
    n_ok = sum(1 for s in report.steps if s.status == StepStatus.SUCCESS)
    parts = [f"{report.status.value.upper()}", f"{n_ok}/{len(report.steps)} steps",
             f"{report.total_api_calls} API calls"]
    if report.wasted_calls:
        parts.append(f"{report.wasted_calls} wasted")
    if report.synthesized_capabilities:
        parts.append(f"synthesized {', '.join(report.synthesized_capabilities)}")
    if report.learning.wasted_calls_saved:
        parts.append(f"avoided {report.learning.wasted_calls_saved} wasted vs first run")
    return " · ".join(parts)
