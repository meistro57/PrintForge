"""Facts the renderer reports to later stages (table of contents, cover, preflight).

Kept separate from :mod:`printforge.render.interior` so front-matter generation
can consume these types without importing the PDF builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from printforge.diagnostics import Diagnostic
from printforge.providers.base import PageSize
from printforge.units import Length

#: Page label in the book's own sequence: lower roman before the main matter,
#: decimal from the page where numbering restarts. Part dividers and display
#: pages print no folio but still occupy a number in that sequence.
Folio = str


@dataclass(frozen=True, slots=True)
class HeadingLocation:
    """Where a chapter title, part or Markdown heading landed in the PDF."""

    id: str
    text: str
    level: int  # HTML level: 1 for parts/chapters, 2-6 for body headings
    kind: str  # "part", "front-matter", "chapter", "appendix", "back-matter"
    unit: bool  # True for part/chapter titles, False for Markdown headings
    page: int  # 1-based physical page number
    folio: str  # page label in the book's sequence ("iv", "12")


@dataclass(frozen=True, slots=True)
class TocEntry:
    """One line of the printed table of contents."""

    id: str  # anchor of the target
    text: str
    level: int  # 1 = part/chapter, 2 = "##", 3 = "###"
    folio: str  # page label of the target
    kind: str = ""  # "part" entries are styled differently


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Facts about a finished interior PDF, for downstream stages."""

    path: Path
    page_count: int
    size: PageSize
    inside_margin: Length  # gutter the pages were laid out with
    headings: tuple[HeadingLocation, ...]
    toc: tuple[TocEntry, ...]
    fonts: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    sha256: str


__all__ = ["Folio", "HeadingLocation", "RenderResult", "TocEntry"]
