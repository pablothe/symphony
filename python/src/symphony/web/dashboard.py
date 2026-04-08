"""WebSocket endpoint for live dashboard updates.

Replaces Phoenix LiveView with WebSocket push.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from symphony.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

ws_router = APIRouter()

_orchestrator: Orchestrator | None = None
_connected_clients: set[WebSocket] = set()


def set_orchestrator(orchestrator: Orchestrator) -> None:
    """Register the orchestrator for WebSocket updates."""
    global _orchestrator
    _orchestrator = orchestrator


@ws_router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint streaming orchestrator state updates."""
    await websocket.accept()
    _connected_clients.add(websocket)

    try:
        # Send initial state
        if _orchestrator:
            await websocket.send_json(_orchestrator.snapshot())

        # Keep connection alive and push updates
        while True:
            try:
                # Wait for messages from client (keep-alive pings)
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                # Push state update
                if _orchestrator:
                    try:
                        await websocket.send_json(_orchestrator.snapshot())
                    except Exception:
                        break

    except WebSocketDisconnect:
        pass
    finally:
        _connected_clients.discard(websocket)


async def broadcast_update() -> None:
    """Broadcast a state update to all connected WebSocket clients."""
    if not _orchestrator or not _connected_clients:
        return

    snapshot = _orchestrator.snapshot()
    data = json.dumps(snapshot)

    disconnected: set[WebSocket] = set()
    for client in _connected_clients:
        try:
            await client.send_text(data)
        except Exception:
            disconnected.add(client)

    _connected_clients.difference_update(disconnected)
