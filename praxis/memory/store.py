"""SQLite-backed persistent store underpinning both memory layers.

SQLite is chosen deliberately over a vector database: the assignment's "real
version" of memory is *structured knowledge that changes decisions*, which is
relational by nature (constraints keyed by scope, capability stats keyed by
signature, plans keyed by intent-signature). A single embedded file also means
the memory genuinely "survives across sessions" with zero external services and
is trivially inspectable (`praxis memory show`, `sqlite3 .praxis/memory.sqlite`).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
-- ── Execution memory ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instructions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    signature   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instructions_sig ON instructions(signature);

CREATE TABLE IF NOT EXISTS executions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instruction   TEXT NOT NULL,
    signature     TEXT NOT NULL,
    status        TEXT NOT NULL,
    plan_json     TEXT NOT NULL,
    plan_source   TEXT NOT NULL,
    api_calls     INTEGER NOT NULL DEFAULT 0,
    llm_calls     INTEGER NOT NULL DEFAULT 0,
    wasted_calls  INTEGER NOT NULL DEFAULT 0,
    duration_s    REAL NOT NULL DEFAULT 0,
    tokens        INTEGER NOT NULL DEFAULT 0,
    confidence    REAL NOT NULL DEFAULT 0,
    synthesized   INTEGER NOT NULL DEFAULT 0,
    started_at    REAL NOT NULL,
    finished_at   REAL NOT NULL,
    summary       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_executions_sig ON executions(signature);

-- Best successful plan SHAPE per signature (bindings re-resolved at run time).
CREATE TABLE IF NOT EXISTS plan_cache (
    signature      TEXT PRIMARY KEY,
    plan_json      TEXT NOT NULL,
    execution_id   INTEGER NOT NULL,
    success_count  INTEGER NOT NULL DEFAULT 1,
    avg_api_calls  REAL NOT NULL DEFAULT 0,
    updated_at     REAL NOT NULL
);

-- ── Capability memory ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS capabilities (
    name          TEXT PRIMARY KEY,
    spec_json     TEXT NOT NULL,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL,
    schema_hash   TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_stats (
    capability    TEXT NOT NULL,
    signature     TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    successes     INTEGER NOT NULL DEFAULT 0,
    failures      INTEGER NOT NULL DEFAULT 0,
    total_duration REAL NOT NULL DEFAULT 0,
    total_api_calls INTEGER NOT NULL DEFAULT 0,
    last_used     REAL,
    PRIMARY KEY (capability, signature)
);

CREATE TABLE IF NOT EXISTS constraints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    origin        TEXT NOT NULL,
    scope         TEXT NOT NULL,
    key           TEXT NOT NULL,
    value_json    TEXT,
    description   TEXT NOT NULL DEFAULT '',
    rewrites_plan INTEGER NOT NULL DEFAULT 0,
    verification_policy TEXT NOT NULL DEFAULT 'trust',
    ttl_seconds   REAL,
    discovered_from_execution INTEGER,
    observed_at   REAL NOT NULL,
    invalidated_by INTEGER,
    confidence    REAL NOT NULL DEFAULT 1.0,
    hits          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, scope, key)
);
CREATE INDEX IF NOT EXISTS idx_constraints_scope ON constraints(scope, key);

-- Free-form summarized memory produced by compaction.
CREATE TABLE IF NOT EXISTS memory_digests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signature   TEXT,
    summary     TEXT NOT NULL,
    covers_from REAL,
    covers_to   REAL,
    created_at  REAL NOT NULL
);
"""


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ── helpers ────────────────────────────────────────────────────────────
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def dumps(obj: Any) -> str:
        return json.dumps(obj, default=str, ensure_ascii=False)

    @staticmethod
    def loads(s: str | None) -> Any:
        return json.loads(s) if s else None

    def now(self) -> float:
        return time.time()

    def counts(self) -> dict[str, int]:
        def c(table: str, where: str = "") -> int:
            row = self.one(f"SELECT COUNT(*) AS n FROM {table} {where}")
            return int(row["n"]) if row else 0

        return {
            "instructions": c("instructions"),
            "executions": c("executions"),
            "capabilities": c("capabilities"),
            "constraints": c("constraints", "WHERE invalidated_by IS NULL"),
        }
