"""Agent run lifecycle management.

Orchestrates the full lifecycle for a single issue:
workspace creation -> prompt building -> Claude Code turns -> cleanup.
"""

from __future__ import annotations

import logging
from typing import Callable

from symphony.agent.claude_code import ClaudeCodeSession, TurnResult, UpdateCallback
from symphony.config.config import settings
from symphony.config.schema import normalize_issue_state
from symphony.models.issue import Issue
from symphony.tracker.base import TrackerProtocol
from symphony.workspace import manager as workspace_mgr
from symphony.workflow.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


RuntimeInfoCallback = Callable[[str, dict], None]  # type: ignore[type-arg]


class AgentRunError(Exception):
    """Error during an agent run."""


async def run(
    issue: Issue,
    tracker: TrackerProtocol,
    on_update: UpdateCallback | None = None,
    on_runtime_info: RuntimeInfoCallback | None = None,
    worker_host: str | None = None,
    max_turns: int | None = None,
) -> None:
    """Execute a full agent run for an issue.

    Creates workspace, builds prompt, runs Claude Code turns, handles cleanup.

    Args:
        issue: The issue to work on.
        tracker: Tracker for fetching issue state between turns.
        on_update: Callback for agent progress updates.
        on_runtime_info: Callback for worker runtime info (host, workspace path).
        worker_host: Optional SSH worker host.
        max_turns: Override for max turns (defaults to config).

    Raises:
        AgentRunError on failure.
    """
    config = settings()
    effective_max_turns = max_turns or config.agent.max_turns
    host = _select_worker_host(worker_host, config.worker.ssh_hosts)

    log_host = host or "local"
    logger.info(
        "Starting agent run issue_id=%s identifier=%s worker_host=%s",
        issue.id, issue.identifier, log_host,
    )

    # Create workspace
    try:
        workspace = await workspace_mgr.create_for_issue(issue, host)
    except Exception as e:
        raise AgentRunError(f"Workspace creation failed: {e}") from e

    # Notify orchestrator of runtime info
    if on_runtime_info and issue.id:
        on_runtime_info(issue.id, {
            "worker_host": host,
            "workspace_path": workspace,
        })

    try:
        # Run before_run hook
        await workspace_mgr.run_before_run_hook(workspace, issue, host)

        # Run Claude Code turns
        await _run_claude_turns(
            workspace=workspace,
            issue=issue,
            tracker=tracker,
            on_update=on_update,
            worker_host=host,
            max_turns=effective_max_turns,
        )
    finally:
        # Always run after_run hook
        await workspace_mgr.run_after_run_hook(workspace, issue, host)


async def _run_claude_turns(
    workspace: str,
    issue: Issue,
    tracker: TrackerProtocol,
    on_update: UpdateCallback | None,
    worker_host: str | None,
    max_turns: int,
) -> None:
    """Run Claude Code turns in a loop, checking issue state between turns."""
    session = ClaudeCodeSession(workspace=workspace, worker_host=worker_host)

    try:
        current_issue = issue
        for turn_number in range(1, max_turns + 1):
            prompt = _build_turn_prompt(current_issue, turn_number, max_turns)

            logger.info(
                "Starting turn %d/%d for %s",
                turn_number, max_turns, current_issue.identifier,
            )

            result: TurnResult = await session.run_turn(
                prompt=prompt,
                issue=current_issue,
                on_update=on_update,
            )

            logger.info(
                "Completed turn %d/%d for %s session_id=%s success=%s",
                turn_number, max_turns, current_issue.identifier,
                result.session_id, result.success,
            )

            if not result.success:
                logger.error(
                    "Claude Code turn failed for %s: %s",
                    current_issue.identifier, result.error,
                )
                raise AgentRunError(f"Turn {turn_number} failed: {result.error}")

            # Check if we should continue
            if turn_number >= max_turns:
                logger.info(
                    "Reached max_turns=%d for %s, returning control to orchestrator",
                    max_turns, current_issue.identifier,
                )
                return

            continuation = await _check_continue(current_issue, tracker)

            if continuation is None:
                # Issue is no longer active
                logger.info(
                    "Issue %s is no longer active, ending agent run",
                    current_issue.identifier,
                )
                return

            current_issue = continuation
            logger.info(
                "Continuing agent run for %s after turn %d",
                current_issue.identifier, turn_number,
            )

    finally:
        await session.cancel()


def _build_turn_prompt(issue: Issue, turn_number: int, max_turns: int) -> str:
    """Build the prompt for a given turn."""
    if turn_number == 1:
        return build_prompt(issue)

    return (
        f"The issue {issue.identifier} is still in state '{issue.state}'. "
        f"This is continuation turn {turn_number}/{max_turns}. "
        f"Continue working on the remaining tasks — do not restart from scratch."
    )


async def _check_continue(
    issue: Issue,
    tracker: TrackerProtocol,
) -> Issue | None:
    """Check if the issue is still active and should continue.

    Returns the refreshed Issue if active, None if done.
    """
    if not issue.id:
        return None

    try:
        refreshed = await tracker.fetch_issue_states_by_ids([issue.id])
    except Exception as e:
        logger.error("Failed to refresh issue state for %s: %s", issue.identifier, e)
        return None

    if not refreshed:
        return None

    refreshed_issue = refreshed[0]
    if _is_active_state(refreshed_issue.state):
        return refreshed_issue

    return None


def _is_active_state(state_name: str | None) -> bool:
    """Check if a state name is in the configured active states."""
    if state_name is None:
        return False

    config = settings()
    normalized = normalize_issue_state(state_name)
    return any(
        normalize_issue_state(s) == normalized
        for s in config.tracker.active_states
    )


def _select_worker_host(
    preferred: str | None,
    configured_hosts: list[str],
) -> str | None:
    """Select the worker host to use."""
    hosts = [h.strip() for h in configured_hosts if h.strip()]
    hosts = list(dict.fromkeys(hosts))  # deduplicate preserving order

    if preferred and preferred.strip():
        return preferred.strip()

    if not hosts:
        return None

    return hosts[0]
