"""CLI entry point and application startup.

Replaces the Elixir CLI module and Application supervisor.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from symphony.config.config import settings, validate
from symphony.observability.log_file import setup_logging
from symphony.observability.status_dashboard import StatusDashboard
from symphony.orchestrator.orchestrator import Orchestrator
from symphony.tracker.linear.adapter import LinearAdapter
from symphony.tracker.memory import MemoryTracker
from symphony.web.server import start_server
from symphony.workflow.store import WorkflowStore

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="symphony",
        description="Symphony: Autonomous work orchestration using Claude Code",
    )
    parser.add_argument(
        "workflow",
        nargs="?",
        default="WORKFLOW.md",
        help="Path to WORKFLOW.md file (default: ./WORKFLOW.md)",
    )
    parser.add_argument(
        "--logs-root",
        default=None,
        help="Directory for log files (default: console only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP server port (overrides config)",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the terminal status dashboard",
    )
    return parser.parse_args(argv)


async def run_app(args: argparse.Namespace) -> None:
    """Main application coroutine."""
    # 1. Load workflow
    workflow_path = Path(args.workflow).resolve()
    store = WorkflowStore(workflow_path)

    try:
        store.load_initial()
    except Exception as e:
        logger.error("Failed to load workflow: %s", e)
        sys.exit(1)

    # 2. Validate config
    try:
        validate()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    config = settings()

    # 3. Create tracker
    if config.tracker.kind == "memory":
        tracker = MemoryTracker()
    else:
        tracker = LinearAdapter()  # type: ignore[assignment]

    # 4. Create orchestrator
    orchestrator = Orchestrator(tracker=tracker)

    # 5. Set up shutdown handling
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int) -> None:
        logger.info("Received signal %s, shutting down", signal.Signals(sig).name)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    # 6. Start components
    tasks: list[asyncio.Task] = []  # type: ignore[type-arg]

    # Workflow store (hot-reload watcher)
    await store.start()

    # Orchestrator
    orchestrator_task = asyncio.create_task(orchestrator.run(), name="orchestrator")
    tasks.append(orchestrator_task)

    # HTTP server (optional)
    port = args.port or config.server.port
    if port is not None:
        server_task = asyncio.create_task(
            start_server(orchestrator, host=config.server.host, port=port),
            name="http-server",
        )
        tasks.append(server_task)

    # Terminal dashboard (optional)
    dashboard: StatusDashboard | None = None
    if not args.no_dashboard and config.observability.dashboard_enabled:
        dashboard = StatusDashboard(
            orchestrator,
            refresh_interval_s=config.observability.refresh_ms / 1000,
        )
        await dashboard.start()

    logger.info(
        "Symphony started workflow=%s tracker=%s",
        workflow_path,
        config.tracker.kind,
    )

    # 7. Wait for shutdown
    await shutdown_event.wait()

    # 8. Graceful shutdown
    logger.info("Shutting down...")

    if dashboard:
        await dashboard.stop()

    await orchestrator.stop()
    await store.stop()

    # Cancel remaining tasks
    for task in tasks:
        if not task.done():
            task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Close tracker client if applicable
    if hasattr(tracker, "close"):
        await tracker.close()  # type: ignore[union-attr]

    logger.info("Symphony shutdown complete")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = parse_args(argv)

    # Set up logging
    setup_logging(logs_root=args.logs_root)

    # Run the application
    try:
        asyncio.run(run_app(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
