"""Tests for orchestrator lifecycle commenting on Linear issues."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from symphony.models.issue import Issue
from symphony.orchestrator.orchestrator import Orchestrator
from symphony.tracker.memory import MemoryTracker


@pytest.fixture
def tracker() -> MemoryTracker:
    return MemoryTracker(issues=[
        Issue(id="issue-1", identifier="TEST-1", title="Test issue", state="Todo", priority=1),
    ])


@pytest.fixture
def orchestrator(tracker: MemoryTracker) -> Orchestrator:
    return Orchestrator(tracker=tracker)


class TestStartComment:
    """Tests for comments posted when an agent starts working."""

    @pytest.mark.asyncio
    async def test_start_updates_state_and_posts_comment(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        issue = tracker._issues[0]

        with patch("symphony.agent.runner.run", new_callable=AsyncMock):
            await orchestrator._run_agent_task(issue, worker_host=None)

        # Should have moved to In Progress
        assert tracker._issues[0].state == "In Progress"

        # Should have posted a start comment
        assert len(tracker._comments) >= 1
        start_comment = tracker._comments[0]
        assert start_comment[0] == "issue-1"
        assert "started working" in start_comment[1]


class TestCompletionComment:
    """Tests for comments posted when an agent completes."""

    @pytest.mark.asyncio
    async def test_success_posts_completion_comment(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        issue = tracker._issues[0]

        with patch("symphony.agent.runner.run", new_callable=AsyncMock):
            await orchestrator._run_agent_task(issue, worker_host=None)

        # Start comment should exist
        assert any("started working" in c[1] for c in tracker._comments)

        # Now simulate task completion
        done_task = AsyncMock()
        done_task.result.return_value = None  # success

        # Set up running entry
        from symphony.models.state import RunningEntry
        from datetime import datetime, timezone

        orchestrator._state.running["issue-1"] = RunningEntry(
            issue_id="issue-1",
            identifier="TEST-1",
            started_at=datetime.now(timezone.utc),
        )
        orchestrator._tasks["issue-1"] = done_task

        await orchestrator._on_task_done("issue-1", done_task)

        assert any("completed work" in c[1] for c in tracker._comments)

    @pytest.mark.asyncio
    async def test_error_posts_error_comment(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        done_task = AsyncMock()
        done_task.result.side_effect = RuntimeError("something broke")

        from symphony.models.state import RunningEntry
        from datetime import datetime, timezone

        orchestrator._state.running["issue-1"] = RunningEntry(
            issue_id="issue-1",
            identifier="TEST-1",
            started_at=datetime.now(timezone.utc),
        )
        orchestrator._tasks["issue-1"] = done_task

        await orchestrator._on_task_done("issue-1", done_task)

        assert any("encountered an error" in c[1] for c in tracker._comments)
        assert any("something broke" in c[1] for c in tracker._comments)


class TestCommentFailureResilience:
    """Tests that comment/state failures don't crash the agent run."""

    @pytest.mark.asyncio
    async def test_comment_failure_does_not_crash_agent(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        issue = tracker._issues[0]

        # Make create_comment raise
        original_create = tracker.create_comment

        async def failing_comment(issue_id: str, body: str) -> None:
            raise RuntimeError("Linear API unavailable")

        tracker.create_comment = failing_comment  # type: ignore[assignment]

        with patch("symphony.agent.runner.run", new_callable=AsyncMock):
            # Should not raise despite comment failure
            await orchestrator._run_agent_task(issue, worker_host=None)

        # State should still have been updated (separate call)
        assert tracker._issues[0].state == "In Progress"

    @pytest.mark.asyncio
    async def test_state_update_failure_does_not_crash_agent(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        issue = tracker._issues[0]

        async def failing_state(issue_id: str, state_name: str) -> None:
            raise RuntimeError("Linear API unavailable")

        tracker.update_issue_state = failing_state  # type: ignore[assignment]

        with patch("symphony.agent.runner.run", new_callable=AsyncMock):
            # Should not raise despite state update failure
            await orchestrator._run_agent_task(issue, worker_host=None)

        # Comment should still have been posted
        assert len(tracker._comments) >= 1


class TestProgressComment:
    """Tests for progress comments posted during agent execution."""

    @pytest.mark.asyncio
    async def test_progress_comment_on_turn_update(
        self, orchestrator: Orchestrator, tracker: MemoryTracker,
    ) -> None:
        from symphony.models.state import RunningEntry

        orchestrator._state.running["issue-1"] = RunningEntry(
            issue_id="issue-1",
            identifier="TEST-1",
            turn_count=0,
        )

        # Simulate a turn_number update
        orchestrator._handle_agent_update("issue-1", {"turn_number": 1})

        # Give the async task a chance to run
        await asyncio.sleep(0.05)

        assert any("completed turn 1" in c[1] for c in tracker._comments)
