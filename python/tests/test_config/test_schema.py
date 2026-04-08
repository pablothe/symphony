"""Tests for config schema parsing and validation."""

import os

import pytest

from symphony.config.schema import (
    ClaudeCodeConfig,
    SymphonyConfig,
    parse_config,
    normalize_issue_state,
)


def test_parse_empty_config():
    """Empty config should use all defaults."""
    config = parse_config({})
    assert config.polling.interval_ms == 30_000
    assert config.agent.max_concurrent_agents == 10
    assert config.agent.max_turns == 20
    assert config.claude_code.command == "claude"
    assert config.claude_code.permission_mode == "accept-all"


def test_parse_full_config():
    """Full config should parse all fields."""
    config = parse_config({
        "tracker": {
            "kind": "linear",
            "project_slug": "my-project",
            "active_states": ["Todo"],
            "terminal_states": ["Done"],
        },
        "polling": {"interval_ms": 5000},
        "agent": {"max_concurrent_agents": 5, "max_turns": 10},
        "claude_code": {
            "command": "claude",
            "model": "claude-sonnet-4-20250514",
            "max_turns": 8,
            "permission_mode": "accept-all",
        },
    })

    assert config.tracker.kind == "linear"
    assert config.tracker.project_slug == "my-project"
    assert config.polling.interval_ms == 5000
    assert config.agent.max_concurrent_agents == 5
    assert config.claude_code.model == "claude-sonnet-4-20250514"
    assert config.claude_code.max_turns == 8


def test_invalid_polling_interval():
    """Negative polling interval should fail validation."""
    with pytest.raises(ValueError):
        parse_config({"polling": {"interval_ms": -1}})


def test_normalize_issue_state():
    assert normalize_issue_state("Todo") == "todo"
    assert normalize_issue_state("IN PROGRESS") == "in progress"
    assert normalize_issue_state("done") == "done"


def test_state_limits_normalization():
    config = parse_config({
        "agent": {
            "max_concurrent_agents_by_state": {
                "Todo": 3,
                "In Progress": 5,
            }
        }
    })
    limits = config.agent.max_concurrent_agents_by_state
    assert "todo" in limits
    assert limits["todo"] == 3
    assert "in progress" in limits
    assert limits["in progress"] == 5


def test_env_var_resolution(monkeypatch):
    """$VAR references should resolve from environment."""
    monkeypatch.setenv("LINEAR_API_KEY", "test-key-123")
    config = parse_config({
        "tracker": {"api_key": "$LINEAR_API_KEY"}
    })
    assert config.tracker.api_key == "test-key-123"


def test_none_values_use_defaults():
    """None values in config should fall back to defaults."""
    config = parse_config({
        "polling": {"interval_ms": None},
        "agent": None,
    })
    assert config.polling.interval_ms == 30_000
    assert config.agent.max_concurrent_agents == 10


def test_claude_code_defaults():
    """Claude Code config should have sensible defaults."""
    config = ClaudeCodeConfig()
    assert config.command == "claude"
    assert config.model is None
    assert config.permission_mode == "accept-all"
    assert config.turn_timeout_ms == 3_600_000
    assert config.stall_timeout_ms == 300_000
    assert config.allowed_tools == []
