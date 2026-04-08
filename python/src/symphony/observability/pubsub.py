"""Internal async event bus for observability.

Simple publish-subscribe mechanism replacing Phoenix PubSub.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

Callback = Callable[[], None]


class PubSub:
    """Simple async event bus for dashboard updates."""

    def __init__(self) -> None:
        self._subscribers: list[Callback] = []
        self._async_subscribers: list[Callable[[], object]] = []

    def subscribe(self, callback: Callback) -> None:
        """Add a synchronous subscriber."""
        self._subscribers.append(callback)

    def subscribe_async(self, callback: Callable[[], object]) -> None:
        """Add an async subscriber."""
        self._async_subscribers.append(callback)

    def unsubscribe(self, callback: Callback) -> None:
        """Remove a subscriber."""
        self._subscribers = [s for s in self._subscribers if s is not callback]

    def notify(self) -> None:
        """Notify all subscribers of a state change."""
        for callback in self._subscribers:
            try:
                callback()
            except Exception:
                logger.exception("PubSub subscriber error")

        for callback in self._async_subscribers:
            try:
                asyncio.create_task(callback())  # type: ignore[arg-type]
            except Exception:
                logger.exception("PubSub async subscriber error")


# Global instance
dashboard_pubsub = PubSub()
