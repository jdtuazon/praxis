"""Capability synthesis: reason → build a typed contract → validate → test → register.

This is the "real" synthesis the assignment contrasts with a lookup table:

  1. REASON   — the model is shown the *introspected* schema + existing
     capabilities and proposes a typed `CapabilityPlan` (a GraphQL-from-contract
     op, or a COMPOSITE of trusted capabilities + pure transforms).
  2. VALIDATE — the contract is checked *deterministically* against the live
     schema before any API call. Hallucinated fields/args die at 0 API cost and
     produce a typed error that is fed back into the next attempt.
  3. TEST     — a tiered gate, cheapest-first: schema-check (0 calls) → a
     non-destructive dry-run probe (reads execute; writes are shape-validated,
     never performed). Destructive canary+rollback is available but gated.
  4. REGISTER — on success the capability is persisted PROBATIONARY (promoted to
     trusted only after it succeeds on real executions), with a schema-hash for
     staleness detection. After N failed attempts it reports exactly which gate
     failed on each attempt.
"""

from __future__ import annotations

from typing import Optional

from ..llm.base import LLM, LLMError
from ..models import (
    CapabilityKind,
    CapabilityPlan,
    CapabilitySource,
    CapabilitySpec,
    CapabilityStatus,
    SynthesisAttempt,
    SynthesisResult,
    TestOutcome,
    TestTier,
    TransformStep,
)
from ..platform.base import PlatformError
from .registry import WHITELISTED_TRANSFORMS, Capability, CapabilityRegistry, ExecutionContext

SYNTHESIZER_SYSTEM = """[[ROLE:SYNTHESIZER]] You are Praxis's capability synthesizer.
A capability gap was found: the agent needs an operation it does not yet have. Design ONE new capability.

Prefer a COMPOSITE capability (compose existing trusted capabilities + pure transforms) for anything
that gathers/filters/groups/aggregates data or operates over many items — these CANNOT be a single API call.
Use a GRAPHQL capability only for a single missing platform operation.

You MUST ground every field/argument in the provided schema and only reference capabilities that exist.
Return ONLY a JSON object matching this shape:
{
  "name": "snake_case_name",
  "kind": "composite" | "graphql",
  "description": "...",
  "input_schema": {"arg": "type"},
  "rationale": "why this design",
  // graphql kind:
  "operation_type": "query"|"mutation",
  "graphql_root_field": "issueArchive",
  "args": {"id": "ID!"},
  "selection": "success issue { id identifier }",
  "select_path": "issueArchive",
  "side_effecting": true,
  "inverse_root_field": "issueUnarchive",
  // composite kind:
  "composition": [
    {"op": "capability:query_issues", "args": {"filter": {}}, "bind": "issues"},
    {"op": "transform:filter", "args": {"source": "{{issues}}", "where": [{"field":"assignee","op":"is_null"}]}, "bind": "open"},
    {"op": "transform:group", "args": {"source": "{{open}}", "by": "priorityLabel"}, "bind": "groups"},
    {"op": "transform:markdown_table", "args": {"source": "{{groups}}", "title": "...", "columns": ["identifier","title"]}, "bind": "table"},
    {"op": "capability:create_document", "args": {"title": "...", "content": "{{table}}"}, "bind": "doc"}
  ],
  "probe_args": {}   // sample args to safely test the capability
}
Transforms available: filter, group, sort, count, markdown_table, create_each.
Template references use {{bind}} or {{item.field}} (inside create_each).
"""


