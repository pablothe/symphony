"""Tests for retry delay calculation."""

from symphony.orchestrator.retry import retry_delay_ms


def test_continuation_retry():
    """Continuation retries use a fixed 1s delay."""
    assert retry_delay_ms(1, 300_000, is_continuation=True) == 1_000
    assert retry_delay_ms(5, 300_000, is_continuation=True) == 1_000


def test_first_failure_retry():
    """First failure retry uses the base delay."""
    assert retry_delay_ms(1, 300_000) == 10_000


def test_exponential_backoff():
    """Retries use exponential backoff."""
    assert retry_delay_ms(1, 300_000) == 10_000      # 10s * 2^0
    assert retry_delay_ms(2, 300_000) == 20_000      # 10s * 2^1
    assert retry_delay_ms(3, 300_000) == 40_000      # 10s * 2^2
    assert retry_delay_ms(4, 300_000) == 80_000      # 10s * 2^3


def test_backoff_capped_at_max():
    """Backoff should be capped at max_backoff_ms."""
    assert retry_delay_ms(10, 300_000) == 300_000
    assert retry_delay_ms(20, 300_000) == 300_000


def test_exponent_capped_at_10():
    """Exponent should be capped at 10 to prevent overflow."""
    delay_at_11 = retry_delay_ms(11, 10_000_000)
    delay_at_12 = retry_delay_ms(12, 10_000_000)
    assert delay_at_11 == delay_at_12  # Both capped at 2^10
