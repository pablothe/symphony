"""Tests for workspace path safety."""

from symphony.workspace.path_safety import (
    sanitize_workspace_key,
    workspace_path_for_issue,
)


def test_sanitize_simple_identifier():
    assert sanitize_workspace_key("TEST-123") == "TEST-123"


def test_sanitize_special_characters():
    assert sanitize_workspace_key("TEST/123") == "TEST_123"
    assert sanitize_workspace_key("TEST 123") == "TEST_123"
    assert sanitize_workspace_key("TEST@#$123") == "TEST___123"


def test_sanitize_preserves_dots_and_dashes():
    assert sanitize_workspace_key("test.issue-1") == "test.issue-1"


def test_workspace_path_construction():
    path = workspace_path_for_issue("/workspaces", "TEST-1")
    assert path == "/workspaces/TEST-1"


def test_workspace_path_with_sanitization():
    path = workspace_path_for_issue("/workspaces", "TEST/1")
    assert path == "/workspaces/TEST_1"
