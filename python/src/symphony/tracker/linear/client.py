"""Linear GraphQL client for polling candidate issues.

Ports the Elixir Linear.Client module with the same GraphQL queries.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from symphony.config.config import settings
from symphony.models.issue import BlockerRef, Issue

logger = logging.getLogger(__name__)

ISSUE_PAGE_SIZE = 50
MAX_ERROR_BODY_LOG_BYTES = 1000

POLL_QUERY = """
query SymphonyLinearPoll($projectSlug: String!, $stateNames: [String!]!, $first: Int!, $relationFirst: Int!, $after: String) {
  issues(filter: {project: {slugId: {eq: $projectSlug}}, state: {name: {in: $stateNames}}}, first: $first, after: $after) {
    nodes {
      id
      identifier
      title
      description
      priority
      state {
        name
      }
      branchName
      url
      assignee {
        id
      }
      labels {
        nodes {
          name
        }
      }
      inverseRelations(first: $relationFirst) {
        nodes {
          type
          issue {
            id
            identifier
            state {
              name
            }
          }
        }
      }
      createdAt
      updatedAt
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

QUERY_BY_IDS = """
query SymphonyLinearIssuesById($ids: [ID!]!, $first: Int!, $relationFirst: Int!) {
  issues(filter: {id: {in: $ids}}, first: $first) {
    nodes {
      id
      identifier
      title
      description
      priority
      state {
        name
      }
      branchName
      url
      assignee {
        id
      }
      labels {
        nodes {
          name
        }
      }
      inverseRelations(first: $relationFirst) {
        nodes {
          type
          issue {
            id
            identifier
            state {
              name
            }
          }
        }
      }
      createdAt
      updatedAt
    }
  }
}
"""

VIEWER_QUERY = """
query SymphonyLinearViewer {
  viewer {
    id
  }
}
"""


class LinearClient:
    """Async GraphQL client for the Linear API."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def graphql(
        self,
        query: str,
        variables: dict | None = None,  # type: ignore[type-arg]
        operation_name: str | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Execute a GraphQL query against the Linear API.

        Raises LinearAPIError on failure.
        """
        config = settings()
        api_key = config.tracker.api_key
        endpoint = config.tracker.endpoint

        if not api_key:
            raise LinearAPIError("Missing LINEAR_API_KEY")

        payload: dict = {"query": query, "variables": variables or {}}  # type: ignore[type-arg]
        if operation_name:
            payload["operationName"] = operation_name

        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

        client = await self._get_client()
        response = await client.post(endpoint, json=payload, headers=headers)

        if response.status_code != 200:
            body_preview = response.text[:MAX_ERROR_BODY_LOG_BYTES]
            logger.error(
                "Linear GraphQL request failed status=%d body=%s",
                response.status_code,
                body_preview,
            )
            raise LinearAPIError(
                f"Linear API returned status {response.status_code}",
                status_code=response.status_code,
            )

        return response.json()

    async def fetch_candidate_issues(self) -> list[Issue]:
        """Fetch issues in active states for the configured project."""
        config = settings()
        tracker = config.tracker

        if not tracker.api_key:
            raise LinearAPIError("Missing LINEAR_API_KEY")
        if not tracker.project_slug:
            raise LinearAPIError("Missing tracker.project_slug")

        assignee_filter = await self._routing_assignee_filter()
        return await self._fetch_by_states(
            tracker.project_slug, tracker.active_states, assignee_filter
        )

    async def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        """Fetch issues in the given states."""
        if not state_names:
            return []

        config = settings()
        tracker = config.tracker

        if not tracker.api_key:
            raise LinearAPIError("Missing LINEAR_API_KEY")
        if not tracker.project_slug:
            raise LinearAPIError("Missing tracker.project_slug")

        return await self._fetch_by_states(tracker.project_slug, state_names, None)

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> list[Issue]:
        """Fetch current states for specific issue IDs."""
        if not issue_ids:
            return []

        ids = list(dict.fromkeys(issue_ids))  # deduplicate preserving order
        assignee_filter = await self._routing_assignee_filter()
        order_index = {id_: idx for idx, id_ in enumerate(ids)}

        all_issues: list[Issue] = []

        # Batch in pages of ISSUE_PAGE_SIZE
        for i in range(0, len(ids), ISSUE_PAGE_SIZE):
            batch = ids[i : i + ISSUE_PAGE_SIZE]
            body = await self.graphql(
                QUERY_BY_IDS,
                {
                    "ids": batch,
                    "first": len(batch),
                    "relationFirst": ISSUE_PAGE_SIZE,
                },
            )
            issues = _decode_linear_response(body, assignee_filter)
            all_issues.extend(issues)

        # Sort by requested order
        fallback = len(order_index)
        all_issues.sort(key=lambda i: order_index.get(i.id or "", fallback))
        return all_issues

    async def _fetch_by_states(
        self,
        project_slug: str,
        state_names: list[str],
        assignee_filter: _AssigneeFilter | None,
    ) -> list[Issue]:
        """Fetch issues by states with pagination."""
        all_issues: list[Issue] = []
        after_cursor: str | None = None

        while True:
            body = await self.graphql(
                POLL_QUERY,
                {
                    "projectSlug": project_slug,
                    "stateNames": state_names,
                    "first": ISSUE_PAGE_SIZE,
                    "relationFirst": ISSUE_PAGE_SIZE,
                    "after": after_cursor,
                },
            )

            issues, page_info = _decode_linear_page_response(body, assignee_filter)
            all_issues.extend(issues)

            if page_info.get("has_next_page") and page_info.get("end_cursor"):
                after_cursor = page_info["end_cursor"]
            else:
                break

        return all_issues

    async def _routing_assignee_filter(self) -> _AssigneeFilter | None:
        """Build the assignee filter from config."""
        config = settings()
        assignee = config.tracker.assignee

        if not assignee:
            return None

        normalized = assignee.strip()
        if not normalized:
            return None

        if normalized == "me":
            return await self._resolve_viewer_assignee_filter()

        return _AssigneeFilter(match_values={normalized})

    async def _resolve_viewer_assignee_filter(self) -> _AssigneeFilter:
        """Resolve 'me' to the authenticated user's ID."""
        body = await self.graphql(VIEWER_QUERY, {})
        viewer = (body.get("data") or {}).get("viewer")

        if not viewer or not viewer.get("id"):
            raise LinearAPIError("Could not resolve Linear viewer identity")

        return _AssigneeFilter(match_values={viewer["id"].strip()})

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class _AssigneeFilter:
    """Filter for matching issues by assignee."""

    def __init__(self, match_values: set[str]):
        self.match_values = match_values


class LinearAPIError(Exception):
    """Error from the Linear API."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _decode_linear_response(
    body: dict,  # type: ignore[type-arg]
    assignee_filter: _AssigneeFilter | None,
) -> list[Issue]:
    """Decode a Linear GraphQL response into Issue objects."""
    if "errors" in body:
        raise LinearAPIError(f"Linear GraphQL errors: {body['errors']}")

    data = body.get("data", {})
    issues_data = data.get("issues", {})
    nodes = issues_data.get("nodes", [])

    issues: list[Issue] = []
    for node in nodes:
        issue = _normalize_issue(node, assignee_filter)
        if issue is not None:
            issues.append(issue)

    return issues


def _decode_linear_page_response(
    body: dict,  # type: ignore[type-arg]
    assignee_filter: _AssigneeFilter | None,
) -> tuple[list[Issue], dict]:  # type: ignore[type-arg]
    """Decode a paginated Linear response into issues + page info."""
    issues = _decode_linear_response(body, assignee_filter)

    data = body.get("data", {})
    issues_data = data.get("issues", {})
    page_info_raw = issues_data.get("pageInfo", {})

    page_info = {
        "has_next_page": page_info_raw.get("hasNextPage", False),
        "end_cursor": page_info_raw.get("endCursor"),
    }

    return issues, page_info


def _normalize_issue(
    node: dict,  # type: ignore[type-arg]
    assignee_filter: _AssigneeFilter | None,
) -> Issue | None:
    """Normalize a Linear API issue node into an Issue dataclass."""
    if not isinstance(node, dict):
        return None

    assignee = node.get("assignee")
    assignee_id = assignee.get("id") if isinstance(assignee, dict) else None

    return Issue(
        id=node.get("id"),
        identifier=node.get("identifier"),
        title=node.get("title"),
        description=node.get("description"),
        priority=node.get("priority") if isinstance(node.get("priority"), int) else None,
        state=_nested_get(node, "state", "name"),
        branch_name=node.get("branchName"),
        url=node.get("url"),
        assignee_id=assignee_id,
        labels=_extract_labels(node),
        blocked_by=_extract_blockers(node),
        assigned_to_worker=_assigned_to_worker(assignee, assignee_filter),
        created_at=_parse_datetime(node.get("createdAt")),
        updated_at=_parse_datetime(node.get("updatedAt")),
    )


def _assigned_to_worker(
    assignee: dict | None,  # type: ignore[type-arg]
    assignee_filter: _AssigneeFilter | None,
) -> bool:
    """Check if the issue's assignee matches the routing filter."""
    if assignee_filter is None:
        return True

    if not isinstance(assignee, dict):
        return False

    aid = assignee.get("id")
    if not aid or not isinstance(aid, str):
        return False

    return aid.strip() in assignee_filter.match_values


def _extract_labels(node: dict) -> list[str]:  # type: ignore[type-arg]
    """Extract normalized label names from an issue node."""
    labels_data = node.get("labels", {})
    if not isinstance(labels_data, dict):
        return []

    nodes = labels_data.get("nodes", [])
    return [
        n["name"].lower()
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("name"), str)
    ]


def _extract_blockers(node: dict) -> list[BlockerRef]:  # type: ignore[type-arg]
    """Extract blocker references from inverse relations."""
    relations_data = node.get("inverseRelations", {})
    if not isinstance(relations_data, dict):
        return []

    nodes = relations_data.get("nodes", [])
    blockers: list[BlockerRef] = []

    for rel in nodes:
        if not isinstance(rel, dict):
            continue

        relation_type = rel.get("type", "")
        if not isinstance(relation_type, str) or relation_type.strip().lower() != "blocks":
            continue

        blocker_issue = rel.get("issue")
        if not isinstance(blocker_issue, dict):
            continue

        blockers.append(
            BlockerRef(
                id=blocker_issue.get("id"),
                identifier=blocker_issue.get("identifier"),
                state=_nested_get(blocker_issue, "state", "name"),
            )
        )

    return blockers


def _nested_get(data: dict, *keys: str) -> str | None:  # type: ignore[type-arg]
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)  # type: ignore[assignment]
    return current if isinstance(current, str) else None


def _parse_datetime(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string."""
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
