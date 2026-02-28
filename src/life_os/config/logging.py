"""structlog configuration for JSON-structured logging.

In development: colourised, human-readable output.
In production (LOG_FORMAT=json): machine-parseable JSON for GCP Cloud Logging.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

import structlog

from life_os.config.settings import settings


def configure_logging() -> None:
    # Configure structlog processors and stdlib logging bridge.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        # Production: JSON output (GCP Cloud Logging compatible)
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: pretty colourised output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler("logs/app.log", maxBytes=5_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG,
        handlers=[console_handler, file_handler],
    )
