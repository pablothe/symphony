"""Linear-specific tracker adapter.

Wraps the LinearClient to implement the TrackerProtocol and adds
mutation support (comments, state transitions).
"""

from __future__ import annotations

import logging

from symphony.models.issue import Issue
from symphony.tracker.linear.client import LinearAPIError, LinearClient

logger = logging.getLogger(__name__)

CREATE_COMMENT_MUTATION = """
mutation SymphonyCreateComment($issueId: String!, $body: String!) {
  commentCreate(input: {issueId: $issueId, body: $body}) {
    success
  }
}
"""

UPDATE_STATE_MUTATION = """
mutation SymphonyUpdateIssueState($issueId: String!, $stateId: String!) {
  issueUpdate(id: $issueId, input: {stateId: $stateId}) {
    success
  }
}
"""

STATE_LOOKUP_QUERY = """
query SymphonyResolveStateId($issueId: String!, $stateName: String!) {
  issue(id: $issueId) {
    team {
      states(filter: {name: {eq: $stateName}}, first: 1) {
        nodes {
          id
        }
      }
    }
  }
}
"""

ATTACH_GITHUB_PR_MUTATION = """
mutation SymphonyAttachGitHubPR($issueId: String!, $url: String!) {
  attachmentLinkGitHubPR(issueId: $issueId, url: $url) {
    success
  }
}
"""

ATTACH_URL_MUTATION = """
mutation SymphonyAttachURL($issueId: String!, $url: String!, $title: String) {
  attachmentLinkURL(issueId: $issueId, url: $url, title: $title) {
    success
  }
}
"""


class LinearAdapter:
    """Linear tracker adapter implementing TrackerProtocol with mutation support."""

    def __init__(self, client: LinearClient | None = None):
        self._client = client or LinearClient()

    @property
    def client(self) -> LinearClient:
        return self._client

    async def fetch_candidate_issues(self) -> list[Issue]:
        return await self._client.fetch_candidate_issues()

    async def fetch_issues_by_states(self, states: list[str]) -> list[Issue]:
        return await self._client.fetch_issues_by_states(states)

    async def fetch_issue_states_by_ids(self, ids: list[str]) -> list[Issue]:
        return await self._client.fetch_issue_states_by_ids(ids)

    async def create_comment(self, issue_id: str, body: str) -> None:
        """Create a comment on an issue.

        Raises LinearAPIError on failure.
        """
        response = await self._client.graphql(
            CREATE_COMMENT_MUTATION,
            {"issueId": issue_id, "body": body},
        )

        data = response.get("data", {})
        success = (data.get("commentCreate") or {}).get("success")
        if not success:
            raise LinearAPIError("Failed to create comment on issue")

    async def update_issue_state(self, issue_id: str, state_name: str) -> None:
        """Update an issue's state by name.

        First resolves the state name to an ID, then updates.
        Raises LinearAPIError on failure.
        """
        state_id = await self._resolve_state_id(issue_id, state_name)

        response = await self._client.graphql(
            UPDATE_STATE_MUTATION,
            {"issueId": issue_id, "stateId": state_id},
        )

        data = response.get("data", {})
        success = (data.get("issueUpdate") or {}).get("success")
        if not success:
            raise LinearAPIError(f"Failed to update issue state to {state_name}")

    async def attach_github_pr(self, issue_id: str, url: str) -> None:
        """Attach a GitHub PR URL to an issue."""
        response = await self._client.graphql(
            ATTACH_GITHUB_PR_MUTATION,
            {"issueId": issue_id, "url": url},
        )

        data = response.get("data", {})
        success = (data.get("attachmentLinkGitHubPR") or {}).get("success")
        if not success:
            raise LinearAPIError("Failed to attach GitHub PR to issue")

    async def attach_url(self, issue_id: str, url: str, title: str | None = None) -> None:
        """Attach a URL to an issue."""
        variables: dict = {"issueId": issue_id, "url": url}  # type: ignore[type-arg]
        if title:
            variables["title"] = title

        response = await self._client.graphql(ATTACH_URL_MUTATION, variables)

        data = response.get("data", {})
        success = (data.get("attachmentLinkURL") or {}).get("success")
        if not success:
            raise LinearAPIError("Failed to attach URL to issue")

    async def _resolve_state_id(self, issue_id: str, state_name: str) -> str:
        """Resolve a state name to its ID for a given issue's team."""
        response = await self._client.graphql(
            STATE_LOOKUP_QUERY,
            {"issueId": issue_id, "stateName": state_name},
        )

        data = response.get("data", {})
        issue_data = data.get("issue", {})
        team = issue_data.get("team", {}) if issue_data else {}
        states = team.get("states", {}) if team else {}
        nodes = states.get("nodes", []) if states else []

        if nodes and isinstance(nodes[0], dict) and "id" in nodes[0]:
            return nodes[0]["id"]

        raise LinearAPIError(f"State '{state_name}' not found for issue {issue_id}")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
