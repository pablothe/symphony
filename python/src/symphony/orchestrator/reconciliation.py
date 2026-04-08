"""Running issue state reconciliation.

Fetches current states for running issues and determines which ones
should be stopped because they moved to terminal or non-active states.
"""

from __future__ import annotations

import logging

from symphony.models.issue import Issue
from symphony.models.state import OrchestratorState
from symphony.orchestrator.dispatch import is_active_state, is_terminal_state
from symphony.tracker.base import TrackerProtocol

logger = logging.getLogger(__name__)


async def reconcile_running_issues(
    state: OrchestratorState,
    tracker: TrackerProtocol,
    active_states: list[str],
    terminal_states: list[str],
) -> list[str]:
    """Check running issues and return IDs that should be stopped.

    An issue should be stopped if:
    - It moved to a terminal state
    - It moved to a non-active state
    - It was not found (deleted)
    """
    if not state.running:
        return []

    running_ids = list(state.running.keys())

    try:
        refreshed = await tracker.fetch_issue_states_by_ids(running_ids)
    except Exception as e:
        logger.error("Failed to reconcile running issues: %s", e)
        return []

    refreshed_by_id: dict[str, Issue] = {}
    for issue in refreshed:
        if issue.id:
            refreshed_by_id[issue.id] = issue

    issues_to_stop: list[str] = []

    for issue_id in running_ids:
        refreshed_issue = refreshed_by_id.get(issue_id)

        if refreshed_issue is None:
            # Issue not found — stop it
            logger.info("Issue %s not found during reconciliation, stopping", issue_id)
            issues_to_stop.append(issue_id)
            continue

        issue_state = refreshed_issue.state
        if issue_state is None:
            issues_to_stop.append(issue_id)
            continue

        if is_terminal_state(issue_state, terminal_states):
            logger.info(
                "Issue %s moved to terminal state '%s', stopping",
                refreshed_issue.identifier, issue_state,
            )
            issues_to_stop.append(issue_id)
            continue

        if not is_active_state(issue_state, active_states):
            logger.info(
                "Issue %s moved to non-active state '%s', stopping",
                refreshed_issue.identifier, issue_state,
            )
            issues_to_stop.append(issue_id)

    return issues_to_stop


def find_stalled_issues(
    state: OrchestratorState,
    stall_timeout_ms: int,
    now_mono: float,
) -> list[str]:
    """Find running issues that have stalled (no activity for too long).

    Returns list of issue IDs that should be restarted.
    """
    if stall_timeout_ms <= 0:
        return []

    stalled: list[str] = []
    stall_threshold_s = stall_timeout_ms / 1000

    for issue_id, entry in state.running.items():
        if entry.last_timestamp is None:
            # No activity yet — check against start time
            if entry.started_at is None:
                continue
            elapsed = now_mono - entry.started_at.timestamp()
        else:
            elapsed = now_mono - entry.last_timestamp.timestamp()

        if elapsed > stall_threshold_s:
            logger.warning(
                "Issue %s has stalled (no activity for %.0fs, threshold %.0fs)",
                entry.identifier, elapsed, stall_threshold_s,
            )
            stalled.append(issue_id)

    return stalled
