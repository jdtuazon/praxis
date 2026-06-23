"""Praxis command-line interface.

    praxis run "instruction"      run one instruction (live by default; --offline for no-key dry run)
    praxis demo                   run the scripted 3-instruction demo (offline)
    praxis bench                  reproduce the learning before/after numbers
    praxis memory show|reset      inspect / manage persistent memory
    praxis capabilities           list known capabilities
    praxis serve                  launch the web dashboard
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from .build import build_agent
from .config import Settings
from .memory import Memory
from .report import render_memory, render_report

app = typer.Typer(add_completion=False, help="Praxis — an autonomous, self-improving agent for Linear.")
memory_app = typer.Typer(help="Inspect and manage persistent memory.")
app.add_typer(memory_app, name="memory")
console = Console()


def _memory(settings: Settings) -> Memory:
    return Memory(settings.memory_file())


@app.command()
def run(
    instruction: str = typer.Argument(..., help="Natural-language instruction."),
    offline: bool = typer.Option(False, "--offline", help="Use the deterministic offline brain + FakeLinear (no API keys)."),
    json_out: bool = typer.Option(False, "--json", help="Emit the structured report as JSON."),
    no_memory: bool = typer.Option(False, "--no-memory", help="Negative control: ignore prior memory (start cold)."),
    memory_path: Optional[str] = typer.Option(None, "--memory", help="Override the memory DB path."),
):
    """Run a single instruction end to end and print the structured report."""
    settings = Settings()
    if memory_path:
        settings.memory_path = memory_path
    mem = _memory(settings)
    if no_memory:
        mem = Memory(":memory:")  # ephemeral, cold
    agent = build_agent(settings, offline=offline, memory=mem)
    report = agent.run(instruction)
    if json_out:
        console.print_json(report.model_dump_json())
    else:
        render_report(report)


@app.command()
def demo(
    offline: bool = typer.Option(True, "--offline/--live",
                                 help="Offline (FakeLinear, default) or live (real Linear + LLM, needs .env keys)."),
):
    """Run the canonical 3-instruction demo showing synthesis, decision-change, and rollback."""
    from .demo import run_demo

    run_demo(console, offline=offline)


@app.command()
def bench(
    offline: bool = typer.Option(True, "--offline/--live", help="Offline (default) or live."),
    json_out: bool = typer.Option(False, "--json"),
):
    """Reproduce the learning before/after numbers (cold vs warm vs negative control)."""
    from .demo import run_benchmark

    run_benchmark(console, offline=offline, json_out=json_out)


@app.command()
def capabilities(
    offline: bool = typer.Option(True, "--offline/--live"),
):
    """List the capabilities the agent currently knows (builtins + synthesized)."""
    settings = Settings()
    mem = _memory(settings)
    agent = build_agent(settings, offline=offline, memory=mem)
    t = Table(title="Capabilities", box=box.SIMPLE_HEAD, expand=True)
    for col in ("name", "kind", "source", "status", "description"):
        t.add_column(col)
    for spec in sorted(agent.registry.specs(), key=lambda s: (s.source.value, s.name)):
        t.add_row(spec.name, spec.kind.value, spec.source.value, spec.status.value, spec.description[:60])
    console.print(t)


@memory_app.command("show")
def memory_show(memory_path: Optional[str] = typer.Option(None, "--memory")):
    """Show the current persistent memory state."""
    settings = Settings()
    if memory_path:
        settings.memory_path = memory_path
    render_memory(_memory(settings))


@memory_app.command("reset")
def memory_reset(
    yes: bool = typer.Option(False, "--yes", help="Confirm wiping ALL memory."),
    memory_path: Optional[str] = typer.Option(None, "--memory"),
):
    """Erase all persistent memory (instructions, executions, capabilities, constraints)."""
    settings = Settings()
    if memory_path:
        settings.memory_path = memory_path
    if not yes:
        console.print("[yellow]This erases all learned memory. Re-run with --yes to confirm.[/]")
        raise typer.Exit(1)
    m = _memory(settings)
    m.reset()
    console.print("[green]Memory reset.[/]")


@memory_app.command("wipe-constraints")
def memory_wipe_constraints(memory_path: Optional[str] = typer.Option(None, "--memory")):
    """Negative control: drop learned constraints but keep capabilities/plans."""
    settings = Settings()
    if memory_path:
        settings.memory_path = memory_path
    _memory(settings).wipe_constraints()
    console.print("[green]Constraints wiped (capabilities and plan cache kept).[/]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    offline: bool = typer.Option(True, "--offline/--live", help="Back the dashboard with FakeLinear (default) or real Linear."),
):
    """Launch the web dashboard (instruct the agent, watch steps, inspect memory & learning)."""
    import uvicorn

    from .server.app import create_app

    application = create_app(offline=offline)
    console.print(f"[bold green]Praxis dashboard[/] → http://{host}:{port}  ({'offline' if offline else 'live'})")
    uvicorn.run(application, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
