import { NextRequest } from "next/server";

// Runtime proxy to the Praxis FastAPI backend. The destination is read from
// PRAXIS_API_URL on every request, so it's configurable at deploy time (Vercel
// env, docker-compose service name) without rebuilding. Keeps the browser on
// the same origin — no CORS, no exposed backend URL.
export const dynamic = "force-dynamic";

const API = () => process.env.PRAXIS_API_URL || "http://127.0.0.1:8000";

async function proxy(req: NextRequest, path: string[]) {
  const url = `${API()}/api/${path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "content-type": "application/json" },
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  try {
    const res = await fetch(url, init);
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") || "application/json" },
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: "Praxis backend is unreachable. Is the API running (praxis serve)?" }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
}

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params.path);
}
export async function POST(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params.path);
}
