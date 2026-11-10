"""Provider-neutral full-wrap cover geometry.

All dimensions come from the resolved settings and the provider profile, never
from hardcoded vendor numbers: the trim, the mandatory cover bleed, the spine
formula and the text/barcode clearances are read through
:class:`~printforge.providers.base.ProviderProfile`.

Coordinates are inches from the **top-left corner of the full cover**, the same
origin CSS uses. The spine is measured from the *final* interior page count, so a
cover is always derived from the book it will wrap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from printforge.config.settings import PrintSettings
from printforge.errors import ConfigError
from printforge.providers.base import CoverRules, ProviderProfile
from printforge.units import ZERO, Length

COVER_SPEC_VERSION = 1


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned rectangle on the full cover, in inches from the top-left."""

    x: Length
    y: Length
    width: Length
    height: Length

    def inset(self, by: Length) -> Box:
        return Box(
            self.x + by,
            self.y + by,
            self.width - by * 2,
            self.height - by * 2,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "x": self.x.to_str("in"),
            "y": self.y.to_str("in"),
            "width": self.width.to_str("in"),
            "height": self.height.to_str("in"),
        }


@dataclass(frozen=True, slots=True)
class CoverGeometry:
    """Everything needed to draw and describe one full-wrap cover."""

    page_count: int
    trim: tuple[Length, Length]  # width, height
    bleed: Length
    spine: Length
    width: Length
    height: Length
    back: Box  # back cover trim area
    spine_area: Box  # spine trim area
    front: Box  # front cover trim area
    back_safe: Box  # text-safe area inside the back trim
    front_safe: Box
    spine_safe: Box  # between the spine clearances
    barcode: Box  # reserved for the retailer's barcode; never drawn
    folds: tuple[Length, Length]  # x of the back/spine and spine/front folds
    rules: CoverRules
    spine_text_allowed: bool

    @property
    def size(self) -> tuple[Length, Length]:
        return self.width, self.height

    def to_spec(self, settings: PrintSettings, provider: ProviderProfile) -> dict[str, Any]:
        """Machine-readable template specification (deterministic, no paths)."""
        return {
            "schema_version": COVER_SPEC_VERSION,
            "provider": provider.name,
            "trim": {"width": self.trim[0].to_str("in"), "height": self.trim[1].to_str("in")},
            "bleed": self.bleed.to_str("in"),
            "spine": {
                "width": self.spine.to_str("in"),
                "page_count": self.page_count,
            },
            "full_cover": {
                "width": self.width.to_str("in"),
                "height": self.height.to_str("in"),
            },
            "fold_lines": [fold.to_str("in") for fold in self.folds],
            "areas": {
                "back": self.back.to_dict(),
                "spine": self.spine_area.to_dict(),
                "front": self.front.to_dict(),
            },
            "safe_areas": {
                "back": self.back_safe.to_dict(),
                "front": self.front_safe.to_dict(),
                "spine_text": self.spine_safe.to_dict(),
            },
            "barcode_reserve": self.barcode.to_dict(),
            "spine_text": {
                "allowed": self.spine_text_allowed,
                "min_pages": self.rules.spine_text_min_pages,
                "clearance": self.rules.spine_text_clearance.to_str("in"),
                "mode": str(settings.cover.spine_text),
            },
            "interior": {
                "page_count": self.page_count,
                "paper": str(settings.interior.paper),
                "ink": str(settings.interior.ink),
            },
            "cover": {
                "finish": str(settings.cover.finish),
                "background_color": settings.cover.background_color,
                "text_color": settings.cover.text_color,
            },
            "sources": [source.to_dict() for source in provider.sources],
        }


def cover_geometry(
    settings: PrintSettings, provider: ProviderProfile, page_count: int
) -> CoverGeometry:
    """Compute the full-wrap cover for ``page_count`` interior pages."""
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
        raise ConfigError(
            f"cover page count must be a positive integer, got {page_count!r}",
            hint="derive it from the finished interior PDF",
        )

    rules = provider.cover_rules()
    spine = provider.spine_width(page_count, settings.interior.ink, settings.interior.paper)
    trim_width, trim_height = settings.trim.width, settings.trim.height
    bleed = rules.bleed
    width = bleed * 2 + trim_width * 2 + spine
    height = bleed * 2 + trim_height

    back = Box(bleed, bleed, trim_width, trim_height)
    spine_area = Box(bleed + trim_width, bleed, spine, trim_height)
    front = Box(bleed + trim_width + spine, bleed, trim_width, trim_height)
    clearance = rules.spine_text_clearance

    return CoverGeometry(
        page_count=page_count,
        trim=(trim_width, trim_height),
        bleed=bleed,
        spine=spine,
        width=width,
        height=height,
        back=back,
        spine_area=spine_area,
        front=front,
        back_safe=back.inset(rules.text_safe_margin),
        front_safe=front.inset(rules.text_safe_margin),
        spine_safe=Box(
            spine_area.x + clearance,
            spine_area.y + rules.text_safe_margin,
            _at_least_zero(spine_area.width - clearance * 2),
            _at_least_zero(spine_area.height - rules.text_safe_margin * 2),
        ),
        barcode=Box(
            back.x + back.width - rules.barcode_inset - rules.barcode_width,
            back.y + back.height - rules.barcode_inset - rules.barcode_height,
            rules.barcode_width,
            rules.barcode_height,
        ),
        folds=(bleed + trim_width, bleed + trim_width + spine),
        rules=rules,
        spine_text_allowed=provider.spine_text_allowed(page_count),
    )


def _at_least_zero(length: Length) -> Length:
    return length if length > ZERO else ZERO


__all__ = ["COVER_SPEC_VERSION", "Box", "CoverGeometry", "cover_geometry"]
