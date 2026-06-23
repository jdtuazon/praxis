# 🍉 Praxis — an autonomous, self-improving agent for Linear

> *praxis* — the process by which a skill is enacted and **refined through practice**.

Praxis takes a natural-language instruction, decomposes it, executes it against
the **real Linear API**, and **gets measurably better every run** — not by being
retrained, but by extracting structured knowledge from each execution and using
it to make *different decisions* next time.

It is built around the distinction the assignment actually tests — the *cheap*
version of each requirement vs the *real* one:

| | Cheap version | What Praxis does |
|---|---|---|
| **Memory** | a vector DB of past prompts | a SQLite world-model of **constraints, capabilities and plan-shapes** read *before acting* to change decisions |
| **Synthesis** | a lookup table of endpoints | reason → emit a **typed contract** → validate it against the live schema → **test** it → register it (probationary→trusted) |
| **Learning** | "we added more examples" | a **measurable behaviour change** — the agent rewrites its own plan to avoid a failure it once hit, proven with a negative control |

---

## Quickstart (single command after `.env`)

```bash
pip install -r requirements.txt          # or:  pip install -e .
cp .env.example .env                     # add ANTHROPIC_API_KEY (or OPENAI) + LINEAR_API_KEY
praxis run "Create an urgent bug 'Login times out after 30s' in Engineering"
```

No keys yet? Everything runs **offline** against a faithful in-process Linear
simulation + a deterministic planner, so you can see the whole loop immediately:

```bash
praxis demo --offline        # the 3 graded instructions, end to end
praxis bench                 # the learning before/after numbers (with a negative control)
praxis serve                 # a web dashboard at http://127.0.0.1:8000
```

> **Why an offline mode exists.** The live demo makes *real* Linear API calls
> (`praxis demo --live`). The offline path swaps in `FakeLinear` — a real
> `graphql-core` schema with genuine introspection, execution, enum/permission/
> workflow-rule **enforcement** and rate limits — so the full agent (including
> schema-driven synthesis) runs deterministically in CI with no keys. The
> production code path is byte-for-byte identical; only the transport differs.

---

## What you'll see (the two depth pillars)

### 1 · Capability synthesis is real

Ask for something no capability covers — *"roll up all issues into a triage
digest grouped by priority"* — and Praxis:

1. **introspects** the live GraphQL schema and proposes a typed `CapabilityPlan`
   (here a **composite**: query → group → render markdown → create document — a
   multi-step transform that *cannot* be one API call);
2. **validates** the contract deterministically against the schema — a
   hallucinated field/capability dies here at **0 API cost** and feeds a typed
   error into the next attempt;
3. **tests** it through a cheapest-first gate (schema-check → non-destructive
   dry-run; destructive canary+rollback is gated behind a flag);
4. **registers** it *probationary*, and promotes it to *trusted* after it proves
   itself on real runs.

A *related, never-seen* instruction (*"create a digest grouped by assignee"*)
then **reuses** that capability — zero re-synthesis. That's transfer a cache can't fake.

### 2 · Memory changes decisions, not just latency

The strongest signal is a **plan rewrite**. Some Linear teams reject completing
an issue without an estimate — a workspace rule *not in the schema*. On the
first "move to Done", Praxis hits the rule (one **wasted call**) and records a
`WORKFLOW_RULE` constraint. On the next such instruction it **rewrites its own
plan**, inserting an estimate step *before* the transition. Same goal, **different
plan, zero wasted calls.**

Reproduce it — note run 3, the **negative control**:

```text
$ praxis bench
Mechanism A — learned workflow rule rewrites the plan (failure avoidance)
  run 1 · cold (rule unknown)                    partial   5 API   1 wasted
  run 2 · warm (rule learned → plan rewritten)   success   5 API   0 wasted
  run 3 · negative control (constraints wiped)   partial   5 API   1 wasted   ← reverts!
```

