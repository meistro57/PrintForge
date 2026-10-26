"""Page geometry, section policies and the gutter convergence loop.

Geometry is computed from resolved settings plus a provider profile and is
independent of Markdown parsing. The inside (gutter) margin can depend on the
*final* page count (KDP gutter tiers), so :func:`paginate_until_stable` renders,
measures, recomputes, and renders again until the gutter used matches the
gutter the resulting page count requires, or fails with a bounded
:class:`LayoutConvergenceError`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from printforge.config.settings import (
    ChapterStart,
    FolioPosition,
    FrontFolios,
    LayoutSettings,
    PrintSettings,
    Typography,
)
from printforge.errors import RenderError
from printforge.log import get_logger
from printforge.providers.base import PageSize, ProviderProfile
from printforge.units import Length

log = get_logger("layout")

T = TypeVar("T")


class PageSide(StrEnum):
    RECTO = "recto"  # right-hand, odd-numbered page; binding (gutter) on its LEFT edge
    VERSO = "verso"  # left-hand, even-numbered page; binding (gutter) on its RIGHT edge


class FolioStyle(StrEnum):
    NONE = "none"
    LOWER_ROMAN = "lower-roman"
    DECIMAL = "decimal"


@dataclass(frozen=True, slots=True)
class PageMargins:
    top: Length
    bottom: Length
    left: Length
    right: Length


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """Physical page box and mirrored margins for single-page (not spread) output."""

    page: PageSize  # PDF page size (trim, or trim + interior bleed)
    trim: PageSize
    top: Length
    bottom: Length
    inside: Length  # gutter side
    outside: Length

    def margins(self, side: PageSide) -> PageMargins:
        if side is PageSide.RECTO:
            return PageMargins(self.top, self.bottom, left=self.inside, right=self.outside)
        return PageMargins(self.top, self.bottom, left=self.outside, right=self.inside)

    @property
    def text_width(self) -> Length:
        return self.page.width - self.inside - self.outside

    @property
    def text_height(self) -> Length:
        return self.page.height - self.top - self.bottom


@dataclass(frozen=True, slots=True)
class SectionPolicy:
    """How one kind of page run is paginated and decorated."""

    name: str  # CSS named page
    folio: FolioStyle
    running_heads: bool
    start: ChapterStart  # where each unit of this section starts
    restart_numbering: bool = False  # first page of this section is folio 1


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    geometry: PageGeometry
    typography: Typography
    layout: LayoutSettings
    sections: dict[str, SectionPolicy]
    page_count_basis: int  # page count the gutter was computed for
    gutter_rule: str  # how the inside margin was chosen (for reports)
    book_title: str

    def section(self, name: str) -> SectionPolicy:
        return self.sections[name]


# Named page runs used by the renderer's HTML contract (see styles.py).
DISPLAY = "front-display"  # half title, title, copyright: no folio, no heads
FRONT = "front"  # contents, foreword, ...: roman folios, no heads
PART = "part"  # part divider pages
CHAPTER = "chapter"  # chapters, appendices, back matter
START_SUFFIX = "-start"  # variant for the first main-matter unit: restarts folio 1


def section_policies(layout: LayoutSettings) -> dict[str, SectionPolicy]:
    front_folio = (
        FolioStyle.LOWER_ROMAN
        if layout.front_matter_folios is FrontFolios.LOWER_ROMAN
        else FolioStyle.NONE
    )
    heads = layout.running_heads
    policies = {
        DISPLAY: SectionPolicy(DISPLAY, FolioStyle.NONE, False, ChapterStart.RECTO),
        FRONT: SectionPolicy(FRONT, front_folio, False, ChapterStart.RECTO),
        PART: SectionPolicy(PART, FolioStyle.NONE, False, ChapterStart.RECTO),
        CHAPTER: SectionPolicy(CHAPTER, FolioStyle.DECIMAL, heads, layout.chapter_start),
    }
    for base in (PART, CHAPTER):
        p = policies[base]
        name = base + START_SUFFIX
        # Main matter always starts on a recto, whatever the chapter_start policy.
        policies[name] = SectionPolicy(name, p.folio, p.running_heads, ChapterStart.RECTO, True)
    return policies


def inside_margin(
    settings: PrintSettings, provider: ProviderProfile, page_count: int
) -> tuple[Length, str]:
    """Inside margin for ``page_count`` pages and a description of the rule used."""
    explicit = settings.margins.inside
    if explicit is not None:
        return explicit, f"explicit margins.inside {explicit}"
    limits = provider.page_count_range(settings)
    clamped = min(max(page_count, limits.minimum), limits.maximum)
    gutter = provider.min_inside_margin(clamped)
    extra = settings.margins.gutter_extra
    rule = f"{provider.name} minimum {gutter} for {page_count} pages + gutter_extra {extra}"
    if clamped != page_count:
        rule += f" (outside {limits.minimum}-{limits.maximum}: tier for {clamped} used)"
    return gutter + extra, rule


def plan_layout(
    settings: PrintSettings, provider: ProviderProfile, page_count: int, *, book_title: str
) -> LayoutPlan:
    page = provider.interior_page_size(settings)
    inside, rule = inside_margin(settings, provider, page_count)
    geometry = PageGeometry(
        page=page,
        trim=PageSize(settings.trim.width, settings.trim.height),
        top=settings.margins.top,
        bottom=settings.margins.bottom,
        inside=inside,
        outside=settings.margins.outside,
    )
    if geometry.text_width <= Length(0) or geometry.text_height <= Length(0):
        raise RenderError("margins leave no room for text on the page")
    return LayoutPlan(
        geometry=geometry,
        typography=settings.typography,
        layout=settings.layout,
        sections=section_policies(settings.layout),
        page_count_basis=page_count,
        gutter_rule=rule,
        book_title=book_title,
    )


# ------------------------------------------------------------------ convergence


class LayoutConvergenceError(RenderError):
    """Pagination did not settle on a gutter consistent with its own page count."""


@dataclass(frozen=True, slots=True)
class PaginationPass:
    basis: int  # page count the plan's gutter was computed for
    inside: Length
    page_count: int  # pages actually produced


@dataclass(frozen=True, slots=True)
class Converged(Generic[T]):
    plan: LayoutPlan
    page_count: int
    result: T
    passes: tuple[PaginationPass, ...]


def paginate_until_stable(
    settings: PrintSettings,
    provider: ProviderProfile,
    render: Callable[[LayoutPlan], tuple[int, T]],
    *,
    book_title: str,
    initial_page_count: int | None = None,
    max_passes: int = 5,
) -> Converged[T]:
    """Render repeatedly until the gutter matches the produced page count.

    ``render(plan)`` must lay out the whole book with ``plan`` and return
    ``(page_count, result)``. The page count is never guessed: a plan is accepted
    only when the inside margin required for the *produced* page count equals the
    inside margin the plan was rendered with.
    """
    basis = initial_page_count or provider.page_count_range(settings).minimum
    history: list[PaginationPass] = []
    for _ in range(max_passes):
        plan = plan_layout(settings, provider, basis, book_title=book_title)
        page_count, result = render(plan)
        history.append(PaginationPass(basis, plan.geometry.inside, page_count))
        required, _rule = inside_margin(settings, provider, page_count)
        log.debug(
            "pagination pass %d: gutter %s -> %d pages (requires %s)",
            len(history),
            plan.geometry.inside,
            page_count,
            required,
        )
        if required == plan.geometry.inside:
            final = plan_layout(settings, provider, page_count, book_title=book_title)
            return Converged(final, page_count, result, tuple(history))
        if any(p.inside == required for p in history):
            raise LayoutConvergenceError(_describe("pagination oscillates", history))
        basis = page_count
    raise LayoutConvergenceError(_describe(f"no stable gutter after {max_passes} passes", history))


def _describe(reason: str, history: list[PaginationPass]) -> str:
    steps = "; ".join(f"gutter {p.inside} -> {p.page_count} pages" for p in history)
    return (
        f"{reason}: {steps}. The page count crosses a gutter tier boundary; set an explicit "
        "margins.inside for the higher tier or adjust typography so the page count settles"
    )


__all__ = [
    "CHAPTER",
    "DISPLAY",
    "FRONT",
    "PART",
    "START_SUFFIX",
    "ChapterStart",
    "Converged",
    "FolioPosition",
    "FolioStyle",
    "LayoutConvergenceError",
    "LayoutPlan",
    "PageGeometry",
    "PageMargins",
    "PageSide",
    "PaginationPass",
    "SectionPolicy",
    "inside_margin",
    "paginate_until_stable",
    "plan_layout",
    "section_policies",
]
