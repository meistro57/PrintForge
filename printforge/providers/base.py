"""Provider profile contract.

A provider encodes one print-on-demand vendor's rules: supported formats, page
geometry, margin minimums, page-count limits and cover/spine maths. Everything
is expressed with :class:`~printforge.units.Length` (explicit units) and every
rule cites the vendor documentation it was taken from.

Core modules (importer, document, layout, renderer) never import a concrete
provider; they receive a :class:`ProviderProfile` from the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from printforge.config.settings import Ink, Paper, PrintSettings
from printforge.diagnostics import Diagnostics
from printforge.units import Length


@dataclass(frozen=True, slots=True)
class RuleSource:
    """Where a provider rule came from, and when it was last verified."""

    title: str
    url: str
    checked: str  # ISO date the source was last read

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "checked": self.checked}


@dataclass(frozen=True, slots=True)
class PageSize:
    width: Length
    height: Length

    def to_dict(self) -> dict[str, str]:
        return {"width": self.width.to_str("in"), "height": self.height.to_str("in")}


@dataclass(frozen=True, slots=True)
class PageCountRange:
    minimum: int
    maximum: int

    def __contains__(self, count: object) -> bool:
        return isinstance(count, int) and self.minimum <= count <= self.maximum


@dataclass(frozen=True, slots=True)
class CoverRules:
    bleed: Length  # mandatory cover bleed on top, bottom and outside edges
    text_safe_margin: Length  # front/back text distance inside the trim line
    spine_text_clearance: Length  # text distance from each spine edge/fold
    spine_text_min_pages: int  # spine text only for books with >= this many pages
    barcode_width: Length
    barcode_height: Length
    barcode_inset: Length  # PrintForge placement policy from the back-cover trim/spine
    min_image_dpi: int


@runtime_checkable
class ProviderProfile(Protocol):
    name: str
    display_name: str
    sources: tuple[RuleSource, ...]

    def default_settings(self) -> dict[str, Any]:
        """Provider defaults layer for settings resolution (#3)."""
        ...

    def validate_settings(self, settings: PrintSettings) -> Diagnostics:
        """ERROR for unsupported/invalid requests, WARNING for risky ones."""
        ...

    def interior_page_size(self, settings: PrintSettings) -> PageSize: ...

    def page_count_range(self, settings: PrintSettings) -> PageCountRange: ...

    def min_inside_margin(self, page_count: int) -> Length: ...

    def min_outside_margin(self, settings: PrintSettings) -> Length: ...

    def spine_width(self, page_count: int, ink: Ink, paper: Paper) -> Length: ...

    def spine_text_allowed(self, page_count: int) -> bool: ...

    def cover_rules(self) -> CoverRules: ...

    def validate_finished_book(
        self,
        page_count: int,
        dimensions: PageSize,
        *,
        settings: PrintSettings,
        inside_margin: Length | None = None,
    ) -> Diagnostics:
        """Check constraints that depend on the *final* rendered interior."""
        ...
