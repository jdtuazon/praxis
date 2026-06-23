"""Execution memory — Layer 1: what the agent has done before.

Stores past instructions, how they were decomposed, the outcome, and the
timing/cost. Crucially it also maintains a `plan_cache` of the best successful
plan *shape* per intent-signature, which is what the planner reuses (re-binding
all volatile ids at execution time) to avoid re-decomposing from scratch.
"""

from __future__ import annotations

from ..models import ExecutionReport, Plan, PlanSource
from .retrieval import cosine_similarity
from .signature import compute_signature
from .store import MemoryStore


class ReusablePlan:
    def __init__(
        self,
        plan: Plan,
        execution_id: int,
        success_count: int,
        avg_api_calls: float,
        similarity: float,
        origin_instruction: str,
    ):
        self.plan = plan
        self.execution_id = execution_id
        self.success_count = success_count
        self.avg_api_calls = avg_api_calls
        self.similarity = similarity
        self.origin_instruction = origin_instruction


class ExecutionMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ── retrieval (read before planning) ──────────────────────────────────
    def find_reusable_plan(
        self, instruction: str, *, min_similarity: float = 0.0
    ) -> ReusablePlan | None:
        """Return a cached plan SHAPE for this instruction's signature, if any.

        Reuse is gated on an exact structured-signature match. Surface-text
        similarity is only reported (for confidence), never used to *select* a
        structurally different plan.
        """
        sig = compute_signature(instruction)
        row = self.store.one("SELECT * FROM plan_cache WHERE signature = ?", (sig,))
        if not row:
            return None
        plan = Plan.model_validate(self.store.loads(row["plan_json"]))
        # similarity to the originating instruction (tie-break / confidence signal)
        src = self.store.one(
            "SELECT instruction FROM executions WHERE id = ?", (row["execution_id"],)
        )
        origin = src["instruction"] if src else instruction
        sim = cosine_similarity(instruction, origin)
        if sim < min_similarity:
            return None
        return ReusablePlan(
            plan, row["execution_id"], row["success_count"], row["avg_api_calls"], sim, origin
        )

    def similar_instructions(self, instruction: str, limit: int = 5) -> list[tuple[str, str]]:
        rows = self.store.query("SELECT DISTINCT instruction, signature FROM executions")
        texts = [r["instruction"] for r in rows]
        scored = sorted(
            ((cosine_similarity(instruction, t), rows[i]) for i, t in enumerate(texts)),
            key=lambda x: x[0],
            reverse=True,
        )
        return [(r["instruction"], r["signature"]) for s, r in scored[:limit] if s > 0]

    def run_number(self, signature: str) -> int:
        """1-based count of how many times this signature has been executed (incl. this)."""
        row = self.store.one(
            "SELECT COUNT(*) AS n FROM executions WHERE signature = ?", (signature,)
        )
        return int(row["n"]) + 1 if row else 1

    def first_run(self, signature: str) -> StoredExecution | None:
        row = self.store.one(
            "SELECT * FROM executions WHERE signature = ? ORDER BY id ASC LIMIT 1", (signature,)
        )
        return StoredExecution(row) if row else None

    def last_run(self, signature: str) -> StoredExecution | None:
        row = self.store.one(
            "SELECT * FROM executions WHERE signature = ? ORDER BY id DESC LIMIT 1", (signature,)
        )
        return StoredExecution(row) if row else None

    # ── writes (after a run) ───────────────────────────────────────────────
    def record_instruction(self, instruction: str, signature: str) -> None:
        self.store.execute(
            "INSERT INTO instructions(text, signature, created_at) VALUES (?,?,?)",
            (instruction, signature, self.store.now()),
        )

    def record_execution(self, report: ExecutionReport) -> int:
        sig = report.plan.intent_signature or compute_signature(report.instruction)
        cur = self.store.execute(
            """INSERT INTO executions
               (instruction, signature, status, plan_json, plan_source, api_calls, llm_calls,
                wasted_calls, duration_s, tokens, confidence, synthesized, started_at, finished_at, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                report.instruction,
                sig,
                report.status.value,
                self.store.dumps(report.plan.model_dump(mode="json")),
                report.plan.source.value,
                report.total_api_calls,
                report.total_llm_calls,
                report.wasted_calls,
                report.duration_s,
                report.total_tokens,
                report.confidence,
                len(report.synthesized_capabilities),
                report.started_at,
                report.finished_at,
                report.summary,
            ),
        )
        exec_id = int(cur.lastrowid)
        self.record_instruction(report.instruction, sig)
        # Update the plan-cache only on a fully successful run, storing the SHAPE.
        if report.status.value == "success":
            self._upsert_plan_cache(sig, report.plan, exec_id, report.total_api_calls)
        self.store.commit()
        return exec_id

    def _upsert_plan_cache(
        self, signature: str, plan: Plan, execution_id: int, api_calls: int
    ) -> None:
        # Persist the BASE shape only: steps inserted by a learned constraint are
        # stripped so the rewrite is re-derived live from current memory each run.
        # (This keeps the learned constraint the sole cause of the decision change,
        # so a constraint-only wipe genuinely reverts behaviour — a clean control.)
        shape = plan.model_copy(deep=True)
        removed = {s.index for s in shape.steps if s.inserted_by_constraint}
        if removed:
            base_steps = [s for s in shape.steps if not s.inserted_by_constraint]
            for s in base_steps:
                s.depends_on = [d for d in s.depends_on if d not in removed]
            shape.steps = base_steps
        shape.source = PlanSource.REUSED
        shape.reused_from_execution_id = execution_id
        existing = self.store.one("SELECT * FROM plan_cache WHERE signature = ?", (signature,))
        if existing:
            sc = existing["success_count"] + 1
            avg = (existing["avg_api_calls"] * existing["success_count"] + api_calls) / sc
            self.store.execute(
                "UPDATE plan_cache SET plan_json=?, execution_id=?, success_count=?, avg_api_calls=?, updated_at=? WHERE signature=?",
                (
                    self.store.dumps(shape.model_dump(mode="json")),
                    execution_id,
                    sc,
                    avg,
                    self.store.now(),
                    signature,
                ),
            )
        else:
            self.store.execute(
                "INSERT INTO plan_cache(signature, plan_json, execution_id, success_count, avg_api_calls, updated_at) VALUES (?,?,?,?,?,?)",
                (
                    signature,
                    self.store.dumps(shape.model_dump(mode="json")),
                    execution_id,
                    1,
                    float(api_calls),
                    self.store.now(),
                ),
            )


class StoredExecution:
    def __init__(self, row) -> None:
        self.id = row["id"]
        self.instruction = row["instruction"]
        self.signature = row["signature"]
        self.status = row["status"]
        self.api_calls = row["api_calls"]
        self.llm_calls = row["llm_calls"]
        self.wasted_calls = row["wasted_calls"]
        self.duration_s = row["duration_s"]
        self.synthesized = row["synthesized"]