Wipe *only* the learned constraint and the wasted call returns — proving the
improvement is **caused by memory**, not luck or a cached answer. (The base plan
shape is what's cached; the rewrite is re-derived live from the constraint.)

---

## How it works

```
  instruction
      │
      ▼
 ┌─────────┐   reuse plan shape / rewrite from learned rules
 │ Planner │◀──────────────── execution + capability memory
 └────┬────┘
      ▼
 ┌──────────┐  gap? → ┌─────────────┐ reason→contract→validate→test→register
 │ Executor │────────▶│ Synthesizer │
 └────┬─────┘         └─────────────┘
      │ cached ids skip probes · enum facts pre-validate · permission facts switch tools
      ▼
 ┌───────────┐  required step failed after side effects?
 │ Validator │────────────────────────────▶ best-effort compensation (reversibility taxonomy)
 └────┬──────┘
      ▼
 ┌─────────┐  extract constraints · cache entities · update stats · promote capabilities
 │ Learner │──────────────────────────────────────────────▶ structured ExecutionReport
 └─────────┘
```

Wired as a **LangGraph** state machine (`plan → execute → validate → compensate? →
learn`). Each node is a specialist component; the conditional edge into
compensation is a real branch, not a straight line.

**Memory — two distinct, structured layers (SQLite):**
- *Execution memory*: instructions, executions (plan, outcome, timing, cost),
  and a `plan_cache` of the best successful plan **shape** per intent-signature.
- *Capability memory*: capabilities (with lifecycle + schema-hash provenance),
  per-(capability, signature) **stats**, and **constraints** — cached entity ids,
  enum facts, permission boundaries, and plan-rewriting workflow rules — each
  tagged *schema-derived* vs *runtime-learned* so only genuine learning is claimed.

See **[ARCHITECTURE.md](ARCHITECTURE.md)** (one page) and **[DEMO.md](DEMO.md)**
(the three live instructions).

---

## CLI

```bash
praxis run "<instruction>"        # run one instruction; add --offline / --json / --no-memory
praxis demo [--live]              # the 3 graded instructions on one persistent memory
praxis bench [--json]             # reproduce the learning numbers + negative control
praxis memory show                # inspect capabilities + learned constraints
praxis memory wipe-constraints    # the negative control, by hand
praxis capabilities               # list builtins + synthesized capabilities
praxis serve                      # JSON API + built-in dashboard
```

## Web console (Next.js)

A polished Next.js console lives in [`web/`](web) — instruct the agent, watch the
plan timeline and synthesis trace, run the learning benchmark, and inspect memory,
all in the browser. It renders the same structured report as the CLI.

```bash
praxis serve --offline            # API on :8000 (terminal 1)
cd web && npm install && npm run dev   # console on :3000 (terminal 2)
```

The browser only talks to a same-origin proxy (`/papi/*`) that forwards to the API
at `PRAXIS_API_URL` — no CORS, no exposed backend. See [web/README.md](web/README.md).

## Deployment

- **Everything at once (Docker):** `docker compose up --build` → console on
  `:3000`, API on `:8000`, with persistent memory on a named volume.
- **Console on Vercel:** import the repo, set Root Directory to `web`, and add
  `PRAXIS_API_URL` pointing at your deployed backend.
- **Backend anywhere:** `docker build -t praxis . && docker run -p 8000:8000 praxis`
  (defaults to the offline simulation; set `ANTHROPIC_API_KEY` + `LINEAR_API_KEY`
  and run with `--live` for a real workspace).

## Dependencies — and why each earns its place

| Dependency | Why |
|---|---|
| **langgraph** / langchain-core | deterministic, inspectable multi-component state graph (the orchestration spine) |
| **anthropic** / openai | pluggable LLM provider for planning + synthesis reasoning |
| **httpx** | async-capable HTTP to Linear's GraphQL; transport seam powers offline tests |
| **graphql-core** | gives `FakeLinear` *real* introspection + execution so synthesis is genuinely exercised offline |
| **pydantic** / pydantic-settings | typed models for plans, capabilities, the report, and config |
| **rich** / typer | operator-grade CLI + structured-report rendering |
| **fastapi** / uvicorn | the dashboard that visualises the memory delta + divergent traces |
| **tenacity** | backoff that honours discovered rate limits |

No agent "framework" magic is hidden: planning, synthesis, memory and learning
are plain, tested Python you can read top-to-bottom.

## Tests

```bash
pytest            # 90+ tests, fully offline & deterministic (no keys, no network)
```

Includes the learning regression (asserts `run-N wasted < run-1` **and** the
negative control restores it **and** correctness post-conditions hold) plus a
generative sweep of 60 instruction variants and a 50-instruction mixed session.

## Project layout

```
praxis/
  models.py            typed domain models (plans, capabilities, constraints, report)
  llm/                 provider abstraction + deterministic ScriptedLLM
  platform/            transport seam · Linear client · FakeLinear (graphql-core)
  memory/              SQLite store · execution + capability layers · signature · compaction
  capabilities/        registry · builtin primitives · runtime synthesis (composition DSL)
  agents/              planner · executor · validator · learner · offline brain
  orchestrator/        LangGraph graph + PraxisAgent facade
  report.py cli.py demo.py server/   reporting, CLI, demo/bench, dashboard
tests/                 unit · integration · generative regression
```

## Limits & what's next

See the final section of **[ARCHITECTURE.md](ARCHITECTURE.md)** — honest notes on
`FakeLinear`'s scope, raw-Python synthesis (deliberately deferred behind the
composition DSL), and the next learning signals worth adding.
