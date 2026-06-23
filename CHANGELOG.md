# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-23

The first end-to-end version: an autonomous, self-improving agent for Linear,
plus a CLI, a JSON API + dashboard, and a Next.js console.

### Added

- **Agent core** — natural-language instruction → decomposed plan → execution on
  Linear's GraphQL API, with a structured execution report after every run and
  partial-failure handling (no silent half-completions).
- **Persistent memory** — two structured SQLite layers: execution memory (plans,
  outcomes, cost, reusable plan shapes keyed on an intent-signature) and
  capability memory (capabilities with a lifecycle, per-pattern stats, and
  learned constraints).
- **Capability synthesis** — runtime reason → typed contract → schema validation
  → tiered non-destructive test → register (probationary → trusted), with a
  constrained composition DSL (no raw `exec`).
- **Self-learning** — a learned workflow rule rewrites the plan to pre-empt a
  failure it once hit; `praxis bench` reports the before/after numbers with a
  negative control that reverts the gain when the constraint is wiped.
- **Nice-to-haves** — LangGraph multi-component orchestration, memory compaction,
  confidence scoring, and best-effort rollback with a reversibility taxonomy.
- **Interfaces** — a `praxis` CLI (`run`, `demo`, `bench`, `memory`,
  `capabilities`, `serve`), a FastAPI JSON API + dashboard, and a Next.js console
  (`web/`).
- **Testing** — 100+ offline, deterministic tests (unit, integration, and a
  generative regression sweep) driven by a real `graphql-core` FakeLinear
  simulation and a scripted LLM.
- **Deployment** — Dockerfiles for the API and the console, a `docker-compose`
  stack, and Vercel configuration.

[0.1.0]: https://github.com/jdtuazon/watermelon