class Synthesizer:
    def __init__(self, llm: LLM, client, registry: CapabilityRegistry, memory, settings) -> None:
        self.llm = llm
        self.client = client
        self.registry = registry
        self.memory = memory
        self.settings = settings

    # ── public entry ─────────────────────────────────────────────────────────
    def synthesize(self, *, gap_intent: str, instruction: str, keywords: list[str]) -> SynthesisResult:
        result = SynthesisResult(requested_for=gap_intent, success=False)
        api_before, llm_before = self.client.api_calls, self.llm.usage.calls
        max_attempts = int(getattr(self.settings, "synthesis_max_attempts", 3))
        feedback: Optional[str] = None

        for attempt_no in range(1, max_attempts + 1):
            attempt = SynthesisAttempt(attempt=attempt_no)
            # 1) REASON → contract
            try:
                plan = self._propose(gap_intent, instruction, keywords, feedback)
                attempt.plan = plan
            except (LLMError, ValueError) as e:
                attempt.error = f"contract generation failed: {e}"
                result.attempts.append(attempt)
                feedback = attempt.error
                continue

            # 2) VALIDATE (deterministic, 0 API calls)
            errors = self._validate(plan)
            attempt.outcomes.append(TestOutcome(tier=TestTier.SCHEMA_CHECK, passed=not errors,
                                                detail="; ".join(errors) or "contract matches schema"))
            if errors:
                attempt.error = "schema validation failed: " + "; ".join(errors)
                result.attempts.append(attempt)
                feedback = attempt.error
                continue

            # 3) TEST (tiered, cheapest-first, non-destructive by default)
            spec = self._build_spec(plan)
            self.registry.register(Capability(spec=spec))  # provisional
            test_ok, outcome = self._test(spec, plan)
            attempt.outcomes.append(outcome)
            if not test_ok:
                attempt.error = f"{outcome.tier.value} failed: {outcome.detail}"
                result.attempts.append(attempt)
                feedback = attempt.error
                continue

            # 4) REGISTER (probationary)
            spec.status = CapabilityStatus.PROBATIONARY
            spec.test_tier_passed = outcome.tier.value
            spec.test_summary = outcome.detail
            self.registry.register(Capability(spec=spec))
            self.memory.capability.save_capability(spec)
            result.success = True
            result.capability_name = spec.name
            result.attempts.append(attempt)
            break

        result.api_calls = self.client.api_calls - api_before
        result.llm_calls = self.llm.usage.calls - llm_before
        if not result.success:
            result.final_error = result.attempts[-1].error if result.attempts else "no attempts made"
        return result

    # ── steps ─────────────────────────────────────────────────────────────────
    def _propose(self, gap_intent: str, instruction: str, keywords: list[str], feedback: Optional[str]) -> CapabilityPlan:
        digest = self.client.schema_digest(keywords or ["issue"])
        caps = "\n".join(
            f"- {s.name}({', '.join(s.input_schema)}) — {s.description}"
            for s in sorted(self.registry.specs(), key=lambda s: s.name)
        )
        prompt = (
            f"INSTRUCTION: {instruction}\nCAPABILITY GAP (sub-goal with no capability): {gap_intent}\n\n"
            f"EXISTING CAPABILITIES (compose these):\n{caps}\n\n"
            f"PLATFORM SCHEMA (introspected):\n{digest}\n"
        )
        if feedback:
            prompt += f"\nYOUR PREVIOUS ATTEMPT FAILED: {feedback}\nFix it. Re-read the schema/capabilities carefully.\n"
        data = self.llm.generate_json(SYNTHESIZER_SYSTEM, prompt, max_tokens=2000)
        if not isinstance(data, dict):
            raise ValueError("synthesizer did not return a JSON object")
        return CapabilityPlan.model_validate(data)

    def _validate(self, plan: CapabilityPlan) -> list[str]:
        errors: list[str] = []
        if plan.kind == CapabilityKind.GRAPHQL:
            if plan.operation_type not in ("query", "mutation"):
                errors.append(f"operation_type must be query|mutation, got {plan.operation_type!r}")
            if not plan.graphql_root_field:
                errors.append("graphql_root_field is required")
            else:
                field = self.client.root_field(plan.operation_type or "query", plan.graphql_root_field)
                if field is None:
                    errors.append(
                        f"{plan.operation_type} root field '{plan.graphql_root_field}' does not exist in the schema"
                    )
                else:
                    valid_args = set(field.args)
                    for a in plan.args:
                        if a not in valid_args:
                            errors.append(f"arg '{a}' is not valid on '{plan.graphql_root_field}' (valid: {sorted(valid_args)})")
                    required = {n for n, ar in field.args.items() if str(ar.type).endswith("!") and ar.default_value is None}
                    missing = required - set(plan.args)
                    if missing:
                        errors.append(f"missing required arg(s) for '{plan.graphql_root_field}': {sorted(missing)}")
            if not plan.selection:
                errors.append("selection set is required for a graphql capability")
        elif plan.kind == CapabilityKind.COMPOSITE:
            if not plan.composition:
                errors.append("composite capability has no composition steps")
            for step in plan.composition:
                kind, _, name = step.op.partition(":")
                if kind == "capability":
                    if not self.registry.has(name):
                        errors.append(f"composition references unknown capability '{name}'")
                elif kind == "transform":
                    if name not in WHITELISTED_TRANSFORMS:
                        errors.append(f"composition references non-whitelisted transform '{name}'")
                else:
                    errors.append(f"invalid composition op '{step.op}'")
        else:
            errors.append(f"unknown capability kind {plan.kind!r}")
        return errors

    def _build_spec(self, plan: CapabilityPlan) -> CapabilitySpec:
        spec = CapabilitySpec(
            name=plan.name, kind=plan.kind, source=CapabilitySource.SYNTHESIZED,
            status=CapabilityStatus.PROBATIONARY, description=plan.description,
            input_schema=plan.input_schema, side_effecting=plan.side_effecting,
            synthesized_for=plan.rationale, schema_hash=self.client.schema_hash(),
        )
        if plan.kind == CapabilityKind.GRAPHQL:
            spec.graphql = self._assemble_graphql(plan)
            spec.select_path = plan.select_path
            if plan.inverse_root_field:
                spec.inverse_capability = plan.inverse_root_field
        else:
            spec.composition = [TransformStep.model_validate(s.model_dump()) for s in plan.composition]
        return spec

    @staticmethod
    def _assemble_graphql(plan: CapabilityPlan) -> str:
        """Construct the GraphQL document from the validated contract (no model-written GraphQL)."""
        op = plan.operation_type or "query"
        field = plan.graphql_root_field
        if plan.args:
            var_defs = ", ".join(f"${k}: {t}" for k, t in plan.args.items())
            arg_binds = ", ".join(f"{k}: ${k}" for k in plan.args)
            return f"{op}({var_defs}) {{ {field}({arg_binds}) {{ {plan.selection} }} }}"
        return f"{op} {{ {field} {{ {plan.selection} }} }}"

    def _test(self, spec: CapabilitySpec, plan: CapabilityPlan) -> tuple[bool, TestOutcome]:
        """Non-destructive tiered test. Reads execute; writes are validated via dry-run."""
        api_before = self.client.api_calls
        ctx = ExecutionContext(client=self.client, registry=self.registry,
                               memory=self.memory, settings=self.settings, dry_run=True)
        try:
            self.registry.run(spec.name, ctx, **(plan.probe_args or {}))
        except PlatformError as e:
            tier = TestTier.COMPOSITION if spec.kind == CapabilityKind.COMPOSITE else TestTier.READ_PROBE
            return False, TestOutcome(tier=tier, passed=False, detail=f"probe error: {e}",
                                      api_calls=self.client.api_calls - api_before)
        except Exception as e:  # noqa: BLE001 — surface any DSL/interpreter error as a failed test
            tier = TestTier.COMPOSITION if spec.kind == CapabilityKind.COMPOSITE else TestTier.READ_PROBE
            return False, TestOutcome(tier=tier, passed=False, detail=f"probe raised {type(e).__name__}: {e}",
                                      api_calls=self.client.api_calls - api_before)
        tier = TestTier.COMPOSITION if spec.kind == CapabilityKind.COMPOSITE else TestTier.READ_PROBE
        detail = ("composition dry-run: reads executed, writes shape-validated"
                  if spec.kind == CapabilityKind.COMPOSITE else "read probe succeeded")
        return True, TestOutcome(tier=tier, passed=True, detail=detail, api_calls=self.client.api_calls - api_before)
