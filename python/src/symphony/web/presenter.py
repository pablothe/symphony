"""State presentation and serialization for web endpoints."""

from __future__ import annotations

from symphony.orchestrator.orchestrator import Orchestrator


def present_state(orchestrator: Orchestrator) -> dict:  # type: ignore[type-arg]
    """Present the orchestrator state for API responses."""
    return orchestrator.snapshot()
