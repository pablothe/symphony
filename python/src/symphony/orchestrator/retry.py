"""Retry scheduling with exponential backoff.

Ports the Elixir orchestrator's retry logic.
"""

from __future__ import annotations

import time

CONTINUATION_RETRY_DELAY_MS = 1_000
FAILURE_RETRY_BASE_MS = 10_000


def retry_delay_ms(
    attempt: int,
    max_backoff_ms: int,
    is_continuation: bool = False,
) -> int:
    """Calculate the retry delay in milliseconds.

    Continuation retries (issue still active after normal turn completion)
    use a short fixed delay. Failure retries use exponential backoff:
    base * 2^(min(attempt-1, 10)), capped at max_backoff_ms.
    """
    if is_continuation:
        return CONTINUATION_RETRY_DELAY_MS

    exponent = min(attempt - 1, 10)
    delay = FAILURE_RETRY_BASE_MS * (1 << exponent)
    return min(delay, max_backoff_ms)


def due_at_mono(delay_ms: int) -> float:
    """Calculate the monotonic due-at time for a retry."""
    return time.monotonic() + (delay_ms / 1000)
