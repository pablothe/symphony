# Symphony

Symphony is an autonomous work orchestration service that continuously polls
Linear for candidate issues, creates isolated per-issue workspaces, launches
Codex (an AI coding agent) to implement each task, and manages the full agent
lifecycle including retries, concurrency, and cleanup.

## Architecture

```
                          ┌──────────────┐
                          │  Linear API  │
                          └──────┬───────┘
                                 │ GraphQL
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator (GenServer)                                       │
│                                                                 │
│  poll tick ──► fetch candidates ──► dispatch eligible issues     │
│       ▲                                    │                    │
│       │                                    ▼                    │
│  :DOWN signal ◄──────────────────  AgentRunner (Task)           │
│  (retry / complete)                  │          │               │
│                                      ▼          ▼               │
│                               Workspace    Codex AppServer      │
│                              (filesystem)  (JSON-RPC stdio)     │
│                                                 │               │
│                                                 ▼               │
│                                          Codex subprocess       │
│                                          (app-server mode)      │
└─────────────────────────────────────────────────────────────────┘
        │                        │
        ▼                        ▼
  StatusDashboard           HttpServer
  (terminal UI)         (Phoenix LiveView
                         + JSON API)
```

## Core Components

All source files live under `elixir/lib/symphony_elixir/` unless noted otherwise.

### Orchestrator (`orchestrator.ex`)

Central GenServer running the main polling loop. Polls Linear on a configurable
cadence (default 30s), reconciles running agents against current issue states,
dispatches eligible issues up to the concurrency limit, and handles agent
completion with exponential backoff retries.

### Workflow & Config

- `workflow.ex` — Parses `WORKFLOW.md`: YAML front matter (config) + Markdown body (prompt template)
- `workflow_store.ex` — GenServer holding the current workflow with hot-reload support
- `config.ex` — Type-safe getters with defaults and env var expansion
- `config/schema.ex` — Ecto-based schema defining all config fields and validation

### Issue Tracking (Linear)

- `tracker.ex` — Abstract behaviour for tracker implementations
- `tracker/memory.ex` — In-memory tracker for tests
- `linear/client.ex` — GraphQL client with paginated queries and mutations
- `linear/adapter.ex` — Normalizes Linear API responses to a stable internal model
- `linear/issue.ex` — Issue struct: id, identifier, title, description, state, labels, etc.

### Workspace (`workspace.ex`)

Per-issue filesystem isolation. Maps issue identifiers to directories, creates
them with `hooks.after_create` (e.g. `git clone`), validates paths stay under
the configured root (`path_safety.ex`), and supports SSH remote hosts.

### Agent Execution

- `agent_runner.ex` — Full lifecycle for a single issue: create workspace → build prompt → run Codex turns → handle completion
- `prompt_builder.ex` — Renders the WORKFLOW.md body as a Liquid template with issue context
- `ssh.ex` — Remote workspace execution over SSH

### Codex Integration

- `codex/app_server.ex` — JSON-RPC 2.0 client over stdio managing Codex session lifecycle
- `codex/dynamic_tool.ex` — Runtime tools exposed to Codex (e.g. `linear_graphql` for raw GraphQL calls)

### Observability

- `status_dashboard.ex` — Terminal UI: running agents, token throughput, retry queue
- `http_server.ex` — Optional Phoenix endpoint
- `symphony_elixir_web/` — LiveView dashboard at `/`, JSON API at `/api/v1/*`
- `log_file.ex` — Structured logging with issue/session context

## Execution Flow

1. **Poll** — Orchestrator fetches issues in configured `active_states` from Linear
2. **Filter** — Skip issues already running, claimed this cycle, or blocked
3. **Dispatch** — If a concurrency slot is available, spawn an AgentRunner task
4. **Workspace** — Create isolated directory, run `after_create` hook
5. **Prompt** — Render WORKFLOW.md template with issue data
6. **Session** — Spawn Codex subprocess, start JSON-RPC session
7. **Turn loop** — Codex works on the issue for up to `agent.max_turns` turns
8. **Completion** — AgentRunner returns result to Orchestrator
9. **Reconcile** — Check issue state: still active → retry with backoff; terminal → cleanup
10. **Repeat**

