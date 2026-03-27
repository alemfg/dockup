"""Shared structured logger for all v2 modules."""
from __future__ import annotations
import logging, sys
from typing import Optional

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)-35s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False

def setup_logging(level: str = "INFO") -> None:
    global _initialized
    if _initialized:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root = logging.getLogger()
    root.setLevel(numeric)
    root.handlers.clear()
    root.addHandler(handler)
    _initialized = True

def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
