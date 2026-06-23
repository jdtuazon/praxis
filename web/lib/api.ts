import type {
  BenchResult,
  Example,
  ExecutionReport,
  MemoryState,
  Meta,
} from "./types";

// All calls go to the same-origin proxy (/papi/*), which Next rewrites to the
// Praxis FastAPI backend. No CORS, no exposed backend URL in the browser.
const BASE = "/papi";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* keep status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => json<{ ok: boolean }>("/health"),
  meta: () => json<Meta>("/meta"),
  examples: () => json<Example[]>("/examples"),
  run: (instruction: string) =>
    json<ExecutionReport>("/run", { method: "POST", body: JSON.stringify({ instruction }) }),
  memory: () => json<MemoryState>("/memory"),
  bench: () => json<BenchResult>("/bench"),
  reset: () => json<{ ok: boolean }>("/reset", { method: "POST", body: "{}" }),
  wipeConstraints: () =>
    json<{ ok: boolean }>("/wipe-constraints", { method: "POST", body: "{}" }),
};
