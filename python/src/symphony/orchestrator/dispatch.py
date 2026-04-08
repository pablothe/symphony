"""Issue dispatch logic: sorting, eligibility, and slot management.

Pure functions extracted from the orchestrator for testability.
"""

from __future__ import annotations

from symphony.config.schema import normalize_issue_state
from symphony.models.issue import Issue
from symphony.models.state import OrchestratorState, RunningEntry


def sort_issues_for_dispatch(issues: list[Issue]) -> list[Issue]:
    """Sort issues for dispatch priority.

    Priority order:
    1. Lower priority number first (higher priority)
    2. Earlier created_at first
    3. Alphabetical identifier as tiebreaker
    """
    return sorted(
        issues,
        key=lambda i: (
            i.priority if i.priority is not None else 999,
            i.created_at or "",
            i.identifier or "",
        ),
    )


def should_dispatch_issue(
    issue: Issue,
    state: OrchestratorState,
    active_states: list[str],
    terminal_states: list[str],
) -> bool:
    """Check if an issue is eligible for dispatch.

    An issue is eligible if:
    - It has an active state
    - It is not in a terminal state
    - It is not already claimed/running/retrying
    - It is assigned to this worker (assigned_to_worker == True)
    - It is not blocked by non-terminal issues
    - There are available concurrency slots
    """
    if not issue.id or not issue.state:
        return False

    if not issue.assigned_to_worker:
        return False

    if state.is_claimed(issue.id):
        return False

    if not is_active_state(issue.state, active_states):
        return False

    if is_terminal_state(issue.state, terminal_states):
        return False

    if is_blocked_by_non_terminal(issue, terminal_states):
        return False

    if state.available_slots() <= 0:
        return False

    if not state_slots_available(issue, state):
        return False

    return True


def is_active_state(state_name: str, active_states: list[str]) -> bool:
    """Check if a state name is in the active states list."""
    normalized = normalize_issue_state(state_name)
    return any(normalize_issue_state(s) == normalized for s in active_states)


def is_terminal_state(state_name: str, terminal_states: list[str]) -> bool:
    """Check if a state name is in the terminal states list."""
    normalized = normalize_issue_state(state_name)
    return any(normalize_issue_state(s) == normalized for s in terminal_states)


def is_blocked_by_non_terminal(issue: Issue, terminal_states: list[str]) -> bool:
    """Check if an issue is blocked by any non-terminal issues.

    Only applies to issues in "todo" state.
    """
    if not issue.state or normalize_issue_state(issue.state) != "todo":
        return False

    for blocker in issue.blocked_by:
        if blocker.state is None:
            continue
        if not is_terminal_state(blocker.state, terminal_states):
            return True

    return False


def state_slots_available(issue: Issue, state: OrchestratorState) -> bool:
    """Check if there are per-state concurrency slots available."""
    if not issue.state:
        return True

    from symphony.config.config import max_concurrent_agents_for_state

    limit = max_concurrent_agents_for_state(issue.state)
    normalized = normalize_issue_state(issue.state)

    # Count running issues in the same state
    count = sum(
        1
        for entry in state.running.values()
        if entry.issue_state and normalize_issue_state(entry.issue_state) == normalized
    )

    return count < limit


def select_worker_host(
    state: OrchestratorState,
    ssh_hosts: list[str],
    max_per_host: int | None,
    preferred_host: str | None = None,
) -> str | None:
    """Select a worker host with available capacity.

    Returns None if no hosts are configured (local execution).
    Returns the host string if a host is available.
    Raises ValueError if all hosts are at capacity.
    """
    if not ssh_hosts:
        return None

    hosts = list(dict.fromkeys(h.strip() for h in ssh_hosts if h.strip()))
    if not hosts:
        return None

    if max_per_host is None:
        max_per_host = state.max_concurrent_agents

    def host_load(host: str) -> int:
        return sum(1 for e in state.running.values() if e.worker_host == host)

    # Prefer the specified host if it has capacity
    if preferred_host and preferred_host in hosts:
        if host_load(preferred_host) < max_per_host:
            return preferred_host

    # Find available hosts sorted by load
    available = [(h, host_load(h)) for h in hosts if host_load(h) < max_per_host]
    if not available:
        raise ValueError("No worker hosts with available capacity")

    # Return least-loaded host
    available.sort(key=lambda x: x[1])
    return available[0][0]
