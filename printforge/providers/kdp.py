"""Amazon KDP paperback provider profile.

Every number below is taken from the official KDP help pages listed in
:data:`SOURCES` (last checked 2026-10-26). KDP changes its requirements from time
to time: re-verify against the sources before relying on a value and update
``checked`` when you do.

Implemented scope (everything else is rejected with a clear error):
paperback, 6 x 9 in trim, black ink, white or cream paper, no interior bleed.
The bleed page geometry and other ink/paper tables are encoded so the rules are
complete and testable, but those modes are not yet supported by the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from printforge.config.settings import Format, Ink, Paper, PrintSettings
from printforge.diagnostics import Diagnostics, Severity
from printforge.providers.base import CoverRules, PageCountRange, PageSize, RuleSource
from printforge.units import Length

CHECKED = "2026-10-26"

SOURCE_INTERIOR = RuleSource(
    "KDP Help: Paperback trim size, bleed, margins and page count (G201857950)",
    "https://kdp.amazon.com/en_US/help/topic/G201857950",
    CHECKED,
)
SOURCE_COVER = RuleSource(
    "KDP Help: Create a Paperback Cover (G201953020)",
    "https://kdp.amazon.com/en_US/help/topic/G201953020",
    CHECKED,
)
SOURCE_BARCODE = RuleSource(
    "KDP Help: barcode reserve, 2 x 1.2 in white box, lower right of back cover (GGE5T76TWKA85DJM)",
    "https://kdp.amazon.com/help/topic/GGE5T76TWKA85DJM",
    CHECKED,
)
SOURCES = (SOURCE_INTERIOR, SOURCE_COVER, SOURCE_BARCODE)

IN = Length.inches

# --- interior (G201857950) -------------------------------------------------------

#: Interior bleed: 0.125 in beyond trim on top, bottom and outer edge, i.e. the PDF
#: page is 0.125 in wider and 0.25 in taller than the trim.
INTERIOR_BLEED = IN("0.125")

#: Page-count ranges for the 6 x 9 in trim by (ink, paper).
PAGE_LIMITS_6X9: dict[tuple[Ink, Paper], PageCountRange] = {
    (Ink.BLACK, Paper.WHITE): PageCountRange(24, 828),
    (Ink.BLACK, Paper.CREAM): PageCountRange(24, 776),
    (Ink.BLACK, Paper.GROUNDWOOD): PageCountRange(24, 812),
    (Ink.STANDARD_COLOR, Paper.WHITE): PageCountRange(72, 600),
    (Ink.PREMIUM_COLOR, Paper.WHITE): PageCountRange(24, 828),
}

#: Minimum inside (gutter) margin by final page count: (first page, last page, gutter).
GUTTER_TABLE: tuple[tuple[int, int, Length], ...] = (
    (24, 150, IN("0.375")),
    (151, 300, IN("0.5")),
    (301, 500, IN("0.625")),
    (501, 700, IN("0.75")),
    (701, 828, IN("0.875")),
)

#: Minimum outside margins (top, bottom and outside edge).
OUTSIDE_MARGIN_NO_BLEED = IN("0.25")
OUTSIDE_MARGIN_BLEED = IN("0.375")

MIN_IMAGE_DPI = 300
RECOMMENDED_MAX_IMAGE_DPI = 600

# --- cover (G201953020) ------------------------------------------------------------

COVER_BLEED = IN("0.125")
COVER_TEXT_SAFE_MARGIN = IN("0.125")
SPINE_TEXT_CLEARANCE = IN("0.0625")
#: G201857950 says spine text needs "more than 79 pages"; G201953020 says "at least 79
#: pages". PrintForge uses the stricter reading (>= 80 pages), which satisfies both.
SPINE_TEXT_MIN_PAGES = 80

#: Spine width per page, in inches, by (ink, paper).
SPINE_PER_PAGE: dict[tuple[Ink, Paper], Length] = {
    (Ink.BLACK, Paper.WHITE): IN("0.002252"),
    (Ink.BLACK, Paper.CREAM): IN("0.0025"),
    (Ink.STANDARD_COLOR, Paper.WHITE): IN("0.002252"),
    (Ink.PREMIUM_COLOR, Paper.WHITE): IN("0.002347"),
}

BARCODE_WIDTH = IN("2")
BARCODE_HEIGHT = IN("1.2")
#: Not specified for paperbacks by KDP; PrintForge policy keeps the reserved box
#: 0.25 in from the back-cover trim edges and the spine fold (KDP's hardcover page
#: asks for 0.25 in from the spine hinge).
BARCODE_INSET = IN("0.25")

# --- implemented scope ------------------------------------------------------------------

SUPPORTED_TRIMS = {(IN("6"), IN("9"))}
SUPPORTED_INKS = {Ink.BLACK}
SUPPORTED_PAPERS = {Paper.WHITE, Paper.CREAM}


@dataclass(frozen=True, slots=True)
class KdpPaperback:
    name: str = "kdp"
    display_name: str = "Amazon KDP paperback"
    sources: tuple[RuleSource, ...] = SOURCES

    # ------------------------------------------------------------------ settings
    def default_settings(self) -> dict[str, Any]:
        return {
            "format": "paperback",
            "trim": {"width": "6in", "height": "9in"},
            "interior": {"bleed": False, "ink": "black", "paper": "white"},
        }

    def validate_settings(self, settings: PrintSettings) -> Diagnostics:
        diags = Diagnostics()
        trim = (settings.trim.width, settings.trim.height)
        interior = settings.interior

        def unsupported(rule: str, message: str, suggestion: str) -> None:
            diags.add(
                Severity.ERROR, rule, message, context="print settings", suggestion=suggestion
            )

        if settings.format is not Format.PAPERBACK:
            unsupported("KDP-FORMAT", f"format {settings.format} is not supported", "use paperback")
        if trim not in SUPPORTED_TRIMS:
            unsupported(
                "KDP-TRIM-UNSUPPORTED",
                f"trim {settings.trim.width} x {settings.trim.height} is not implemented yet",
                "use trim 6in x 9in",
            )
        if interior.ink not in SUPPORTED_INKS:
            unsupported(
                "KDP-INK-UNSUPPORTED",
                f"interior ink {interior.ink!s} is not implemented yet",
                "use ink 'black'",
            )
        if (interior.ink, interior.paper) not in PAGE_LIMITS_6X9:
            unsupported(
                "KDP-PAPER-INVALID",
                f"KDP does not offer {interior.paper!s} paper with {interior.ink!s} ink",
                "use white paper",
            )
        elif interior.paper not in SUPPORTED_PAPERS:
            unsupported(
                "KDP-PAPER-UNSUPPORTED",
                f"{interior.paper!s} paper is not implemented yet",
                "use 'white' or 'cream' paper",
            )
        if interior.bleed:
            unsupported(
                "KDP-BLEED-UNSUPPORTED",
                "interior bleed is not implemented yet (cover bleed is always applied)",
                "set interior.bleed to false",
            )

        minimum = self.min_outside_margin(settings)
        for side in ("top", "bottom", "outside"):
            value = getattr(settings.margins, side)
            if value < minimum:
                diags.add(
                    Severity.ERROR,
                    "KDP-MARGIN-OUTSIDE",
                    f"margins.{side} {value} is below KDP's minimum {minimum}",
                    context="print settings",
                    suggestion=f"set margins.{side} to at least {minimum}",
                )
        inside = settings.margins.inside
        if inside is not None and inside < GUTTER_TABLE[0][2]:
            diags.add(
                Severity.ERROR,
                "KDP-MARGIN-INSIDE",
                f"margins.inside {inside} is below KDP's smallest gutter {GUTTER_TABLE[0][2]}",
                context="print settings",
                suggestion="use 'auto' to follow KDP's page-count gutter table",
            )
        if settings.images.min_dpi < MIN_IMAGE_DPI:
            diags.add(
                Severity.WARNING,
                "KDP-IMAGE-DPI-SETTING",
                f"images.min_dpi {settings.images.min_dpi} is below KDP's minimum {MIN_IMAGE_DPI}",
                context="print settings",
                suggestion=f"set images.min_dpi to {MIN_IMAGE_DPI}",
            )
        return diags

    # ------------------------------------------------------------------ geometry
    def interior_page_size(self, settings: PrintSettings) -> PageSize:
        if settings.interior.bleed:
            return PageSize(
                settings.trim.width + INTERIOR_BLEED, settings.trim.height + INTERIOR_BLEED * 2
            )
        return PageSize(settings.trim.width, settings.trim.height)

    def page_count_range(self, settings: PrintSettings) -> PageCountRange:
        key = (settings.interior.ink, settings.interior.paper)
        if key not in PAGE_LIMITS_6X9:
            raise ValueError(f"no KDP page limits for {key}")
        return PAGE_LIMITS_6X9[key]

    def min_inside_margin(self, page_count: int) -> Length:
        """Minimum gutter for the final page count. Raises ``ValueError`` outside 24-828."""
        for first, last, gutter in GUTTER_TABLE:
            if first <= page_count <= last:
                return gutter
        raise ValueError(f"page count {page_count} is outside KDP's gutter table (24-828)")

    def min_outside_margin(self, settings: PrintSettings) -> Length:
        return OUTSIDE_MARGIN_BLEED if settings.interior.bleed else OUTSIDE_MARGIN_NO_BLEED

    def spine_width(self, page_count: int, ink: Ink, paper: Paper) -> Length:
        key = (ink, paper)
        if key not in SPINE_PER_PAGE:
            raise ValueError(f"no KDP spine formula for {ink} ink on {paper} paper")
        return SPINE_PER_PAGE[key] * page_count

    def spine_text_allowed(self, page_count: int) -> bool:
        return page_count >= SPINE_TEXT_MIN_PAGES

    def cover_rules(self) -> CoverRules:
        return CoverRules(
            bleed=COVER_BLEED,
            text_safe_margin=COVER_TEXT_SAFE_MARGIN,
            spine_text_clearance=SPINE_TEXT_CLEARANCE,
            spine_text_min_pages=SPINE_TEXT_MIN_PAGES,
            barcode_width=BARCODE_WIDTH,
            barcode_height=BARCODE_HEIGHT,
            barcode_inset=BARCODE_INSET,
            min_image_dpi=MIN_IMAGE_DPI,
        )

    # ------------------------------------------------------------------ finished book
    def validate_finished_book(
        self,
        page_count: int,
        dimensions: PageSize,
        *,
        settings: PrintSettings,
        inside_margin: Length | None = None,
    ) -> Diagnostics:
        diags = Diagnostics()
        limits = self.page_count_range(settings)
        if page_count < limits.minimum:
            diags.add(
                Severity.ERROR,
                "KDP-PAGES-MIN",
                f"{page_count} pages is below KDP's minimum of {limits.minimum} for "
                f"{settings.interior.ink!s} ink on {settings.interior.paper!s} paper",
                suggestion="add content; KDP does not accept shorter paperbacks",
            )
        elif page_count > limits.maximum:
            diags.add(
                Severity.ERROR,
                "KDP-PAGES-MAX",
                f"{page_count} pages exceeds KDP's maximum of {limits.maximum} for "
                f"{settings.interior.ink!s} ink on {settings.interior.paper!s} paper",
                suggestion="shorten the book, adjust typography, or split it into volumes",
            )
        elif inside_margin is not None:
            required = self.min_inside_margin(page_count)
            if inside_margin < required:
                diags.add(
                    Severity.ERROR,
                    "KDP-GUTTER",
                    f"inside margin {inside_margin} is below KDP's {required} gutter for "
                    f"{page_count} pages",
                    suggestion=f"use margins.inside 'auto' or at least {required}",
                )

        expected = self.interior_page_size(settings)
        tolerance = Length.pt("0.5")
        for axis in ("width", "height"):
            got, want = getattr(dimensions, axis), getattr(expected, axis)
            if abs((got - want).exact_inches) > tolerance.exact_inches:
                diags.add(
                    Severity.ERROR,
                    "KDP-PAGE-SIZE",
                    f"interior page {axis} {got.to_str('in', 4)} does not match the required "
                    f"{want.to_str('in', 4)}",
                    suggestion="re-render with the resolved trim and bleed settings",
                )
        return diags


KDP = KdpPaperback()
