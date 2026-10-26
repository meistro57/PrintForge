"""Provider-neutral renderer contract.

The publishing pipeline only talks to an :class:`InteriorRenderer`: it hands
over HTML that follows the layout contract (``printforge.layout.styles``), the
generated stylesheet and the exact set of local files the document may load,
and gets back a laid-out document it can measure and serialize. WeasyPrint is
the current implementation (``printforge.render.weasy``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RenderedPage:
    index: int  # 0-based physical page index
    side: str  # "recto" | "verso"
    name: str  # CSS named page ("" for default pages)
    blank: bool  # intentionally blank page inserted by the layout
    anchors: tuple[str, ...]  # element ids located on this page, in document order


@runtime_checkable
class LaidOutDocument(Protocol):
    @property
    def pages(self) -> tuple[RenderedPage, ...]: ...

    def write_pdf(self) -> bytes: ...


@runtime_checkable
class InteriorRenderer(Protocol):
    name: str
    version: str

    def lay_out(self, html: str, css: str, assets: frozenset[Path]) -> LaidOutDocument:
        """Lay out ``html``; only files in ``assets`` may be loaded. Raises RenderError."""
        ...

    def embedded_fonts(self, pdf: bytes) -> list[tuple[str, bool]]:
        """(font name, embedded?) for every font used in ``pdf``."""
        ...
