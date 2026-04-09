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
    # Base processors that don't require a logger instance
    base_processors: list = [  # type: ignore[type-arg]
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Processors for structlog's internal use (including filter_by_level)
    structlog_processors: list = [  # type: ignore[type-arg]
        structlog.stdlib.filter_by_level,
    ] + base_processors

    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    handlers.append(console_handler)

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
        handlers.append(file_handler)

        # JSON formatter for file output
        processors_for_file = structlog_processors + [
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors_for_file = structlog_processors

    # Configure structlog
    structlog.configure(
        processors=processors_for_file + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in handlers:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer()
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.handlers.RotatingFileHandler)
            else structlog.processors.JSONRenderer(),
            foreign_pre_chain=base_processors,
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
