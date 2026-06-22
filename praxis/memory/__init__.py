"""Persistent memory: two distinct, structured layers over one SQLite file.

`Memory` is the facade the orchestrator uses. It exposes the two layers the
assignment requires explicitly — `memory.execution` and `memory.capability` —
plus snapshot/diff helpers so every run can show *what changed and why*.
"""

from __future__ import annotations

from pathlib import Path

from ..models import MemoryCounts, MemoryDiff, MemorySnapshot
from .capability_memory import CapabilityMemory
from .compaction import Compactor
from .execution_memory import ExecutionMemory
from .signature import compute_signature
from .store import MemoryStore

__all__ = ["Memory", "MemoryStore", "compute_signature"]


class Memory:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.store = MemoryStore(path)
        self.execution = ExecutionMemory(self.store)
        self.capability = CapabilityMemory(self.store)
        self.compactor = Compactor(self.store)

    # ── snapshots / diffs ──────────────────────────────────────────────────
    def snapshot(self) -> MemorySnapshot:
        counts = self.store.counts()
        cap_names = [r["name"] for r in self.store.query("SELECT name FROM capabilities ORDER BY name")]
        con_keys = [
            f"{r['scope']}/{r['key']}"
            for r in self.store.query(
                "SELECT scope, key FROM constraints WHERE invalidated_by IS NULL ORDER BY scope, key"
            )
        ]
        return MemorySnapshot(counts=MemoryCounts(**counts), capability_names=cap_names, constraint_keys=con_keys)

    @staticmethod
    def diff(before: MemorySnapshot, after: MemorySnapshot) -> MemoryDiff:
        new_caps = [c for c in after.capability_names if c not in before.capability_names]
        new_cons = [c for c in after.constraint_keys if c not in before.constraint_keys]
        lines: list[str] = []
        d_exec = after.counts.executions - before.counts.executions
        if d_exec:
            lines.append(f"executions {before.counts.executions} → {after.counts.executions}")
        if new_caps:
            lines.append(f"+{len(new_caps)} capability: {', '.join(new_caps)}")
        if new_cons:
            lines.append(f"+{len(new_cons)} constraint: {', '.join(new_cons)}")
        if after.counts.constraints != before.counts.constraints and not new_cons:
            lines.append(f"constraints {before.counts.constraints} → {after.counts.constraints}")
        return MemoryDiff(new_capabilities=new_caps, new_constraints=new_cons, lines=lines)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def wipe_constraints(self) -> None:
        """Negative control: drop the learned world-model but keep capabilities/plans."""
        self.store.execute("DELETE FROM constraints")
        self.store.commit()

    def reset(self) -> None:
        for t in ("instructions", "executions", "plan_cache", "capabilities",
                  "capability_stats", "constraints", "memory_digests"):
            self.store.execute(f"DELETE FROM {t}")
        self.store.commit()

    def close(self) -> None:
        self.store.close()
