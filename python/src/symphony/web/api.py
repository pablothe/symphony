"""REST API endpoints for observability.

Replaces the Elixir ObservabilityApiController.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

if TYPE_CHECKING:
    from symphony.orchestrator.orchestrator import Orchestrator

router = APIRouter(prefix="/api/v1")

# Set by server startup
_orchestrator: Orchestrator | None = None


def set_orchestrator(orchestrator: Orchestrator) -> None:
    """Register the orchestrator instance for API access."""
    global _orchestrator
    _orchestrator = orchestrator


def _get_orchestrator() -> Orchestrator:
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return _orchestrator


@router.get("/state")
async def get_state() -> dict:  # type: ignore[type-arg]
    """Get the full orchestrator state snapshot."""
    return _get_orchestrator().snapshot()


@router.get("/issues/{identifier}")
async def get_issue(identifier: str) -> dict:  # type: ignore[type-arg]
    """Get details for a specific issue by identifier."""
    orch = _get_orchestrator()
    snapshot = orch.snapshot()

    # Search in running
    for entry in snapshot["running"]:
        if entry["identifier"] == identifier:
            return {
                "identifier": identifier,
                "status": "running",
                **entry,
            }

    # Search in retrying
    for entry in snapshot["retrying"]:
        if entry["identifier"] == identifier:
            return {
                "identifier": identifier,
                "status": "retrying",
                **entry,
            }

    raise HTTPException(status_code=404, detail=f"Issue {identifier} not found")


@router.post("/refresh")
async def trigger_refresh() -> dict:  # type: ignore[type-arg]
    """Trigger an immediate poll cycle."""
    orch = _get_orchestrator()
    await orch.trigger_poll()
    return {"queued": True}
