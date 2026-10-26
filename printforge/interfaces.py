"""Stage contracts for the PrintForge pipeline (see docs/ARCHITECTURE.md).

The pipeline is a chain of small, swappable stages::

    BookImporter -> (print settings) -> ProviderProfile -> layout -> Renderer

Concrete model types are introduced by the issues that own them (Book in #2,
settings in #3, document in #4, provider constraints in #5, layout in #6,
rendering in #7). Until then these protocols use ``Any`` for payloads; the
*shape* of each contract -- what a stage receives and returns -- is fixed here
so independent work can proceed against it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BookImporter(Protocol):
    """Reads a manuscript source **read-only** and returns a Book model."""

    def load(self, book_dir: Path) -> Any:  # -> printforge.book.Book (#2)
        ...


@runtime_checkable
class ProviderProfile(Protocol):
    """A print-on-demand vendor's rules (trim, margins, page limits, cover)."""

    name: str

    def validate_settings(self, settings: Any) -> Any:  # -> diagnostics (#5)
        ...

    def validate_finished_book(self, page_count: int, dimensions: Any) -> Any:  # (#5)
        ...


@runtime_checkable
class Renderer(Protocol):
    """Turns a laid-out document into a PDF file. Provider-neutral."""

    def render(self, document: Any, layout: Any, output_path: Path) -> Any:  # (#7)
        ...
