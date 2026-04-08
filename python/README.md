# Symphony (Python + Claude Code)

Autonomous work orchestration service that polls Linear for issues, creates isolated per-issue workspaces, and runs Claude Code agents to complete tasks.

This is a Python port of the Elixir implementation, replacing OpenAI Codex with Claude Code as the AI agent runtime.

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Configure
export LINEAR_API_KEY="your-linear-api-key"
# Edit WORKFLOW.md with your project_slug

# Run
symphony WORKFLOW.md
# or
python -m symphony WORKFLOW.md
```

## Architecture

```
                          ┌──────────────┐
                          │  Linear API  │
                          └──────┬───────┘
                                 │ GraphQL
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator (asyncio)                                         │
│                                                                 │
│  poll tick ──► fetch candidates ──► dispatch eligible issues     │
│       ▲                                    │                    │
│       │                                    ▼                    │
│  task callback ◄──────────────  AgentRunner (asyncio.Task)      │
│  (retry / complete)                  │          │               │
│                                      ▼          ▼               │
│                               Workspace    Claude Code          │
│                              (filesystem)  (subprocess)         │
│                                                 │               │
│                                                 ▼               │
│                                        claude --print           │
│                                        --output-format json     │
└─────────────────────────────────────────────────────────────────┘
        │                        │
        ▼                        ▼
  StatusDashboard           HTTP Server
  (Rich terminal UI)     (FastAPI + WebSocket)
```

## Configuration

All configuration lives in `WORKFLOW.md` — a Markdown file with YAML front matter:

```yaml
---
tracker:
  kind: linear
  project_slug: "your-project-slug"
  active_states: [Todo, "In Progress"]
  terminal_states: [Done, Closed]
polling:
  interval_ms: 5000
workspace:
  root: ~/code/symphony-workspaces
agent:
  max_concurrent_agents: 10
  max_turns: 20
claude_code:
  command: claude
  model: claude-sonnet-4-20250514
  max_turns: 10
  permission_mode: accept-all
server:
  port: 4000
---

Your prompt template here using {{ issue.title }} variables...
```

## Key Differences from Elixir Version

| Aspect | Elixir | Python |
|--------|--------|--------|
| Runtime | BEAM/OTP | asyncio |
| AI Agent | Codex (JSON-RPC app-server) | Claude Code (subprocess) |
| Concurrency | GenServer + Task.Supervisor | asyncio.Lock + create_task |
| Config | Ecto schemas | Pydantic models |
| Templates | Liquid (Solid) | Jinja2 |
| Web | Phoenix LiveView | FastAPI + WebSocket |
| Terminal UI | ANSI rendering | Rich |
| HTTP Client | Req | httpx |

## CLI Options

```
symphony [WORKFLOW.md] [--logs-root DIR] [--port PORT] [--no-dashboard]
```

## API Endpoints

- `GET /api/v1/state` — Full orchestrator snapshot
- `GET /api/v1/issues/{identifier}` — Single issue detail
- `POST /api/v1/refresh` — Trigger immediate poll
- `WS /ws/dashboard` — Live dashboard updates

## Development

```bash
# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Environment Variables

- `LINEAR_API_KEY` — Required for Linear API access
- `LINEAR_ASSIGNEE` — Filter issues by assignee (use "me" for authenticated user)
- `SYMPHONY_SSH_CONFIG` — Custom SSH config file path
- `SYMPHONY_WORKSPACE_ROOT` — Override workspace directory
