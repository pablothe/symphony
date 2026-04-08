"""Typed configuration schema for WORKFLOW.md front matter.

Replaces the Elixir Ecto-based Config.Schema with Pydantic models.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


def _resolve_env_reference(value: str | None, fallback: str | None = None) -> str | None:
    """Resolve $VAR_NAME references to environment variable values."""
    if value is None:
        return _normalize_secret(fallback)

    match = re.match(r"^\$([A-Za-z_][A-Za-z0-9_]*)$", value)
    if match:
        env_name = match.group(1)
        env_value = os.environ.get(env_name)
        if env_value is None:
            return _normalize_secret(fallback)
        if env_value == "":
            return None
        return env_value

    return value


def _resolve_path_value(value: str | None, default: str) -> str:
    """Resolve a path value, expanding ~ and $VAR references."""
    if value is None or value == "":
        return default

    match = re.match(r"^\$([A-Za-z_][A-Za-z0-9_]*)$", value)
    if match:
        env_name = match.group(1)
        env_value = os.environ.get(env_name)
        if env_value is None or env_value == "":
            return default
        return env_value

    return str(Path(value).expanduser())


def _normalize_secret(value: str | None) -> str | None:
    """Normalize a secret value — empty strings become None."""
    if isinstance(value, str) and value == "":
        return None
    return value


def normalize_issue_state(state_name: str) -> str:
    """Normalize an issue state name for comparison."""
    return state_name.lower()


class TrackerConfig(BaseModel):
    """Issue tracker configuration."""

    kind: str | None = None
    endpoint: str = "https://api.linear.app/graphql"
    api_key: str | None = None
    project_slug: str | None = None
    assignee: str | None = None
    active_states: list[str] = Field(default_factory=lambda: ["Todo", "In Progress"])
    terminal_states: list[str] = Field(
        default_factory=lambda: ["Closed", "Cancelled", "Canceled", "Duplicate", "Done"]
    )


class PollingConfig(BaseModel):
    """Polling interval configuration."""

    interval_ms: int = Field(default=30_000, gt=0)


class WorkspaceConfig(BaseModel):
    """Workspace directory configuration."""

    root: str = Field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "symphony_workspaces"))


class WorkerConfig(BaseModel):
    """SSH worker configuration."""

    ssh_hosts: list[str] = Field(default_factory=list)
    max_concurrent_agents_per_host: int | None = Field(default=None, gt=0)


class AgentConfig(BaseModel):
    """Agent concurrency and retry configuration."""

    max_concurrent_agents: int = Field(default=10, gt=0)
    max_turns: int = Field(default=20, gt=0)
    max_retry_backoff_ms: int = Field(default=300_000, gt=0)
    max_concurrent_agents_by_state: dict[str, int] = Field(default_factory=dict)

    @field_validator("max_concurrent_agents_by_state")
    @classmethod
    def normalize_state_limits(cls, v: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for state_name, limit in v.items():
            if not state_name:
                raise ValueError("state names must not be blank")
            if not isinstance(limit, int) or limit <= 0:
                raise ValueError("limits must be positive integers")
            normalized[normalize_issue_state(str(state_name))] = limit
        return normalized


class ClaudeCodeConfig(BaseModel):
    """Claude Code agent configuration (replaces Codex config)."""

    command: str = "claude"
    model: str | None = None
    max_turns: int | None = Field(default=None, gt=0)
    permission_mode: str = "accept-all"
    allowed_tools: list[str] = Field(default_factory=list)
    mcp_config: str | None = None
    turn_timeout_ms: int = Field(default=3_600_000, gt=0)
    stall_timeout_ms: int = Field(default=300_000, ge=0)


class HooksConfig(BaseModel):
    """Workspace lifecycle hooks."""

    after_create: str | None = None
    before_run: str | None = None
    after_run: str | None = None
    before_remove: str | None = None
    timeout_ms: int = Field(default=60_000, gt=0)


class ObservabilityConfig(BaseModel):
    """Dashboard and observability settings."""

    dashboard_enabled: bool = True
    refresh_ms: int = Field(default=1_000, gt=0)
    render_interval_ms: int = Field(default=16, gt=0)


class ServerConfig(BaseModel):
    """HTTP server configuration."""

    port: int | None = Field(default=None, ge=0)
    host: str = "127.0.0.1"


class SymphonyConfig(BaseModel):
    """Root configuration model composed from WORKFLOW.md front matter."""

    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    polling: PollingConfig = Field(default_factory=PollingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    claude_code: ClaudeCodeConfig = Field(default_factory=ClaudeCodeConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    @model_validator(mode="before")
    @classmethod
    def drop_none_values(cls, data: dict) -> dict:  # type: ignore[type-arg]
        """Strip None values so defaults apply, and normalize string keys."""
        if not isinstance(data, dict):
            return data
        return _drop_nones(_normalize_keys(data))

    def finalize(self) -> SymphonyConfig:
        """Resolve environment variables and expand paths. Called after parsing."""
        default_ws_root = str(Path(tempfile.gettempdir()) / "symphony_workspaces")

        tracker = self.tracker.model_copy(
            update={
                "api_key": _resolve_env_reference(
                    self.tracker.api_key, os.environ.get("LINEAR_API_KEY")
                ),
                "assignee": _resolve_env_reference(
                    self.tracker.assignee, os.environ.get("LINEAR_ASSIGNEE")
                ),
            }
        )

        workspace = self.workspace.model_copy(
            update={
                "root": _resolve_path_value(self.workspace.root, default_ws_root),
            }
        )

        return self.model_copy(update={"tracker": tracker, "workspace": workspace})


def parse_config(config: dict) -> SymphonyConfig:  # type: ignore[type-arg]
    """Parse and validate a WORKFLOW.md config dict into a typed SymphonyConfig.

    Raises ValueError on validation failure.
    """
    try:
        settings = SymphonyConfig.model_validate(config)
        return settings.finalize()
    except Exception as e:
        raise ValueError(f"Invalid WORKFLOW.md config: {e}") from e


def _normalize_keys(data: object) -> object:
    """Recursively normalize all map keys to strings."""
    if isinstance(data, dict):
        return {str(k): _normalize_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize_keys(item) for item in data]
    return data


def _drop_nones(data: object) -> object:
    """Recursively strip None values from dicts so Pydantic defaults apply."""
    if isinstance(data, dict):
        return {k: _drop_nones(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [_drop_nones(item) for item in data]
    return data
