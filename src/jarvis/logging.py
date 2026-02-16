"""Logging configuration with structlog for JSON output in production."""

import logging
import sys

import structlog


def configure_logging(level: str, json_output: bool | None = None) -> None:
    """Configure logging with structlog.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        json_output: Force JSON output. If None, auto-detect (JSON in prod).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if json_output is None:
        import os
        json_output = os.environ.get("APP_ENV", "dev") == "prod"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


def bind_context(**kwargs: object) -> None:
    """Bind key-value pairs to the structlog context for the current execution."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all structlog context variables."""
    structlog.contextvars.clear_contextvars()
