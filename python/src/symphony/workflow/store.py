"""Hot-reloading workflow file watcher.

Replaces the Elixir WorkflowStore GenServer. Polls WORKFLOW.md for changes
using mtime + file size + content hash, reloading on change while preserving
the last-known-good workflow on failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from symphony.config.config import set_current_workflow
from symphony.workflow.loader import WorkflowDefinition, load

logger = logging.getLogger(__name__)


class WorkflowStore:
    """Async workflow file watcher with hot-reload support."""

    def __init__(self, workflow_path: str | Path, poll_interval_s: float = 1.0):
        self._path = Path(workflow_path)
        self._poll_interval = poll_interval_s
        self._current: WorkflowDefinition | None = None
        self._fingerprint: str | None = None
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]

    @property
    def current(self) -> WorkflowDefinition | None:
        return self._current

    def load_initial(self) -> WorkflowDefinition:
        """Load the workflow synchronously at startup. Raises on failure."""
        workflow = load(self._path)
        self._current = workflow
        self._fingerprint = self._compute_fingerprint()
        set_current_workflow(workflow)
        return workflow

    async def start(self) -> None:
        """Start the background file watcher."""
        if self._current is None:
            self.load_initial()
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop the background file watcher."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def force_reload(self) -> WorkflowDefinition | None:
        """Force an immediate reload. Returns the new workflow or None on failure."""
        try:
            workflow = load(self._path)
            self._current = workflow
            self._fingerprint = self._compute_fingerprint()
            set_current_workflow(workflow)
            logger.info("Workflow reloaded from %s", self._path)
            return workflow
        except Exception:
            logger.exception("Failed to reload workflow from %s, keeping last known good", self._path)
            return None

    async def _watch_loop(self) -> None:
        """Poll for workflow file changes."""
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                new_fingerprint = self._compute_fingerprint()
                if new_fingerprint != self._fingerprint:
                    self.force_reload()
            except Exception:
                logger.exception("Error checking workflow file %s", self._path)

    def _compute_fingerprint(self) -> str | None:
        """Compute a fingerprint from mtime + size + content hash."""
        try:
            stat = self._path.stat()
            content = self._path.read_bytes()
            content_hash = hashlib.sha256(content).hexdigest()[:16]
            return f"{stat.st_mtime}:{stat.st_size}:{content_hash}"
        except OSError:
            return None
