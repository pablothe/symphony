# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Symphony is an autonomous work orchestration service that polls Linear for issues, creates isolated per-issue workspaces, launches an AI coding agent (Codex for Elixir, Claude Code for Python) to implement each task, and manages agent lifecycle including retries, concurrency, and cleanup.

There are two independent implementations: **Elixir** (primary, with CI) and **Python**.

## Build & Test Commands

### Elixir (`cd elixir`)

```bash
mise trust && mise install          # install Erlang 28 + Elixir 1.19.x
mix setup                           # fetch deps
mix build                           # creates bin/symphony (escript)
./bin/symphony ./WORKFLOW.md        # run with a workflow file

# Testing
mix test                            # all tests
mix test test/symphony_elixir/core_test.exs        # single file
mix test test/symphony_elixir/core_test.exs:42     # single test at line

# Quality gates
make all                            # full CI: fmt-check, lint, coverage (100%), dialyzer
make fmt                            # auto-format
make fmt-check                      # check formatting (CI uses this)
make lint                           # mix specs.check + mix credo --strict
make coverage                       # mix test --cover (enforces 100% threshold)
make dialyzer                       # static type analysis
make e2e                            # live e2e test (needs LINEAR_API_KEY, SYMPHONY_LIVE_LINEAR_TEAM_KEY)
```

### Python (`cd python`)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run
symphony WORKFLOW.md                # or: python -m symphony WORKFLOW.md

# Testing
pytest tests/ -v                    # all tests
pytest tests/test_foo.py            # single file
pytest -k "test_name"              # single test by name

# Lint & type check
ruff check src/ tests/              # lint (line length 100)
mypy src/                           # strict mode, Python 3.11
```

## Architecture

```
                          ┌──────────────┐
                          │  Linear API  │
                          └──────┬───────┘
                                 │ GraphQL
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator                                                   │
│  poll tick ──► fetch candidates ──► dispatch eligible issues     │
│       ▲                                    │                    │
│       │                                    ▼                    │
│  completion ◄────────────────────  AgentRunner                  │
│  (retry / done)                      │          │               │
│                                      ▼          ▼               │
│                               Workspace    AI Agent             │
│                              (filesystem)  (Codex / Claude)     │
└─────────────────────────────────────────────────────────────────┘
        │                        │
        ▼                        ▼
  StatusDashboard           Web Server
  (terminal UI)         (LiveView / FastAPI)
```

### Elixir Implementation

OTP/GenServer-based. Source: `elixir/lib/symphony_elixir/`.

- **Orchestrator** (`orchestrator.ex`) — GenServer polling loop, dispatch, retry with exponential backoff
- **AgentRunner** (`agent_runner.ex`) — per-issue lifecycle: workspace → prompt → Codex turns → completion
- **Codex integration** (`codex/app_server.ex`) — JSON-RPC 2.0 over stdio; `codex/dynamic_tool.ex` for runtime tools
- **Workflow** (`workflow.ex`, `workflow_store.ex`) — parses WORKFLOW.md (YAML front matter + Liquid template body), hot-reloads at runtime
- **Config** (`config.ex`, `config/schema.ex`) — Ecto-based typed config with env var expansion
- **Linear** (`linear/client.ex`, `linear/adapter.ex`) — GraphQL client + response normalization
- **Workspace** (`workspace.ex`, `path_safety.ex`) — per-issue directory isolation, SSH support via `ssh.ex`
- **Web** (`symphony_elixir_web/`) — Phoenix LiveView dashboard at `/`, JSON API at `/api/v1/*`

OTP supervision tree: PubSub, Task.Supervisor (AgentRunner tasks), WorkflowStore, Orchestrator, HttpServer, StatusDashboard.

### Python Implementation

asyncio-based. Source: `python/src/symphony/`.

- Uses Claude Code (not Codex) via `claude --print --output-format json`
- Config key is `claude_code:` (not `codex:`), Jinja2 templates (not Liquid), Pydantic models
- FastAPI + WebSocket for web, Rich for terminal UI

### Key Design Decisions

- **Workspace isolation** — each issue gets its own directory, never run agent in source repo
- **Exponential backoff** — `base * 2^(attempt-1)` capped at configurable max
- **WORKFLOW.md** — config + prompt template version-controlled together; hot-reload preserves last good config on failure

## Coding Conventions

### Elixir

- All public `def` functions in `lib/` must have an adjacent `@spec` (enforced by `mix specs.check`). `defp` and `@impl` callbacks are exempt.
- Config access through `SymphonyElixir.Config` — no ad-hoc env reads.
- Follow `elixir/docs/logging.md` for logging conventions and required issue/session context fields.
- Tests use `use SymphonyElixir.TestSupport` and `SymphonyElixir.Tracker.Memory` (in-memory tracker) to avoid real Linear calls.
- Keep implementation aligned with `SPEC.md` — may be a superset but must not conflict.

### Python

- Strict mypy, ruff linting (rules: E, F, I, N, W, UP), line length 100.
- asyncio_mode = "auto" for pytest-asyncio.

## PR Requirements

- PR body must follow `.github/pull_request_template.md` exactly (Context, TL;DR, Summary, Alternatives, Test Plan sections).
- Validate locally: `mix pr_body.check --file /path/to/pr_body.md`
- If behavior/config changes, update docs in the same PR: root `README.md`, `elixir/README.md`, `elixir/WORKFLOW.md`.

## Environment Variables

- `LINEAR_API_KEY` — required for Linear API access
- `SYMPHONY_WORKSPACE_ROOT` — custom workspace directory (default: `~/code/symphony-workspaces`)
- `CODEX_BIN` — path to Codex binary (default: `codex`)
- `SYMPHONY_LIVE_LINEAR_TEAM_KEY` — e2e test team key (default: `SYME2E`)

## References

- [SPEC.md](SPEC.md) — language-agnostic specification
- [elixir/README.md](elixir/README.md) — Elixir setup, configuration, and usage
- [elixir/WORKFLOW.md](elixir/WORKFLOW.md) — example workflow configuration
- [elixir/docs/logging.md](elixir/docs/logging.md) — logging conventions
- [elixir/docs/token_accounting.md](elixir/docs/token_accounting.md) — token usage tracking
- [python/README.md](python/README.md) — Python implementation details
