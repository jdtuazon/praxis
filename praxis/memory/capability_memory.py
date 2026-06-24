"""Capability memory — Layer 2: what the agent knows how to do, and the rules.

Three kinds of structured knowledge, all *read before acting*:

  • capabilities  — executable knowledge (GraphQL ops / composites), with a
    lifecycle (probationary→trusted) and schema-hash provenance.
  • capability_stats — success rate / cost per (capability, signature), the
    promotion signal and an honest health metric.
  • constraints  — the learned world-model: cached ids (skip probes), enum
    facts (pre-validate), permission facts (switch tool), and workflow rules
    (rewrite the plan). Each tagged schema-derived vs runtime-learned so only
    genuine learning is ever claimed as such.
"""

from __future__ import annotations

from ..models import (
    CapabilitySource,
    CapabilitySpec,
    CapabilityStatus,
    Constraint,
    ConstraintKind,
    ConstraintOrigin,
    VerificationPolicy,
)
from .store import MemoryStore


class CapabilityMemory:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ── capabilities ───────────────────────────────────────────────────────
    def save_capability(self, spec: CapabilitySpec) -> None:
        now = self.store.now()
        self.store.execute(
            """INSERT INTO capabilities(name, spec_json, source, status, schema_hash, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 spec_json=excluded.spec_json, source=excluded.source, status=excluded.status,
                 schema_hash=excluded.schema_hash, updated_at=excluded.updated_at""",
            (
                spec.name,
                self.store.dumps(spec.model_dump(mode="json")),
                spec.source.value,
                spec.status.value,
                spec.schema_hash,
                spec.created_at,
                now,
            ),
        )
        self.store.commit()

    def get_capability(self, name: str) -> CapabilitySpec | None:
        row = self.store.one("SELECT spec_json FROM capabilities WHERE name = ?", (name,))
        return CapabilitySpec.model_validate(self.store.loads(row["spec_json"])) if row else None

    def list_capabilities(self, *, source: CapabilitySource | None = None) -> list[CapabilitySpec]:
        if source:
            rows = self.store.query(
                "SELECT spec_json FROM capabilities WHERE source = ? ORDER BY name", (source.value,)
            )
        else:
            rows = self.store.query("SELECT spec_json FROM capabilities ORDER BY name")
        return [CapabilitySpec.model_validate(self.store.loads(r["spec_json"])) for r in rows]

    def set_status(self, name: str, status: CapabilityStatus) -> None:
        spec = self.get_capability(name)
        if not spec:
            return
        spec.status = status
        self.save_capability(spec)

    # ── capability stats (promotion + telemetry) ───────────────────────────
    def record_capability_use(
        self, capability: str, signature: str, *, success: bool, duration: float, api_calls: int
    ) -> None:
        row = self.store.one(
            "SELECT * FROM capability_stats WHERE capability = ? AND signature = ?",
            (capability, signature),
        )
        if row:
            self.store.execute(
                """UPDATE capability_stats SET attempts=attempts+1, successes=successes+?,
                   failures=failures+?, total_duration=total_duration+?, total_api_calls=total_api_calls+?,
                   last_used=? WHERE capability=? AND signature=?""",
                (
                    1 if success else 0,
                    0 if success else 1,
                    duration,
                    api_calls,
                    self.store.now(),
                    capability,
                    signature,
                ),
            )
        else:
            self.store.execute(
                """INSERT INTO capability_stats(capability, signature, attempts, successes, failures,
                   total_duration, total_api_calls, last_used) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    capability,
                    signature,
                    1,
                    1 if success else 0,
                    0 if success else 1,
                    duration,
                    api_calls,
                    self.store.now(),
                ),
            )
        self.store.commit()

    def success_count(self, capability: str) -> int:
        row = self.store.one(
            "SELECT COALESCE(SUM(successes),0) AS s FROM capability_stats WHERE capability = ?",
            (capability,),
        )
        return int(row["s"]) if row else 0

    def capability_health(self, capability: str) -> dict:
        row = self.store.one(
            """SELECT COALESCE(SUM(attempts),0) a, COALESCE(SUM(successes),0) s,
                      COALESCE(SUM(failures),0) f, COALESCE(SUM(total_api_calls),0) c
               FROM capability_stats WHERE capability = ?""",
            (capability,),
        )
        if row is None:  # no stats yet (or a transient empty read) — report zeroed health
            return {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "success_rate": None,
                "total_api_calls": 0,
            }
        a, s, f, c = row["a"], row["s"], row["f"], row["c"]
        return {
            "attempts": a,
            "successes": s,
            "failures": f,
            "success_rate": (s / a) if a else None,
            "total_api_calls": c,
        }

    # ── constraints (the learned world-model) ──────────────────────────────
    def upsert_constraint(self, c: Constraint) -> int:
        existing = self.store.one(
            "SELECT id, hits FROM constraints WHERE kind=? AND scope=? AND key=?",
            (c.kind.value, c.scope, c.key),
        )
        if existing:
            self.store.execute(
                """UPDATE constraints SET value_json=?, description=?, origin=?, rewrites_plan=?,
                   verification_policy=?, ttl_seconds=?, observed_at=?, invalidated_by=NULL,
                   confidence=?, discovered_from_execution=COALESCE(?, discovered_from_execution)
                   WHERE id=?""",
                (
                    self.store.dumps(c.value),
                    c.description,
                    c.origin.value,
                    int(c.rewrites_plan),
                    c.verification_policy.value,
                    c.ttl_seconds,
                    self.store.now(),
                    c.confidence,
                    c.discovered_from_execution,
                    existing["id"],
                ),
            )
            self.store.commit()
            return int(existing["id"])
        cur = self.store.execute(
            """INSERT INTO constraints(kind, origin, scope, key, value_json, description, rewrites_plan,
               verification_policy, ttl_seconds, discovered_from_execution, observed_at, confidence, hits)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (
                c.kind.value,
                c.origin.value,
                c.scope,
                c.key,
                self.store.dumps(c.value),
                c.description,
                int(c.rewrites_plan),
                c.verification_policy.value,
                c.ttl_seconds,
                c.discovered_from_execution,
                c.observed_at,
                c.confidence,
            ),
        )
        self.store.commit()
        return int(cur.lastrowid)

    def _row_to_constraint(self, row) -> Constraint:
        return Constraint(
            kind=ConstraintKind(row["kind"]),
            origin=ConstraintOrigin(row["origin"]),
            scope=row["scope"],
            key=row["key"],
            value=self.store.loads(row["value_json"]),
            description=row["description"],
            rewrites_plan=bool(row["rewrites_plan"]),
            verification_policy=VerificationPolicy(row["verification_policy"]),
            ttl_seconds=row["ttl_seconds"],
            discovered_from_execution=row["discovered_from_execution"],
            observed_at=row["observed_at"],
            invalidated_by=row["invalidated_by"],
            confidence=row["confidence"],
            hits=row["hits"],
        )

    def get_constraints(
        self,
        *,
        scope: str | None = None,
        key: str | None = None,
        kind: ConstraintKind | None = None,
        include_invalidated: bool = False,
    ) -> list[Constraint]:
        sql = "SELECT * FROM constraints WHERE 1=1"
        params: list = []
        if not include_invalidated:
            sql += " AND invalidated_by IS NULL"
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY observed_at DESC"
        return [self._row_to_constraint(r) for r in self.store.query(sql, tuple(params))]

    def constraint_row(self, *, kind: ConstraintKind, scope: str, key: str):
        return self.store.one(
            "SELECT * FROM constraints WHERE kind=? AND scope=? AND key=? AND invalidated_by IS NULL",
            (kind.value, scope, key),
        )

    def bump_hit(self, *, kind: ConstraintKind, scope: str, key: str) -> None:
        self.store.execute(
            "UPDATE constraints SET hits=hits+1 WHERE kind=? AND scope=? AND key=? AND invalidated_by IS NULL",
            (kind.value, scope, key),
        )
        self.store.commit()

    def invalidate_constraint(self, constraint_id: int, *, by_execution: int | None) -> None:
        self.store.execute(
            "UPDATE constraints SET invalidated_by=? WHERE id=?", (by_execution, constraint_id)
        )
        self.store.commit()

    # ── typed accessors used by the planner/executor ───────────────────────
    def cached_entity_id(self, scope: str, key: str) -> str | None:
        row = self.constraint_row(kind=ConstraintKind.ENTITY_ID, scope=scope, key=key)
        return self.store.loads(row["value_json"]) if row else None

    def enum_constraint(self, field: str) -> Constraint | None:
        rows = self.get_constraints(scope="field", key=field, kind=ConstraintKind.ENUM)
        return rows[0] if rows else None

    def permission_forbidden(self, operation: str) -> bool:
        row = self.constraint_row(kind=ConstraintKind.PERMISSION, scope="mutation", key=operation)
        if not row:
            return False
        val = self.store.loads(row["value_json"])
        return val == "forbidden" or val is True

    def workflow_rules(self, team_id: str) -> list[Constraint]:
        return self.get_constraints(scope="team", key=team_id, kind=ConstraintKind.WORKFLOW_RULE)
