"""Terminal status dashboard using Rich.

Displays running agents, token throughput, retry queue, and polling status.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import logging.handlers
import time
from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from symphony.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

# Module-level activity log shared between dashboard and claude_code streaming.
_activity_log: collections.deque[str] = collections.deque(maxlen=20)


def log_activity(message: str) -> None:
    """Append a line to the dashboard activity log."""
    timestamp = time.strftime("%H:%M:%S")
    _activity_log.append(f"[dim]{timestamp}[/dim] {message}")


class StatusDashboard:
    """Terminal UI dashboard showing orchestrator status."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        refresh_interval_s: float = 1.0,
    ):
        self._orchestrator = orchestrator
        self._refresh_interval = refresh_interval_s
        self._console = Console()
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._start_time = time.time()

    async def start(self) -> None:
        """Start the dashboard in the background."""
        self._start_time = time.time()
        self._task = asyncio.create_task(self._render_loop())

    async def stop(self) -> None:
        """Stop the dashboard."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _render_loop(self) -> None:
        """Periodically render the dashboard."""
        # Suppress console log output while dashboard is active to avoid
        # interleaving log lines with the Rich Live display.
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        console_handlers = [
            h for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        for h in console_handlers:
            root_logger.removeHandler(h)

        try:
            with Live(self._build_display(), console=self._console, refresh_per_second=2) as live:
                while True:
                    await asyncio.sleep(self._refresh_interval)
                    live.update(self._build_display())
        except asyncio.CancelledError:
            pass
        finally:
            # Restore handlers on shutdown
            root_logger.handlers = original_handlers

    def _build_display(self) -> Group:
        """Build the dashboard display table."""
        snapshot = self._orchestrator.snapshot()
        uptime = time.time() - self._start_time

        # Main container
        main = Table(title="Symphony Orchestrator", show_header=False, box=None, padding=(0, 1))

        # Status line
        status = Text()
        status.append(f"Uptime: {_format_duration(uptime)}  ", style="dim")
        status.append(f"Running: {snapshot['counts']['running']}  ", style="green")
        status.append(f"Retrying: {snapshot['counts']['retrying']}  ", style="yellow")
        status.append(f"Completed: {snapshot['counts']['completed']}  ", style="blue")
        polling = "checking..." if snapshot["polling"]["checking"] else f"every {snapshot['polling']['poll_interval_ms']}ms"
        status.append(f"Polling: {polling}", style="dim")
        main.add_row(status)
        main.add_row(Text())

        # Token totals
        totals = snapshot["agent_totals"]
        tokens_text = Text()
        tokens_text.append("Tokens: ", style="bold")
        tokens_text.append(f"in={totals['input_tokens']:,}  ", style="cyan")
        tokens_text.append(f"out={totals['output_tokens']:,}  ", style="magenta")
        tokens_text.append(f"total={totals['total_tokens']:,}  ", style="white")
        tokens_text.append(f"runtime={_format_duration(totals['seconds_running'])}", style="dim")
        main.add_row(tokens_text)
        main.add_row(Text())

        # Running issues table
        if snapshot["running"]:
            running_table = Table(title="Running", show_lines=False)
            running_table.add_column("Issue", style="cyan")
            running_table.add_column("State", style="green")
            running_table.add_column("Host", style="dim")
            running_table.add_column("Turns", justify="right")
            running_table.add_column("Tokens", justify="right")
            running_table.add_column("Runtime", justify="right")
            running_table.add_column("Last Event", style="dim")

            for r in snapshot["running"]:
                running_table.add_row(
                    r["identifier"] or "",
                    r["state"] or "",
                    r["worker_host"] or "local",
                    str(r["turn_count"]),
                    f"{r['total_tokens']:,}",
                    _format_duration(r["runtime_seconds"]),
                    r["last_event"] or "",
                )

            main.add_row(running_table)
        else:
            main.add_row(Text("No running agents", style="dim"))

        main.add_row(Text())

        # Retry queue
        if snapshot["retrying"]:
            retry_table = Table(title="Retry Queue", show_lines=False)
            retry_table.add_column("Issue", style="yellow")
            retry_table.add_column("Attempt", justify="right")
            retry_table.add_column("Host", style="dim")
            retry_table.add_column("Error", style="red")

            for r in snapshot["retrying"]:
                retry_table.add_row(
                    r["identifier"] or "",
                    str(r["attempt"]),
                    r["worker_host"] or "local",
                    (r["error"] or "")[:80],
                )

            main.add_row(retry_table)

        # Activity log panel
        if _activity_log:
            log_text = Text.from_markup("\n".join(_activity_log))
            main.add_row(Panel(log_text, title="Agent Activity", border_style="dim"))
        else:
            main.add_row(Panel(Text("Waiting for agent output...", style="dim"), title="Agent Activity", border_style="dim"))

        return Group(main)


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m{seconds % 60:.0f}s"
    hours = seconds / 3600
    remaining = seconds % 3600
    return f"{hours:.0f}h{remaining / 60:.0f}m"
