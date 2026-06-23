# Contributing

Thanks for taking a look. This documents how the project is developed and the
conventions it follows.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"        # editable install + dev tools (pytest, ruff)

# frontend
cd web && npm install
```

## Running it

```bash
praxis demo --offline          # the 3 graded instructions, no API keys
praxis bench                   # the learning before/after numbers
praxis serve --offline         # JSON API + dashboard on :8000
cd web && npm run dev          # the Next.js console on :3000
```

## Tests, lint, format

The Python suite runs fully offline and deterministically (no API keys, no
network):

```bash
pytest                         # 100+ tests
ruff check .                   # lint
ruff format .                  # format
cd web && npm run build        # type-check + build the frontend
```

CI runs all of the above on every push (`.github/workflows/ci.yml`).

## Code style

- **Python** — formatted and linted with [ruff](https://docs.astral.sh/ruff/)
  (config in `pyproject.toml`); 100-column lines; type hints on public
  functions; module docstrings explain *why*, not just *what*.
- **TypeScript / React** — `eslint-config-next`; functional components; design
  tokens live in `web/tailwind.config.ts` and `web/app/globals.css`, not inline
  magic values.

## Commit messages — Conventional Commits

This repository follows the [Conventional Commits](https://www.conventionalcommits.org/)
specification:

```
<type>(<optional scope>): <summary in the imperative, lower-case>

<optional body explaining what and why>
```

Types used here:

| type       | when                                                        |
| ---------- | ----------------------------------------------------------- |
| `feat`     | a new capability or user-facing feature                     |
| `fix`      | a bug fix (correctness, security, behaviour)                |
| `refactor` | a code change that neither fixes a bug nor adds a feature   |
| `perf`     | a performance improvement                                   |
| `test`     | adding or changing tests                                    |
| `docs`     | documentation only                                          |
| `build`    | build system, dependencies, packaging                       |
| `ci`       | CI configuration                                            |
| `style`    | formatting only (no logic change)                           |
| `chore`    | tooling/maintenance with no src or test change              |

Scopes mirror the package layout: `core`, `memory`, `capabilities`, `agent`,
`cli`, `server`, `web`. Keep the summary under ~72 characters; put the detail in
the body.

## Branching

Work happens on `main`. Keep commits small, focused, and green — every commit
should pass `pytest` and `ruff check`.
