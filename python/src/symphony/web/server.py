"""FastAPI application and server startup.

Replaces the Phoenix HTTP server and endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from symphony.web.api import router as api_router
from symphony.web.api import set_orchestrator as set_api_orchestrator
from symphony.web.dashboard import set_orchestrator as set_ws_orchestrator
from symphony.web.dashboard import ws_router

if TYPE_CHECKING:
    from symphony.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def create_app(orchestrator: Orchestrator) -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Symphony Orchestrator",
        description="Autonomous work orchestration service",
        version="0.1.0",
    )

    # Register orchestrator with API and WebSocket handlers
    set_api_orchestrator(orchestrator)
    set_ws_orchestrator(orchestrator)

    # Include routers
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/")
    async def root() -> dict:  # type: ignore[type-arg]
        return {
            "service": "symphony",
            "status": "running",
            "api": "/api/v1/state",
            "dashboard": "/ws/dashboard",
        }

    return app


async def start_server(
    orchestrator: Orchestrator,
    host: str = "127.0.0.1",
    port: int = 4000,
) -> None:
    """Start the HTTP server in the background."""
    app = create_app(orchestrator)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    logger.info("Starting HTTP server on %s:%d", host, port)
    await server.serve()
