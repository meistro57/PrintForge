"""Publishing engine: one manuscript in, local print-ready artifacts out."""

from printforge.publish.build import (
    ARTIFACTS,
    DEFAULT_OUTPUT_ROOT,
    BuildResult,
    build_book,
)

__all__ = [
    "ARTIFACTS",
    "DEFAULT_OUTPUT_ROOT",
    "BuildResult",
    "build_book",
]
