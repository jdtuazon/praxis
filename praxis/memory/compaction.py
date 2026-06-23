"""Memory compaction (nice-to-have): summarise old execution rows.

Rather than letting execution memory grow without bound, compaction folds the
oldest runs of a signature into a single `memory_digests` row that preserves the
*aggregate* knowledge (run count, baseline vs latest cost, learning delta) while
deleting the verbose per-run records. The first run of each signature is kept as
the learning baseline; recent runs are kept for transfer analysis.
"""

from __future__ import annotations

from .store import MemoryStore


class Compactor:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def compact(self, *, keep_recent: int = 10) -> list[str]:
        notes: list[str] = []
        sigs = [r["signature"] for r in self.store.query("SELECT DISTINCT signature FROM executions")]
        for sig in sigs:
            rows = self.store.query(
                "SELECT * FROM executions WHERE signature = ? ORDER BY id ASC", (sig,)
            )
            if len(rows) <= keep_recent + 1:
                continue
            baseline = rows[0]
            # Candidates to fold: everything except the baseline and the most recent N.
            foldable = rows[1:-keep_recent]
            # Never delete a row still referenced by the plan_cache (it backs the
            # reusable plan's provenance + similarity scoring in find_reusable_plan).
            referenced = {r["execution_id"] for r in self.store.query("SELECT execution_id FROM plan_cache")}
            foldable = [r for r in foldable if r["id"] not in referenced]
            if not foldable:
                continue
            latest = rows[-1]
            summary = (
                f"{len(rows)} runs of '{sig}'. Baseline #{baseline['id']}: "
                f"{baseline['api_calls']} api / {baseline['wasted_calls']} wasted. "
                f"Latest #{latest['id']}: {latest['api_calls']} api / {latest['wasted_calls']} wasted. "
                f"Folded {len(foldable)} interim runs."
            )
            self.store.execute(
                "INSERT INTO memory_digests(signature, summary, covers_from, covers_to, created_at) VALUES (?,?,?,?,?)",
                (sig, summary, foldable[0]["started_at"], foldable[-1]["finished_at"], self.store.now()),
            )
            ids = [str(r["id"]) for r in foldable]
            self.store.execute(
                f"DELETE FROM executions WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)
            )
            notes.append(summary)
        self.store.commit()
        return notes

    def digests(self) -> list[str]:
        return [r["summary"] for r in self.store.query("SELECT summary FROM memory_digests ORDER BY id DESC")]
