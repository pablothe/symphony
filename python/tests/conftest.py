"""Shared test fixtures for Symphony tests."""

from __future__ import annotations

import pytest

from symphony.models.issue import Issue
from symphony.tracker.memory import MemoryTracker
from symphony.workflow.loader import WorkflowDefinition
from symphony.config.config import set_current_workflow


@pytest.fixture
def sample_issue() -> Issue:
    """A sample issue for testing."""
    return Issue(
        id="issue-001",
        identifier="TEST-1",
        title="Fix the widget",
        description="The widget is broken. Please fix it.",
        priority=1,
        state="Todo",
        url="https://linear.app/team/issue/TEST-1",
        labels=["bug"],
    )


@pytest.fixture
def sample_issues() -> list[Issue]:
    """Multiple sample issues for dispatch testing."""
    return [
        Issue(id="issue-001", identifier="TEST-1", title="First issue", state="Todo", priority=1),
        Issue(id="issue-002", identifier="TEST-2", title="Second issue", state="In Progress", priority=2),
        Issue(id="issue-003", identifier="TEST-3", title="Third issue", state="Todo", priority=1),
        Issue(id="issue-004", identifier="TEST-4", title="Done issue", state="Done", priority=1),
    ]


@pytest.fixture
def memory_tracker(sample_issues: list[Issue]) -> MemoryTracker:
    """In-memory tracker pre-loaded with sample issues."""
    return MemoryTracker(issues=sample_issues)


@pytest.fixture
def sample_workflow() -> WorkflowDefinition:
    """A minimal workflow definition for testing."""
    return WorkflowDefinition(
        config={
            "tracker": {
                "kind": "memory",
                "active_states": ["Todo", "In Progress"],
                "terminal_states": ["Done", "Closed"],
            },
            "polling": {"interval_ms": 1000},
            "workspace": {"root": "/tmp/symphony-test-workspaces"},
            "agent": {"max_concurrent_agents": 2, "max_turns": 3},
            "claude_code": {"command": "echo", "permission_mode": "accept-all"},
        },
        prompt_template="Work on {{ issue.identifier }}: {{ issue.title }}",
    )


@pytest.fixture(autouse=True)
def setup_workflow(sample_workflow: WorkflowDefinition) -> None:
    """Auto-set the workflow for all tests."""
    set_current_workflow(sample_workflow)
