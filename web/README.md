# Praxis Console — web frontend

A Next.js (App Router, TypeScript, Tailwind) console for the Praxis agent. It
renders the same structured execution report the CLI produces — the plan
timeline, the capability-synthesis trace, the learning signal with a before/after
comparison, and the live memory delta — plus a memory inspector, a learning
benchmark, and a capability catalog.

It is a thin client over the Praxis FastAPI backend: the browser only ever talks
to `/papi/*`, a runtime proxy (`app/papi/[...path]/route.ts`) that forwards to
the API at `PRAXIS_API_URL`. No CORS, no backend URL exposed to the browser.

## Develop

```bash
# 1) start the backend (from the repo root)
praxis serve --offline          # → http://127.0.0.1:8000

# 2) start the console
cd web
npm install
npm run dev                     # → http://localhost:3000
```

`PRAXIS_API_URL` defaults to `http://127.0.0.1:8000`; set it if your API is
elsewhere (see `.env.example`).

## Design

A precision observability console. Cool slate ink ground, a single iris accent
(a nod to Linear's own indigo identity), aqua reserved for learning/delta
visualizations, and semantic state colors kept separate. **Hanken Grotesk** for
display/body, **JetBrains Mono** for all data — both self-hosted via `next/font`.
Tokens live in `tailwind.config.ts` + `app/globals.css`.

## Deploy

- **Vercel** — import the repo, set the project **Root Directory** to `web`, and
  add an env var `PRAXIS_API_URL` pointing at your deployed backend. That's it.
- **Docker** — `docker build -t praxis-web .` then run with
  `-e PRAXIS_API_URL=…`. Or use the root `docker-compose.yml` to run the API and
  console together.

`PRAXIS_API_URL` is read at request time, so the same image works against any
backend without a rebuild.
