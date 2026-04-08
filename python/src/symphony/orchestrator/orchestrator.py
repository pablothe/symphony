"""Main orchestrator: async polling loop, dispatch, and state machine.

Ports the Elixir Orchestrator GenServer to Python asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from symphony.agent import runner as agent_runner
from symphony.config.config import settings
from symphony.config.schema import normalize_issue_state
from symphony.models.issue import Issue
from symphony.models.state import (
    AgentTotals,
    OrchestratorState,
    RetryEntry,
    RunningEntry,
)
from symphony.orchestrator.dispatch import (
    is_terminal_state,
    select_worker_host,
    should_dispatch_issue,
    sort_issues_for_dispatch,
)
from symphony.orchestrator.reconciliation import (
    find_stalled_issues,
    reconcile_running_issues,
)
from symphony.orchestrator.retry import due_at_mono, retry_delay_ms
from symphony.tracker.base import TrackerProtocol
from symphony.workspace import manager as workspace_mgr

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestrator managing the polling loop, dispatch, and agent lifecycle."""

    def __init__(
        self,
        tracker: TrackerProtocol,
        on_state_change: asyncio.Event | None = None,
    ):
        self._tracker = tracker
        self._state = OrchestratorState()
        self._lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self._on_state_change = on_state_change or asyncio.Event()
        self._tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]

    @property
    def state(self) -> OrchestratorState:
        """Current orchestrator state (read-only snapshot)."""
        return self._state

    async def run(self) -> None:
        """Main polling loop. Runs until shutdown is signaled."""
        config = settings()
        self._state.poll_interval_ms = config.polling.interval_ms
        self._state.max_concurrent_agents = config.agent.max_concurrent_agents

        # Initial workspace cleanup for terminal issues
        await self._terminal_workspace_cleanup()

        logger.info(
            "Orchestrator started poll_interval=%dms max_concurrent=%d",
            self._state.poll_interval_ms,
            self._state.max_concurrent_agents,
        )

        while not self._shutdown.is_set():
            try:
                async with self._lock:
                    self._refresh_runtime_config()
                    await self._poll_and_dispatch()

                self._notify_state_change()

                # Wait for next poll cycle
                await self._wait_poll_interval()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in orchestrator poll cycle")
                await asyncio.sleep(5.0)  # backoff on error

        # Shutdown: cancel all running tasks
        await self._shutdown_all_tasks()

    async def stop(self) -> None:
        """Signal the orchestrator to shut down."""
        logger.info("Orchestrator shutdown requested")
        self._shutdown.set()

    async def trigger_poll(self) -> None:
        """Trigger an immediate poll cycle."""
        async with self._lock:
            await self._poll_and_dispatch()
        self._notify_state_change()

    def snapshot(self) -> dict:  # type: ignore[type-arg]
        """Return a serializable snapshot of the current state."""
        state = self._state
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "running": state.running_count,
                "retrying": state.retrying_count,
                "completed": len(state.completed),
            },
            "running": [
                {
                    "issue_id": e.issue_id,
                    "identifier": e.identifier,
                    "state": e.issue_state,
                    "worker_host": e.worker_host,
                    "workspace_path": e.workspace_path,
                    "session_id": e.session_id,
                    "turn_count": e.turn_count,
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "total_tokens": e.total_tokens,
                    "started_at": e.started_at.isoformat() if e.started_at else None,
                    "last_event": e.last_event,
                    "last_message": e.last_message,
                    "runtime_seconds": (
                        (time.time() - e.started_at.timestamp()) if e.started_at else 0
                    ),
                }
                for e in state.running.values()
            ],
            "retrying": [
                {
                    "issue_id": e.issue_id,
                    "identifier": e.identifier,
                    "attempt": e.attempt,
                    "error": e.error,
                    "worker_host": e.worker_host,
                }
                for e in state.retry_attempts.values()
            ],
            "agent_totals": {
                "input_tokens": state.agent_totals.input_tokens,
                "output_tokens": state.agent_totals.output_tokens,
                "total_tokens": state.agent_totals.total_tokens,
                "seconds_running": state.agent_totals.seconds_running,
            },
            "rate_limits": state.rate_limits,
            "polling": {
                "checking": state.poll_check_in_progress,
                "poll_interval_ms": state.poll_interval_ms,
            },
        }

    # --- Internal methods ---

    def _refresh_runtime_config(self) -> None:
        """Refresh config from the current workflow (hot-reload support)."""
        try:
            config = settings()
            self._state.poll_interval_ms = config.polling.interval_ms
            self._state.max_concurrent_agents = config.agent.max_concurrent_agents
        except Exception:
            logger.warning("Failed to refresh config, keeping current values")

    async def _poll_and_dispatch(self) -> None:
        """Execute one poll + dispatch cycle."""
        self._state.poll_check_in_progress = True
        config = settings()

        try:
            # 1. Reconcile running issues
            issues_to_stop = await reconcile_running_issues(
                self._state,
                self._tracker,
                config.tracker.active_states,
                config.tracker.terminal_states,
            )
            for issue_id in issues_to_stop:
                await self._stop_running_issue(issue_id, reason="state_changed")

            # 2. Check for stalled issues
            stalled = find_stalled_issues(
                self._state,
                config.claude_code.stall_timeout_ms,
                time.monotonic(),
            )
            for issue_id in stalled:
                await self._stop_running_issue(issue_id, reason="stalled")
                # Schedule retry for stalled issues
                entry = self._state.running.get(issue_id)
                if entry:
                    self._schedule_retry(issue_id, entry.identifier, attempt=1, error="stalled")

            # 3. Fetch candidate issues
            try:
                candidates = await self._tracker.fetch_candidate_issues()
            except Exception as e:
                logger.error("Failed to fetch candidate issues: %s", e)
                candidates = []

            # 4. Sort and dispatch
            sorted_candidates = sort_issues_for_dispatch(candidates)
            dispatched = 0

            for issue in sorted_candidates:
                if self._state.available_slots() <= 0:
                    break

                if not should_dispatch_issue(
                    issue,
                    self._state,
                    config.tracker.active_states,
                    config.tracker.terminal_states,
                ):
                    continue

                try:
                    await self._dispatch_issue(issue, config)
                    dispatched += 1
                except Exception:
                    logger.exception("Failed to dispatch issue %s", issue.identifier)

            if dispatched > 0:
                logger.info("Dispatched %d issues", dispatched)

        finally:
            self._state.poll_check_in_progress = False

    async def _dispatch_issue(self, issue: Issue, config: object) -> None:  # type: ignore[type-arg]
        """Dispatch a single issue to an agent task."""
        cfg = settings()

        # Select worker host
        worker_host: str | None = None
        if cfg.worker.ssh_hosts:
            try:
                worker_host = select_worker_host(
                    self._state,
                    cfg.worker.ssh_hosts,
                    cfg.worker.max_concurrent_agents_per_host,
                )
            except ValueError:
                logger.warning("No worker capacity for %s", issue.identifier)
                return

        # Claim the issue
        self._state.claimed.add(issue.id)  # type: ignore[arg-type]

        # Create running entry
        entry = RunningEntry(
            issue_id=issue.id or "",
            identifier=issue.identifier or "",
            issue_state=issue.state,
            worker_host=worker_host,
            started_at=datetime.now(timezone.utc),
        )
        self._state.running[issue.id or ""] = entry

        # Spawn agent task
        task = asyncio.create_task(
            self._run_agent_task(issue, worker_host),
            name=f"agent-{issue.identifier}",
        )
        entry.task = task
        self._tasks[issue.id or ""] = task

        # Set up completion callback
        task.add_done_callback(
            lambda t, iid=issue.id: asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.create_task, self._on_task_done(iid or "", t)
            )
        )

        logger.info(
            "Dispatched issue %s worker_host=%s",
            issue.identifier,
            worker_host or "local",
        )

    async def _run_agent_task(
        self, issue: Issue, worker_host: str | None
    ) -> None:
        """Agent task coroutine that runs in the background."""

        def on_update(update: dict) -> None:  # type: ignore[type-arg]
            """Handle agent updates (called from agent runner)."""
            if not issue.id:
                return
            asyncio.get_event_loop().call_soon_threadsafe(
                self._handle_agent_update, issue.id, update
            )

        def on_runtime_info(issue_id: str, info: dict) -> None:  # type: ignore[type-arg]
            """Handle runtime info (workspace path, worker host)."""
            entry = self._state.running.get(issue_id)
            if entry:
                entry.workspace_path = info.get("workspace_path")
                entry.worker_host = info.get("worker_host")

        await agent_runner.run(
            issue=issue,
            tracker=self._tracker,
            on_update=on_update,
            on_runtime_info=on_runtime_info,
            worker_host=worker_host,
        )

    def _handle_agent_update(self, issue_id: str, update: dict) -> None:  # type: ignore[type-arg]
        """Process an update from a running agent."""
        entry = self._state.running.get(issue_id)
        if entry is None:
            return

        event = update.get("event", "")
        entry.last_event = event
        entry.last_timestamp = datetime.now(timezone.utc)
        entry.last_message = str(update)[:500]

        # Update token counts
        if "input_tokens" in update:
            delta_input = update["input_tokens"] - entry.last_reported_input_tokens
            delta_output = update["output_tokens"] - entry.last_reported_output_tokens
            delta_total = update["total_tokens"] - entry.last_reported_total_tokens

            entry.input_tokens += max(0, delta_input)
            entry.output_tokens += max(0, delta_output)
            entry.total_tokens += max(0, delta_total)

            entry.last_reported_input_tokens = update["input_tokens"]
            entry.last_reported_output_tokens = update["output_tokens"]
            entry.last_reported_total_tokens = update["total_tokens"]

            self._state.agent_totals.input_tokens += max(0, delta_input)
            self._state.agent_totals.output_tokens += max(0, delta_output)
            self._state.agent_totals.total_tokens += max(0, delta_total)

        if "session_id" in update:
            entry.session_id = update["session_id"]
        if "turn_number" in update:
            entry.turn_count = update["turn_number"]

        self._notify_state_change()

    async def _on_task_done(self, issue_id: str, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        """Handle agent task completion (normal or error)."""
        async with self._lock:
            entry = self._state.running.pop(issue_id, None)
            self._tasks.pop(issue_id, None)

            if entry is None:
                return

            # Track runtime
            if entry.started_at:
                runtime = time.time() - entry.started_at.timestamp()
                self._state.agent_totals.seconds_running += runtime

            self._state.completed.add(issue_id)
            self._state.claimed.discard(issue_id)

            # Check for errors
            error: str | None = None
            try:
                task.result()
            except asyncio.CancelledError:
                logger.info("Agent task cancelled for %s", entry.identifier)
                return
            except Exception as e:
                error = str(e)
                logger.error("Agent task failed for %s: %s", entry.identifier, error)

            if error:
                # Schedule retry with backoff
                attempt = 1
                # Check if there was a previous retry
                if issue_id in self._state.retry_attempts:
                    attempt = self._state.retry_attempts[issue_id].attempt + 1

                self._schedule_retry(issue_id, entry.identifier, attempt, error)
            else:
                logger.info("Agent task completed for %s", entry.identifier)

        self._notify_state_change()

    def _schedule_retry(
        self, issue_id: str, identifier: str, attempt: int, error: str | None = None,
        is_continuation: bool = False,
    ) -> None:
        """Schedule a retry for an issue with exponential backoff."""
        config = settings()
        delay_ms = retry_delay_ms(
            attempt,
            config.agent.max_retry_backoff_ms,
            is_continuation=is_continuation,
        )
        due = due_at_mono(delay_ms)

        logger.info(
            "Scheduling retry for %s attempt=%d delay=%dms",
            identifier, attempt, delay_ms,
        )

        loop = asyncio.get_event_loop()
        timer = loop.call_later(
            delay_ms / 1000,
            lambda: asyncio.create_task(self._execute_retry(issue_id)),
        )

        self._state.retry_attempts[issue_id] = RetryEntry(
            issue_id=issue_id,
            identifier=identifier,
            attempt=attempt,
            due_at_mono=due,
            timer_handle=timer,
            error=error,
        )

    async def _execute_retry(self, issue_id: str) -> None:
        """Execute a scheduled retry."""
        async with self._lock:
            retry_entry = self._state.retry_attempts.pop(issue_id, None)
            if retry_entry is None:
                return

            self._state.claimed.discard(issue_id)

            logger.info(
                "Executing retry for %s attempt=%d",
                retry_entry.identifier, retry_entry.attempt,
            )

        # The issue will be picked up in the next poll cycle
        self._notify_state_change()

    async def _stop_running_issue(self, issue_id: str, reason: str = "") -> None:
        """Stop a running agent task."""
        entry = self._state.running.get(issue_id)
        if entry is None:
            return

        logger.info(
            "Stopping issue %s reason=%s", entry.identifier, reason,
        )

        task = self._tasks.get(issue_id)
        if task and not task.done():
            task.cancel()

    async def _terminal_workspace_cleanup(self) -> None:
        """Clean up workspaces for issues in terminal states on startup."""
        config = settings()
        try:
            terminal_issues = await self._tracker.fetch_issues_by_states(
                config.tracker.terminal_states
            )
            for issue in terminal_issues:
                if issue.identifier:
                    try:
                        await workspace_mgr.remove_issue_workspaces(issue.identifier)
                    except Exception:
                        logger.exception(
                            "Failed to clean workspace for terminal issue %s",
                            issue.identifier,
                        )
        except Exception:
            logger.exception("Failed terminal workspace cleanup")

    async def _shutdown_all_tasks(self) -> None:
        """Cancel all running agent tasks for shutdown."""
        logger.info("Shutting down %d running tasks", len(self._tasks))

        for task in self._tasks.values():
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        self._tasks.clear()
        self._state.running.clear()
        self._state.claimed.clear()

    async def _wait_poll_interval(self) -> None:
        """Wait for the next poll interval or until shutdown."""
        try:
            await asyncio.wait_for(
                self._shutdown.wait(),
                timeout=self._state.poll_interval_ms / 1000,
            )
        except asyncio.TimeoutError:
            pass

    def _notify_state_change(self) -> None:
        """Notify observers of a state change."""
        self._on_state_change.set()
        self._on_state_change.clear()
