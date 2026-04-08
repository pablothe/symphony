"""Tests for dispatch logic."""

import pytest

from symphony.models.issue import BlockerRef, Issue
from symphony.models.state import OrchestratorState, RunningEntry
from symphony.orchestrator.dispatch import (
    is_active_state,
    is_blocked_by_non_terminal,
    is_terminal_state,
    should_dispatch_issue,
    sort_issues_for_dispatch,
)


ACTIVE_STATES = ["Todo", "In Progress"]
TERMINAL_STATES = ["Done", "Closed"]


def test_sort_by_priority():
    issues = [
        Issue(id="3", identifier="C", priority=3),
        Issue(id="1", identifier="A", priority=1),
        Issue(id="2", identifier="B", priority=2),
    ]
    sorted_issues = sort_issues_for_dispatch(issues)
    assert [i.identifier for i in sorted_issues] == ["A", "B", "C"]


def test_sort_none_priority_last():
    issues = [
        Issue(id="1", identifier="A", priority=None),
        Issue(id="2", identifier="B", priority=1),
    ]
    sorted_issues = sort_issues_for_dispatch(issues)
    assert sorted_issues[0].identifier == "B"
    assert sorted_issues[1].identifier == "A"


def test_is_active_state():
    assert is_active_state("Todo", ACTIVE_STATES)
    assert is_active_state("todo", ACTIVE_STATES)
    assert is_active_state("In Progress", ACTIVE_STATES)
    assert not is_active_state("Done", ACTIVE_STATES)


def test_is_terminal_state():
    assert is_terminal_state("Done", TERMINAL_STATES)
    assert is_terminal_state("done", TERMINAL_STATES)
    assert not is_terminal_state("Todo", TERMINAL_STATES)


def test_should_dispatch_eligible_issue():
    state = OrchestratorState(max_concurrent_agents=5)
    issue = Issue(id="1", identifier="T-1", state="Todo", assigned_to_worker=True)
    assert should_dispatch_issue(issue, state, ACTIVE_STATES, TERMINAL_STATES)


def test_should_not_dispatch_terminal_issue():
    state = OrchestratorState(max_concurrent_agents=5)
    issue = Issue(id="1", identifier="T-1", state="Done", assigned_to_worker=True)
    assert not should_dispatch_issue(issue, state, ACTIVE_STATES, TERMINAL_STATES)


def test_should_not_dispatch_claimed_issue():
    state = OrchestratorState(max_concurrent_agents=5)
    state.claimed.add("1")
    issue = Issue(id="1", identifier="T-1", state="Todo", assigned_to_worker=True)
    assert not should_dispatch_issue(issue, state, ACTIVE_STATES, TERMINAL_STATES)


def test_should_not_dispatch_when_no_slots():
    state = OrchestratorState(max_concurrent_agents=1)
    state.running["other"] = RunningEntry(issue_id="other", identifier="T-0")
    issue = Issue(id="1", identifier="T-1", state="Todo", assigned_to_worker=True)
    assert not should_dispatch_issue(issue, state, ACTIVE_STATES, TERMINAL_STATES)


def test_should_not_dispatch_unassigned():
    state = OrchestratorState(max_concurrent_agents=5)
    issue = Issue(id="1", identifier="T-1", state="Todo", assigned_to_worker=False)
    assert not should_dispatch_issue(issue, state, ACTIVE_STATES, TERMINAL_STATES)


def test_blocked_by_non_terminal():
    issue = Issue(
        id="1", identifier="T-1", state="Todo",
        blocked_by=[BlockerRef(id="2", identifier="T-2", state="In Progress")],
    )
    assert is_blocked_by_non_terminal(issue, TERMINAL_STATES)


def test_not_blocked_by_terminal():
    issue = Issue(
        id="1", identifier="T-1", state="Todo",
        blocked_by=[BlockerRef(id="2", identifier="T-2", state="Done")],
    )
    assert not is_blocked_by_non_terminal(issue, TERMINAL_STATES)


def test_blocking_only_applies_to_todo():
    issue = Issue(
        id="1", identifier="T-1", state="In Progress",
        blocked_by=[BlockerRef(id="2", identifier="T-2", state="In Progress")],
    )
    assert not is_blocked_by_non_terminal(issue, TERMINAL_STATES)
