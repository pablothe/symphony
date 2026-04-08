"""In-memory tracker for testing."""

from __future__ import annotations

from symphony.models.issue import Issue


class MemoryTracker:
    """In-memory tracker that returns preconfigured issues. For tests only."""

    def __init__(self, issues: list[Issue] | None = None):
        self._issues = list(issues or [])

    def set_issues(self, issues: list[Issue]) -> None:
        self._issues = list(issues)

    def add_issue(self, issue: Issue) -> None:
        self._issues.append(issue)

    def update_issue_state(self, issue_id: str, new_state: str) -> None:
        for issue in self._issues:
            if issue.id == issue_id:
                issue.state = new_state
                break

    async def fetch_candidate_issues(self) -> list[Issue]:
        return list(self._issues)

    async def fetch_issues_by_states(self, states: list[str]) -> list[Issue]:
        normalized = {s.lower() for s in states}
        return [i for i in self._issues if i.state and i.state.lower() in normalized]

    async def fetch_issue_states_by_ids(self, ids: list[str]) -> list[Issue]:
        id_set = set(ids)
        return [i for i in self._issues if i.id in id_set]
