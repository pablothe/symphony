"""Abstract tracker protocol for issue tracking integrations."""

from __future__ import annotations

from typing import Protocol

from symphony.models.issue import Issue


class TrackerProtocol(Protocol):
    """Interface that all tracker implementations must satisfy."""

    async def fetch_candidate_issues(self) -> list[Issue]:
        """Fetch issues in active states eligible for dispatch."""
        ...

    async def fetch_issues_by_states(self, states: list[str]) -> list[Issue]:
        """Fetch issues in the given states."""
        ...

    async def fetch_issue_states_by_ids(self, ids: list[str]) -> list[Issue]:
        """Fetch current states for specific issue IDs (reconciliation)."""
        ...

    async def create_comment(self, issue_id: str, body: str) -> None:
        """Create a comment on an issue."""
        ...

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        """Update an issue's workflow state."""
        ...
