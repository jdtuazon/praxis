"""FastAPI dashboard for Praxis.

Justified (per design review) only because it visualises the depth story: the
memory delta and the divergent execution trace before/after learning. It is a
thin shell over the same `PraxisAgent` + structured report used everywhere else
— instruct the agent, watch the steps, inspect memory, and run the learning
benchmark, all in the browser.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..build import build_agent
from ..config import Settings
from ..memory import Memory
from ..platform.fake import FakeLinear

_STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    instruction: str


def create_app(*, offline: bool = True) -> FastAPI:
    app = FastAPI(title="Praxis", docs_url="/api/docs")
    settings = Settings()
    state: dict = {
        "memory": Memory(":memory:" if offline else settings.memory_file()),
        "fake": FakeLinear() if offline else None,
        "offline": offline,
    }

    def agent():
        return build_agent(settings, offline=state["offline"], memory=state["memory"], fake=state["fake"])

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (_STATIC / "index.html").read_text()

    @app.post("/api/run")
    def run(req: RunRequest) -> JSONResponse:
        report = agent().run(req.instruction)
        return JSONResponse(report.model_dump(mode="json"))

    @app.get("/api/memory")
    def memory() -> JSONResponse:
        m: Memory = state["memory"]
        caps = []
        for spec in m.capability.list_capabilities():
            h = m.capability.capability_health(spec.name)
            caps.append({"name": spec.name, "kind": spec.kind.value, "source": spec.source.value,
                         "status": spec.status.value, "attempts": h["attempts"],
                         "success_rate": h["success_rate"], "description": spec.description})
        cons = [{"kind": c.kind.value, "origin": c.origin.value, "scope": c.scope, "key": c.key,
                 "value": c.value, "rewrites_plan": c.rewrites_plan, "hits": c.hits,
                 "description": c.description} for c in m.capability.get_constraints()]
        return JSONResponse({"counts": m.store.counts(), "capabilities": caps, "constraints": cons})

    @app.post("/api/reset")
    def reset() -> JSONResponse:
        state["memory"].reset()
        if state["offline"]:
            state["fake"] = FakeLinear()
        return JSONResponse({"ok": True})

    @app.post("/api/wipe-constraints")
    def wipe() -> JSONResponse:
        state["memory"].wipe_constraints()
        return JSONResponse({"ok": True})

    @app.get("/api/bench")
    def bench() -> JSONResponse:
        from rich.console import Console

        from ..demo import run_benchmark

        data = run_benchmark(Console(quiet=True), offline=True, json_out=False)
        return JSONResponse(data)

    return app
