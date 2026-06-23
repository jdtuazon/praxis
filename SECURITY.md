# Security

## Reporting a vulnerability

Please report security issues privately by opening a
[GitHub security advisory](https://github.com/jdtuazon/watermelon/security/advisories/new)
rather than a public issue. You can expect an initial response within a few days.

## Trust boundaries

Praxis synthesizes and runs capabilities at runtime, so the trust boundary is
documented explicitly:

- **No arbitrary code execution.** Synthesized `composite` capabilities run in a
  constrained DSL that can only call already-registered capabilities and a fixed
  set of pure transforms — no `import`, `exec`, `eval`, filesystem, or network.
  Raw-Python synthesis is deliberately not enabled.
- **Schema-validated operations.** Synthesized GraphQL is assembled from a typed
  contract and the full document is parsed and validated against the live schema
  before any call, so an injected sibling operation is rejected at zero API cost.
- **Non-destructive testing by default.** The synthesis test gate uses
  schema-check and dry-run tiers; a side-effecting operation is never executed
  during a probe (the write-guard derives this from the operation type, not a
  model-supplied flag).
- **Secrets.** API keys are read from the environment / `.env` and are never
  written to memory, logs, or the structured report.

## Supported versions

This is a recruitment/demonstration project; only the latest `main` is
maintained.
