"""Canonical demo + learning benchmark.

`run_demo` walks the three graded instructions (synthesis, decision-changing
memory, partial-failure+rollback). `run_benchmark` reproduces the before/after
numbers with a negative control — the auditable evidence the assignment asks for
("X took N calls on run 1 and M on run 5 because the agent learned Y").
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .build import build_agent
from .config import Settings
from .memory import Memory
from .platform.fake import FakeLinear
from .report import render_report

DEMO_STEPS = [
    ("1 · Capability synthesis — a novel composite instruction",
     "Roll up all issues into a triage digest grouped by priority"),
    ("1b · Transfer — a related instruction reuses the synthesized capability",
     "Create a digest of issues grouped by assignee"),
    ("2 · Decision-changing memory — first encounter (the rule is unknown)",
     "Move my in-progress issue to Done"),
    ("2b · Decision-changing memory — the agent now rewrites its own plan",
     "Mark my in-progress work as completed"),
    ("3 · Partial failure + best-effort compensation (no silent half-completion)",
     "Triage ENG-3: move it to In Progress, comment 'Picked up for this sprint', and assign it to Dave"),
]


def _agent(offline: bool, mem: Memory, fake: FakeLinear | None = None):
    settings = Settings()
    return build_agent(settings, offline=offline, memory=mem, fake=fake)


def run_demo(console: Console, *, offline: bool = True) -> None:
    mem = Memory(":memory:")
    fake = FakeLinear() if offline else None
    agent = _agent(offline, mem, fake)
    console.print(Panel("[bold]Praxis demo[/] — 3 instructions of increasing complexity, on one persistent memory.\n"
                        f"Mode: [cyan]{'offline (FakeLinear + deterministic brain)' if offline else 'LIVE (real Linear + LLM)'}[/]",
                        box=box.DOUBLE, border_style="bold"))
    for label, instruction in DEMO_STEPS:
        console.rule(f"[bold]{label}")
        report = agent.run(instruction)
        render_report(report, console)
        console.print()
    console.rule("[bold]Final memory state")
    from .report import render_memory
    render_memory(mem, console)


def run_benchmark(console: Console, *, offline: bool = True, json_out: bool = False) -> dict:
    """Cold vs warm vs negative-control numbers for the two learning mechanisms."""
    results: dict = {}

    # ── Mechanism A: workflow-rule → plan rewrite → wasted-call avoidance ──────
    mem = Memory(":memory:")
    a_cold = _agent(offline, mem, FakeLinear()).run("Move my in-progress issue to Done")
    a_warm = _agent(offline, mem, FakeLinear()).run("Mark my in-progress work as completed")
    mem.wipe_constraints()
    a_ctrl = _agent(offline, mem, FakeLinear()).run("Mark my in-progress work as completed")
    results["workflow_rule"] = {
        "cold": _row(a_cold), "warm": _row(a_warm), "control_after_wipe": _row(a_ctrl),
    }

    # ── Mechanism B: synthesis → transfer (capability reuse) ──────────────────
    mem2 = Memory(":memory:")
    fake2 = FakeLinear()
    b_cold = _agent(offline, mem2, fake2).run("Roll up all issues into a triage digest grouped by priority")
    b_xfer = _agent(offline, mem2, fake2).run("Create a digest of issues grouped by assignee")
    results["synthesis_transfer"] = {"cold": _row(b_cold), "transfer": _row(b_xfer)}

    if json_out:
        console.print_json(data=results)
        return results

    _print_bench_table(console, "Mechanism A — learned workflow rule rewrites the plan (failure avoidance)",
                        [("run 1 · cold (rule unknown)", a_cold),
                         ("run 2 · warm (rule learned → plan rewritten)", a_warm),
                         ("run 3 · negative control (constraints wiped)", a_ctrl)],
                        highlight="wasted")
    console.print("[dim]→ the wasted call vanishes once the rule is learned, and returns when the constraint is wiped: "
                  "the behaviour change is caused by memory, not luck.[/]\n")
    _print_bench_table(console, "Mechanism B — runtime synthesis, then transfer to a related instruction",
                        [("run 1 · cold (capability synthesized)", b_cold),
                         ("run 2 · transfer (capability reused, 0 synthesis)", b_xfer)],
                        highlight="api")
    console.print("[dim]→ the second, never-seen instruction pays no synthesis cost because the capability "
                  "built for a related one is reused.[/]")
    return results


def _row(report) -> dict:
    return {"status": report.status.value, "api_calls": report.total_api_calls,
            "llm_calls": report.total_llm_calls, "wasted_calls": report.wasted_calls,
            "synthesized": len(report.synthesized_capabilities),
            "saved": [a for a in report.learning.attributions]}


def _print_bench_table(console: Console, title: str, rows: list, *, highlight: str) -> None:
    t = Table(title=title, box=box.ROUNDED, title_justify="left", expand=True)
    t.add_column("scenario")
    t.add_column("status")
    t.add_column("API calls", justify="right")
    t.add_column("wasted", justify="right")
    t.add_column("LLM calls", justify="right")
    t.add_column("synth", justify="right")
    for label, r in rows:
        wasted = str(r.wasted_calls)
        api = str(r.total_api_calls)
        if highlight == "wasted" and r.wasted_calls == 0:
            wasted = f"[green]{wasted}[/]"
        if highlight == "wasted" and r.wasted_calls > 0:
            wasted = f"[red]{wasted}[/]"
        t.add_row(label, r.status.value, api, wasted, str(r.total_llm_calls),
                  str(len(r.synthesized_capabilities)))
    console.print(t)
