"""Rich rendering of the structured execution report.

The report is the artefact the assignment asks for after *every* run — what was
done, what failed, why, and what the agent decided. This module renders it for
the terminal (and the video); the same `ExecutionReport` serialises to JSON for
the dashboard and machine consumers.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .memory import Memory
from .models import ExecutionReport, ExecutionStatus, StepStatus

_STATUS_STYLE = {
    ExecutionStatus.SUCCESS: "bold green",
    ExecutionStatus.PARTIAL: "bold yellow",
    ExecutionStatus.FAILED: "bold red",
    ExecutionStatus.ROLLED_BACK: "bold magenta",
}
_STEP_STYLE = {
    StepStatus.SUCCESS: "green", StepStatus.FAILED: "red", StepStatus.SKIPPED: "yellow",
    StepStatus.ROLLED_BACK: "magenta", StepStatus.PENDING: "dim", StepStatus.RUNNING: "cyan",
}
_STEP_GLYPH = {
    StepStatus.SUCCESS: "✓", StepStatus.FAILED: "✗", StepStatus.SKIPPED: "⊘",
    StepStatus.ROLLED_BACK: "↩", StepStatus.PENDING: "·", StepStatus.RUNNING: "▸",
}


def render_report(report: ExecutionReport, console: Console | None = None) -> None:
    c = console or Console()
    style = _STATUS_STYLE.get(report.status, "white")

    head = Text()
    head.append(f"{report.status.value.upper()}", style=style)
    head.append(f"   {report.summary}", style="dim")
    c.print(Panel(head, title=f"[bold]Instruction[/]  {report.instruction}",
                  subtitle=f"plan: {report.plan.source.value} · confidence {report.confidence:.2f} · {report.duration_s:.3f}s",
                  border_style=style, box=box.ROUNDED))

    # ── steps ────────────────────────────────────────────────────────────────
    t = Table(box=box.SIMPLE_HEAD, expand=True, title="Execution steps", title_justify="left")
    t.add_column("#", width=3)
    t.add_column("", width=2)
    t.add_column("Sub-goal")
    t.add_column("Capability", style="cyan")
    t.add_column("API", justify="right", width=4)
    t.add_column("Notes", style="dim")
    for s in report.steps:
        glyph = Text(_STEP_GLYPH.get(s.status, "·"), style=_STEP_STYLE.get(s.status, "white"))
        notes = []
        if s.inserted_by_constraint:
            notes.append("⟲ inserted by learned rule")
        if s.wasted_calls:
            notes.append(f"{s.wasted_calls} wasted")
        if s.error:
            notes.append(s.error[:60])
        for p in s.provenance:
            notes.append(f"{p.kind}")
        if s.result_summary and not s.error:
            notes.append(s.result_summary[:50])
        t.add_row(str(s.index), glyph, s.intent, s.capability or "—", str(s.api_calls), " · ".join(notes))
    c.print(t)

    # ── decisions ────────────────────────────────────────────────────────────
    if report.decisions:
        body = Text()
        for d in report.decisions:
            body.append(f"• [{d.stage}] ", style="bold cyan")
            body.append(d.summary + "\n")
            if d.rationale:
                body.append(f"    {d.rationale}\n", style="dim")
        c.print(Panel(body, title="Decisions & rationale", border_style="cyan", box=box.ROUNDED))

    # ── synthesis ────────────────────────────────────────────────────────────
    for syn in report.synthesis:
        body = Text()
        verdict = "registered" if syn.success else "FAILED"
        vstyle = "green" if syn.success else "red"
        body.append(f"gap: {syn.requested_for}\n", style="dim")
        body.append(f"result: {verdict}", style=vstyle)
        if syn.capability_name:
            body.append(f"  →  {syn.capability_name}", style="cyan")
        body.append(f"   ({syn.api_calls} API, {syn.llm_calls} LLM calls)\n")
        for a in syn.attempts:
            body.append(f"  attempt {a.attempt}: ", style="bold")
            for o in a.outcomes:
                ok = "✓" if o.passed else "✗"
                body.append(f"[{ok} {o.tier.value}] ", style="green" if o.passed else "red")
            if a.error:
                body.append(f"→ {a.error[:80]}", style="red")
            body.append("\n")
        c.print(Panel(body, title="Capability synthesis (reason → build → test → register)",
                      border_style="green" if syn.success else "red", box=box.ROUNDED))

    # ── rollback / cleanup ────────────────────────────────────────────────────
    if report.rollback_performed or report.manual_cleanup_required:
        body = Text()
        for r in report.rollback_steps:
            body.append(f"↩ compensated: {r}\n", style="magenta")
        for m in report.manual_cleanup_required:
            body.append(f"⚠ manual cleanup: {m}\n", style="yellow")
        c.print(Panel(body, title="Rollback (best-effort compensation)", border_style="magenta", box=box.ROUNDED))

    # ── learning ──────────────────────────────────────────────────────────────
    _render_learning(report, c)

    # ── memory delta ──────────────────────────────────────────────────────────
    mb, ma = report.memory_before.counts, report.memory_after.counts
    body = Text()
    body.append(f"executions {mb.executions}→{ma.executions}   "
                f"capabilities {mb.capabilities}→{ma.capabilities}   "
                f"constraints {mb.constraints}→{ma.constraints}\n", style="bold")
    for line in report.memory_diff.lines:
        body.append(f"  + {line}\n", style="green")
    if report.discovered_constraints:
        body.append("\nlearned this run:\n", style="bold")
        for dc in report.discovered_constraints:
            body.append(f"  • {dc}\n", style="green")
    c.print(Panel(body, title="Memory Δ (before → after)", border_style="blue", box=box.ROUNDED))


def _render_learning(report: ExecutionReport, c: Console) -> None:
    L = report.learning
    body = Text()
    body.append(f"intent-signature: {L.instruction_signature}\n", style="dim")
    body.append(f"run #{L.run_number} of this intent  ·  mode: ", style="bold")
    body.append(f"{L.mode}\n", style="bold cyan")
    body.append(f"this run:  {L.api_calls} API · {L.llm_calls} LLM · {L.wasted_calls} wasted · {L.failed_steps} failed\n")
    if L.baseline_api_calls is not None:
        body.append(f"first run: {L.baseline_api_calls} API · {L.baseline_llm_calls} LLM · "
                    f"{L.baseline_wasted_calls} wasted\n", style="dim")
        deltas = []
        if L.wasted_calls_saved:
            deltas.append(f"−{L.wasted_calls_saved} wasted")
        if L.api_calls_saved:
            deltas.append(f"−{L.api_calls_saved} API")
        if L.llm_calls_saved:
            deltas.append(f"−{L.llm_calls_saved} LLM")
        if L.speedup_pct:
            deltas.append(f"{L.speedup_pct:+.0f}% time")
        if deltas:
            body.append("improvement: " + "  ".join(deltas) + "\n", style="bold green")
    if L.attributions:
        body.append("\nattributed to memory:\n", style="bold")
        for a in L.attributions:
            body.append(f"  → {a}\n", style="green")
    border = "green" if (L.wasted_calls_saved or L.api_calls_saved or L.mode != "fresh") else "dim"
    c.print(Panel(body, title="Learning signal (this run vs first run of this intent)",
                  border_style=border, box=box.ROUNDED))


def render_memory(memory: Memory, console: Console | None = None) -> None:
    """Inspect the persistent memory state."""
    c = console or Console()
    counts = memory.store.counts()
    c.print(Panel(Text(f"instructions {counts['instructions']} · executions {counts['executions']} · "
                       f"capabilities {counts['capabilities']} · active constraints {counts['constraints']}",
                       style="bold"), title="Memory state", border_style="blue", box=box.ROUNDED))

    caps = memory.capability.list_capabilities()
    if caps:
        t = Table(title="Capability memory", box=box.SIMPLE_HEAD, title_justify="left", expand=True)
        for col in ("name", "kind", "source", "status", "uses", "success"):
            t.add_column(col)
        for spec in caps:
            h = memory.capability.capability_health(spec.name)
            rate = f"{h['success_rate']:.0%}" if h["success_rate"] is not None else "—"
            t.add_row(spec.name, spec.kind.value, spec.source.value, spec.status.value, str(h["attempts"]), rate)
        c.print(t)

    cons = memory.capability.get_constraints()
    if cons:
        t = Table(title="Learned constraints", box=box.SIMPLE_HEAD, title_justify="left", expand=True)
        for col in ("kind", "origin", "scope/key", "value", "rewrites plan", "hits"):
            t.add_column(col)
        for con in cons:
            val = str(con.value)
            t.add_row(con.kind.value, con.origin.value, f"{con.scope}/{con.key}",
                      val[:48], "yes" if con.rewrites_plan else "", str(con.hits))
        c.print(t)
