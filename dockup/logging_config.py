"""Structured JSON logging configuration using structlog."""
from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "info", fmt: str = "json") -> None:
    """Configure structlog for JSON or console output."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if fmt == "console":
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for libraries
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    for noisy in ["uvicorn.access", "docker", "urllib3", "botocore"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "dockup") -> structlog.BoundLogger:
    return structlog.get_logger(name)
