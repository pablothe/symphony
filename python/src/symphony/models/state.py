"""Orchestrator runtime state models."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AgentTotals:
    """Aggregate token usage and runtime across all agent sessions."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    seconds_running: float = 0.0


@dataclass
class RunningEntry:
    """State tracked for an actively running agent task."""

    issue_id: str
    identifier: str
    issue_state: str | None = None
    task: asyncio.Task | None = None  # type: ignore[type-arg]
    worker_host: str | None = None
    workspace_path: str | None = None
    session_id: str | None = None
    started_at: datetime | None = None
    turn_count: int = 0

    # Token accounting
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    last_reported_input_tokens: int = 0
    last_reported_output_tokens: int = 0
    last_reported_total_tokens: int = 0

    # Observability
    last_event: str | None = None
    last_timestamp: datetime | None = None
    last_message: str | None = None


@dataclass
class RetryEntry:
    """Scheduled retry state for an issue."""

    issue_id: str
    identifier: str
    attempt: int
    due_at_mono: float  # monotonic clock timestamp
    timer_handle: asyncio.TimerHandle | None = None
    error: str | None = None
    worker_host: str | None = None
    workspace_path: str | None = None


@dataclass
class OrchestratorState:
    """Single authoritative in-memory state owned by the orchestrator."""

    poll_interval_ms: int = 30_000
    max_concurrent_agents: int = 10
    running: dict[str, RunningEntry] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)
    retry_attempts: dict[str, RetryEntry] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    agent_totals: AgentTotals = field(default_factory=AgentTotals)
    rate_limits: dict | None = None

    # Polling state
    next_poll_due_at: float | None = None
    poll_check_in_progress: bool = False

    @property
    def running_count(self) -> int:
        return len(self.running)

    @property
    def retrying_count(self) -> int:
        return len(self.retry_attempts)

    def available_slots(self) -> int:
        return max(0, self.max_concurrent_agents - len(self.running))

    def is_claimed(self, issue_id: str) -> bool:
        return issue_id in self.claimed or issue_id in self.running or issue_id in self.retry_attempts
