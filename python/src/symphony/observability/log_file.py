"""Structured logging configuration.

Sets up structlog with rotating file output and console formatting.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import structlog


def setup_logging(
    logs_root: str | None = None,
    level: int = logging.INFO,
) -> None:
    """Configure structured logging with optional file output.

    Args:
        logs_root: Directory for log files. If None, logs only go to console.
        level: Logging level.
    """
    # Base processors for structlog
    processors: list = [  # type: ignore[type-arg]
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        # Add the wrap processor for structlog
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    # Configure structlog first
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Processors for foreign logs (from stdlib and other libraries)
    foreign_pre_chain = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
        foreign_pre_chain=foreign_pre_chain,
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (if logs_root specified)
    if logs_root:
        log_dir = Path(logs_root)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "symphony.log"

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
        file_handler.setLevel(level)

        # JSON formatter for file output
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=foreign_pre_chain,
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
