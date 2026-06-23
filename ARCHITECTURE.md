# Praxis — Architecture (one page)

Platform: **Linear** (GraphQL). Orchestration: a **LangGraph** state machine —
`plan → execute → validate → compensate? → learn` — over specialist components
(Planner, Synthesizer, Executor, Validator, Learner). The transport seam means
the production path and the offline test path run identical code.

### 1 · What does memory store, and why structured that way?

Two distinct, structured layers in one SQLite file (survives sessions, zero
external services, inspectable):

- **Execution memory** — instructions, executions (decomposition, outcome,
  timing, API/LLM cost), and a `plan_cache` of the best successful **plan shape**
  per *intent-signature*. The signature canonicalises an instruction to
  `{verb · entity · predicates · fields}` with concrete parameters *extracted
  out*, so knowledge transfers across phrasings ("high-priority bug in
  Engineering" ≡ "urgent ticket in Design").
- **Capability memory** — capabilities (lifecycle + schema-hash provenance),
  per-`(capability, signature)` **stats**, and **constraints**: cached entity ids
  (skip resolver probes), enum facts (pre-validate args), permission boundaries
  (switch tooling), and **workflow rules that rewrite the plan**.

Why not a vector store? Because the thing that must change a *decision* is
relational, not a nearest-neighbour blob: a constraint keyed by
`team/team_eng → estimate-before-Done`, read *before acting*. Embeddings are used
only as a tie-breaker. Every constraint is tagged **schema-derived vs
runtime-learned**, so only genuinely learned facts are ever counted as learning.
The plan-cache stores the *base* shape only — constraint-driven rewrites are
re-derived live, so the constraint remains the sole cause of the behaviour change.

### 2 · How does capability synthesis work?

When the planner hits a sub-goal no capability covers, the Synthesizer:
**reason → contract → validate → test → register.**

1. **Reason** over the *introspected* schema + existing capabilities → emit a
   typed `CapabilityPlan`: either a `GRAPHQL` op (built from a contract — we
   assemble the document, the model never writes raw GraphQL) or a `COMPOSITE`
   (an ordered composition of already-trusted capabilities + whitelisted pure
   transforms: filter / group / sort / markdown_table / create_each).
2. **Validate** the contract *deterministically* against the live schema — bad
   root fields/args or unknown capabilities are rejected at **0 API cost** and
   become a typed error fed into the next attempt (max N).
3. **Test** through a cheapest-first gate: schema-check → a non-destructive
   **dry-run** (reads execute; writes are shape-validated, never performed).
   Destructive canary+inverse-op probes exist but are gated behind a flag.
4. **Register** the capability *probationary*, with a schema-hash; it is promoted
   to *trusted* only after it succeeds on real runs, and a stale schema-hash
   forces a re-test. The composite DSL is the safety boundary — **no `exec`, no
   imports, no network, no filesystem** — so runtime-synthesized behaviour can
   only compose trusted pieces. Raw-Python synthesis is deliberately deferred.

After N failures it reports exactly which gate failed on each attempt.

### 3 · What is the learning signal, and what differs on run N vs run 1?

The primary signal is a **measurable behaviour change** — a *different decision*,
not a faster path to the same one — with two honest, attributed metrics:
**wasted calls → 0** (calls that hit a rule memory could have pre-empted) and
**transfer** (a never-seen related instruction benefits). API calls are counted
at the transport seam, so a genuine skip provably shows 0 calls.

- **Run 1** of "move my in-progress issue to Done": the agent doesn't know the
  team requires an estimate. It attempts the transition, the API rejects it
  (**1 wasted call**), and it records a runtime-learned `WORKFLOW_RULE`
  constraint. Status: partial (no silent half-completion).
- **Run N** (even a differently-phrased instruction with the same intent): the
  planner reads that constraint and **rewrites the plan** — inserting an estimate
  step *before* the transition. **0 wasted calls**, full success, and cached
  entity ids skip the resolver probes. Each saved call is attributed in the
  report to the exact memory artifact responsible.
- **Negative control**: wipe only the constraints and the wasted call returns and
  the rewrite disappears — proving causality, not memoization. (`praxis bench`.)

Secondary signals: synthesized-capability **reuse** (a related instruction pays
no synthesis cost), capability **promotion** from stats, and exact-repeat
**plan reuse** (skips the planning LLM call).

---

### Status & what I'd build next

Implemented to depth: all four MUST-HAVEs + all four NICE-TO-HAVEs (multi-agent
graph, compaction, confidence scoring, rollback). `FakeLinear` is a faithful but
*partial* Linear schema used only for offline CI — the live demo runs on real
Linear; the synthesizer is schema-driven, so it operates on whichever schema it
introspects.

Honest scope notes: the decision-changing learning currently covers the
**workflow-rule family** — `requires <field> before <state-type>` — which is
field-agnostic and team-scoped, but it is one rule *type*; the constraint store
and plan-rewrite hook generalize to more. The **rate-limit** constraint is
learned and surfaced for operator awareness, but throttling itself is reactive
(tenacity backoff in the client), not yet proactive. The **destructive
canary+rollback** test tier is designed and config-gated but not wired — the
shipped synthesizer validates only with non-destructive tiers.

If I had more time: (a) **more learned rule types** driving plan rewrites
(required sub-issues, label policies, assignment rules); (b) **raw-Python
capability synthesis** behind an AST allowlist + subprocess sandbox
(CPU/mem/no-net), deliberately deferred in favour of the safe composition DSL;
(c) the **destructive canary tier** in a sandbox team with `[PRAXIS-PROBE]`
markers + read-back verify; (d) a **tool-selection** learning signal once two
capabilities genuinely compete for a step (a discovered batch mutation vs N
single calls); (e) **concurrent execution** of independent plan branches (the
DAG is modelled; execution is sequential today for deterministic rollback
ordering); (f) the **live LLM+Linear path** is exercised by an env-gated smoke
test — broader live coverage and a recorded-cassette mode are next.
