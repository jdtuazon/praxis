"""Smoke tests for the full surface: report rendering, CLI, dashboard, composition DSL."""

from conftest import make_agent

from praxis.capabilities.registry import (
    CapabilityRegistry,
    Capability,
    ExecutionContext,
    _TRANSFORMS,
)
from praxis.capabilities.primitives import register_builtins
from praxis.memory import Memory
from praxis.models import CapabilityKind, CapabilitySource, CapabilityStatus, CapabilitySpec, TransformStep
from praxis.platform.fake import FakeLinear
from praxis.platform.linear.client import LinearClient


def test_report_renders_without_error():
    from rich.console import Console
    from praxis.report import render_report

    report = make_agent().run("Create a high-priority bug titled 'X' in Engineering")
    render_report(report, Console(quiet=True, file=open("/dev/null", "w")))
    assert report.execution_id is not None
    assert report.model_dump_json()  # serialises cleanly


def test_dashboard_endpoints():
    from fastapi.testclient import TestClient
    from praxis.server.app import create_app

    c = TestClient(create_app(offline=True))
    assert c.get("/").status_code == 200
    r = c.post("/api/run", json={"instruction": "Roll up all issues into a triage digest grouped by priority"})
    assert r.status_code == 200 and r.json()["synthesized_capabilities"] == ["issue_digest"]
    assert c.get("/api/memory").json()["counts"]["capabilities"] >= 1


def test_composition_dsl_dry_run_does_not_mutate():
    reg = CapabilityRegistry()
    register_builtins(reg)
    fake = FakeLinear()
    spec = CapabilitySpec(name="d", kind=CapabilityKind.COMPOSITE, source=CapabilitySource.SYNTHESIZED,
                          status=CapabilityStatus.PROBATIONARY, composition=[
        TransformStep(op="capability:query_issues", args={"filter": {}}, bind="i"),
        TransformStep(op="transform:group", args={"source": "{{i}}", "by": "priorityLabel"}, bind="g"),
        TransformStep(op="transform:markdown_table", args={"source": "{{g}}", "title": "T", "columns": ["identifier"]}, bind="t"),
        TransformStep(op="capability:create_document", args={"title": "T", "content": "{{t}}"}, bind="doc")])
    reg.register(Capability(spec=spec))
    ctx = ExecutionContext(client=LinearClient(fake), registry=reg, dry_run=True)
    reg.run("d", ctx)
    assert len(fake.store["documents"]) == 0, "dry-run must validate writes, not perform them"


def test_transform_whitelist_is_closed():
    assert set(_TRANSFORMS) == {"filter", "group", "sort", "count", "markdown_table", "create_each"}


def test_cli_run_offline(tmp_path):
    from typer.testing import CliRunner
    from praxis.cli import app

    db = str(tmp_path / "mem.sqlite")  # isolate from the working dir
    res = CliRunner().invoke(app, ["run", "--offline", "--memory", db,
                                   "Create a bug titled 'Boom' in Engineering"])
    assert res.exit_code == 0, res.stdout
    assert "SUCCESS" in res.stdout