## OTP Supervision Tree

```
Application
├── Phoenix.PubSub          — inter-process messaging
├── Task.Supervisor          — managed spawning of AgentRunner tasks
├── WorkflowStore            — loads and watches WORKFLOW.md
├── Orchestrator             — main polling loop
├── HttpServer               — optional Phoenix endpoint
└── StatusDashboard          — terminal UI rendering
```

## Build & Test

```bash
cd elixir
mise trust && mise install
mix setup
mix build                    # creates bin/symphony
./bin/symphony ./WORKFLOW.md # run with a workflow file
```

```bash
make all       # full CI: format check, lint, dialyzer, tests with 100% coverage
make test      # unit tests only
make e2e       # live end-to-end test (requires LINEAR_API_KEY)
```

## Environment Variables

- `LINEAR_API_KEY` — Required for Linear API access
- `SYMPHONY_WORKSPACE_ROOT` — Custom workspace directory (default: `~/code/symphony-workspaces`)
- `CODEX_BIN` — Path to Codex binary (default: `codex`)

## Key Design Decisions

- **Elixir/OTP** — BEAM provides lightweight processes, supervision trees, and hot code reloading for managing many concurrent long-running agents
- **Workspace isolation** — Each issue gets its own directory preventing cross-contamination
- **Exponential backoff** — Failed agents retry with `base * 2^(attempt-1)` capped at a configurable max
- **WORKFLOW.md** — Config and prompt templates version-controlled in-repo alongside the code
- **Hot-reload** — WorkflowStore watches WORKFLOW.md; failed reloads preserve last good config

## Directory Structure

```
elixir/lib/
├── symphony_elixir.ex                   # Application entry point
├── symphony_elixir/
│   ├── orchestrator.ex                  # Core polling loop & dispatch
│   ├── agent_runner.ex                  # Per-issue agent lifecycle
│   ├── workspace.ex                     # Workspace directory management
│   ├── workflow.ex                      # WORKFLOW.md parser
│   ├── workflow_store.ex                # Config hot-reload GenServer
│   ├── config.ex                        # Typed config access
│   ├── config/schema.ex                 # Config validation schema
│   ├── tracker.ex                       # Tracker behaviour
│   ├── tracker/memory.ex                # In-memory tracker (tests)
│   ├── linear/
│   │   ├── client.ex                    # Linear GraphQL client
│   │   ├── adapter.ex                   # Response normalization
│   │   └── issue.ex                     # Issue data model
│   ├── codex/
│   │   ├── app_server.ex                # Codex JSON-RPC client
│   │   └── dynamic_tool.ex              # Runtime tools for Codex
│   ├── prompt_builder.ex                # Liquid template rendering
│   ├── status_dashboard.ex              # Terminal UI
│   ├── http_server.ex                   # Phoenix server startup
│   ├── log_file.ex                      # Structured file logging
│   ├── path_safety.ex                   # Workspace path validation
│   ├── ssh.ex                           # Remote execution over SSH
│   └── cli.ex                           # CLI argument parsing
├── symphony_elixir_web/
│   ├── router.ex                        # HTTP routes
│   ├── endpoint.ex                      # Phoenix endpoint
│   ├── presenter.ex                     # State presentation
│   ├── live/                            # LiveView components
│   └── controllers/                     # API & asset controllers
└── mix/tasks/                           # Custom Mix tasks
```

## References

- [SPEC.md](SPEC.md) — Language-agnostic specification
- [elixir/README.md](elixir/README.md) — Setup, configuration, and usage guide
- [elixir/WORKFLOW.md](elixir/WORKFLOW.md) — Example workflow configuration
- [elixir/docs/logging.md](elixir/docs/logging.md) — Logging conventions
- [elixir/docs/token_accounting.md](elixir/docs/token_accounting.md) — Token usage tracking
