"""Logging conventions.

All PrintForge output for humans goes to **stderr** through the ``printforge``
logger hierarchy; stdout is reserved for machine-readable command output (e.g.
``inspect --json``). Modules obtain loggers with :func:`get_logger`.
"""

from __future__ import annotations

import logging
import sys

ROOT_LOGGER = "printforge"


def get_logger(name: str) -> logging.Logger:
    """Return a child of the ``printforge`` logger."""
    if name == ROOT_LOGGER or name.startswith(ROOT_LOGGER + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def configure(verbosity: int = 0) -> None:
    """Configure stderr logging. ``verbosity``: -1 quiet, 0 normal, >=1 debug."""
    if verbosity < 0:
        level = logging.WARNING
    elif verbosity == 0:
        level = logging.INFO
    else:
        level = logging.DEBUG
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("printforge: %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
