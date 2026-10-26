"""Stage contracts for the PrintForge pipeline (see docs/ARCHITECTURE.md).

The pipeline is a chain of small, swappable stages::

    BookImporter -> (print settings) -> ProviderProfile -> layout -> Renderer

Concrete model types are introduced by the issues that own them (Book in #2,
settings in #3, document in #4, provider constraints in #5, layout in #6,
rendering in #7). Until then a protocol may use ``Any`` for payloads; the
*shape* of each contract -- what a stage receives and returns -- is fixed here
so independent work can proceed against it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

# The provider contract lives with the providers (issue #5); re-exported here.
from printforge.providers.base import ProviderProfile

if TYPE_CHECKING:
    from printforge.book import Book

__all__ = ["BookImporter", "ProviderProfile", "Renderer"]


@runtime_checkable
class BookImporter(Protocol):
    """Reads a manuscript source **read-only** and returns a Book model."""

    def load(self, book_dir: Path) -> Book: ...


@runtime_checkable
class Renderer(Protocol):
    """Turns a laid-out document into a PDF file. Provider-neutral."""

    def render(self, document: Any, layout: Any, output_path: Path) -> Any:  # (#7)
        ...
