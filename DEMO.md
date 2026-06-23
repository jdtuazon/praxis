# Praxis — Demo script (the walkthrough)

Three instructions of increasing complexity, run on **one persistent memory** so
each builds on the last. Everything below is reproducible:

```bash
praxis demo --live      # against real Linear + a real LLM (.env keys required)
praxis demo --offline   # identical flow against FakeLinear, no keys (what CI runs)
praxis bench            # just the before/after numbers + the negative control
```

> Memory persists between runs — that's the point. Don't `praxis memory reset`
> mid-demo. Offline numbers below are exact and asserted in the test suite; live
> numbers track them closely (a real LLM may add an exploratory call or two).

---

## Instruction 1 — Capability synthesis (a genuinely novel, compound task)

> **"Roll up all issues into a triage digest grouped by priority."**

No shipped capability does this. Watch the agent **synthesize one at runtime**:

- it introspects the live schema, proposes a **composite** `CapabilityPlan`
  (query issues → group by priority → render a markdown table → create a
  document) — a multi-step transform that *cannot* be a single API call;
- the contract is **validated against the schema first** (a hallucinated field
  would be rejected at 0 API cost); then a **non-destructive dry-run** tests it;
- it registers `issue_digest` *probationary* and runs it — a real Linear document
  appears.

**Then, the transfer proof:**

> **"Create a digest of issues grouped by assignee."**

A *different, never-seen* instruction — and the agent does **zero synthesis**: it
reuses the `issue_digest` capability built for the related task, re-parameterised
to group by assignee.

| | API calls | LLM calls | synthesized |
|---|---|---|---|
| run 1 (cold) | 5 | 2 | **issue_digest** |
| run 2 (transfer) | **2** | **1** | — (reused) |

*Proves:* synthesis is **reason→build→test→register**, not a lookup table; and the
result is reusable knowledge, not a one-off.

---

## Instruction 2 — Decision-changing memory (the headline)

> **"Move my in-progress issue to Done."**  *(first encounter)*

This Linear team enforces a workspace rule **not visible in the schema**: an issue
can't be completed without an estimate. The agent doesn't know that yet:

- it resolves the issue + the Done state, attempts the transition, and the API
  **rejects it** → **1 wasted call**;
- it records a runtime-learned `WORKFLOW_RULE` constraint. Status: **partial** —
  reported honestly, nothing silently half-done.

> **"Mark my in-progress work as completed."**  *(later — note: different words, same intent)*

Now the agent **rewrites its own plan**: it inserts an *estimate* step *before*
the Done transition. A **different decision**, not a faster path:

| run | status | wasted calls | plan |
|---|---|---|---|
| 1 · cold | partial | **1** | move → ✗ rejected |
| 2 · warm | success | **0** | **set estimate → move → ✓** |
| 3 · control (`memory wipe-constraints`) | partial | **1** | reverts to cold |

*Proves:* the improvement is **caused by the learned constraint** — wipe it and the
old behaviour returns. Not memoization, not luck. Cached entity ids also skip the
resolver probes; every saved call is attributed in the report.

---

## Instruction 3 — Partial failure + best-effort compensation

> **"Triage ENG-3: move it to In Progress, comment 'Picked up for this sprint', and assign it to Dave."**

`Dave` doesn't exist — so a required step fails *after* side effects were applied.
The agent does **not** leave a half-mutated workspace:

- ✓ move to In Progress (reversible) · ✓ comment posted (irreversible) · ✗ resolve
  "Dave" (fails) · ⊘ assign (skipped — its prerequisite failed);
- **rollback** runs as best-effort **compensation in reverse**: the state change is
  reverted; the posted comment is surfaced under **"manual cleanup required"**
  (a sent notification cannot be unsent) — never silently swallowed.

The structured report partitions every effect: `{success, rolled_back,
manual-cleanup, failed, skipped}`.

*Proves:* partial-failure handling with an explicit **reversibility taxonomy**
(reversible / archive-only / irreversible) — the two hardest-graded axes turned
into a visible strength.

---

### What to watch in the report each run

`praxis run "<instruction>"` prints: the **plan** (and whether it was reused or
rewritten), per-step **API + wasted** counts with provenance, the **synthesis
trace** (attempts + which test tier passed), **rollback / manual-cleanup**, the
**learning signal** (this run vs the first run of this intent, with attributions),
and the **memory Δ** (before → after, with newly-learned constraints). The web
dashboard (`praxis serve`) shows the same, with the memory delta highlighted.
