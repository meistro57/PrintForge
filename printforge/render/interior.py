"""Build a print-ready interior PDF from the semantic document and layout plan.

The work is split the way ``docs/RENDERING.md`` describes:

* :mod:`printforge.render.html` turns the document into contract HTML,
* :mod:`printforge.layout.styles` supplies the paged-media stylesheet,
* :mod:`printforge.render.weasy` lays it out with WeasyPrint and draws the PDF,
* :mod:`printforge.render.pdf` normalizes the bytes and reads them back.

This module orchestrates those stages and reports facts a later stage needs: the
measured page count, page size, heading locations and embedded fonts.

Guarantees:

* The output file is written atomically. A failed build leaves no file behind.
* Manuscript ERROR diagnostics (for example an unresolved image) stop the build
  before rendering, with the chapter and file named.
* Required fonts are verified after rendering; a silent substitution is reported.
* Metadata is written explicitly and embedded fonts are timestamp-normalized, so
  the same document plus the same plan renders to the same bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from printforge import __version__
from printforge.diagnostics import Diagnostics, Severity
from printforge.document.model import (
    Block,
    BlockQuote,
    CodeBlock,
    Document,
    Image,
    Inline,
    InlineCode,
    ListBlock,
    Paragraph,
    Table,
)
from printforge.errors import RenderError
from printforge.fsutil import atomic_write_bytes
from printforge.layout.plan import LayoutPlan
from printforge.layout.styles import stylesheet
from printforge.log import get_logger
from printforge.render.base import InteriorRenderer, RenderedPage
from printforge.render.html import HeadingAnchor, build_html
from printforge.render.pdf import normalize_pdf, read_pdf
from printforge.render.result import HeadingLocation, RenderResult

if TYPE_CHECKING:
    from printforge.config.settings import PrintSettings

log = get_logger("render")

#: Images above this effective resolution only bloat the PDF; KDP recommends
#: at most 600 DPI for interior images (docs/providers/KDP.md).
MAX_EFFECTIVE_IMAGE_DPI = 600

#: CSS reference resolution: an ``img`` without width/height renders at 96 DPI
#: before the stylesheet's ``max-width``/``max-height`` constraints apply.
CSS_PIXELS_PER_INCH = 96


class InteriorPdfBuilder:
    """Render a :class:`Document` with a :class:`LayoutPlan` to one PDF.

    ``metadata`` is the resolved book metadata (``ResolvedPrintJob.metadata``:
    title, author, description, overrides included). When omitted, only the
    ``print.json`` metadata overrides are used. ``renderer`` defaults to the
    WeasyPrint adapter and only needs overriding in tests.
    """

    def __init__(
        self,
        settings: PrintSettings,
        *,
        metadata: Mapping[str, Any] | None = None,
        renderer: InteriorRenderer | None = None,
    ) -> None:
        self.settings = settings
        self.metadata = dict(metadata) if metadata is not None else _settings_metadata(settings)
        self.renderer = renderer

    def render(
        self,
        document: Document,
        layout: LayoutPlan,
        output_path: Path,
        *,
        front_units: tuple[str, ...] = (),
        front_unit_ids: tuple[str, ...] = (),
    ) -> RenderResult:
        output_path = Path(output_path)
        errors = [item for item in document.diagnostics if item.severity is Severity.ERROR]
        if errors:
            details = "\n".join(f"  - {item.format()}" for item in errors)
            raise RenderError(
                f"cannot render {len(errors)} manuscript error(s):\n{details}",
                hint="fix the reported chapter, image or link and build again",
            )
        if not document.chapters:
            raise RenderError("nothing to render: the document has no chapters")

        diagnostics = Diagnostics()
        _check_image_resolution(document, layout, self.settings, diagnostics)
        broken = diagnostics.errors()
        if broken:
            details = "\n".join(f"  - {item.format()}" for item in broken)
            raise RenderError(
                f"cannot render {len(broken)} image error(s):\n{details}",
                hint="replace or re-export the reported image files",
            )

        build = build_html(
            document,
            layout.layout,
            language=layout.typography.language,
            title=str(self.metadata.get("title") or document.title),
            author=str(self.metadata.get("author") or ""),
            front_units=front_units,
            front_unit_ids=front_unit_ids,
        )
        laid_out = self._renderer().lay_out(build.html, stylesheet(layout), build.assets)
        raw = laid_out.write_pdf()
        _check_fonts(laid_out.font_families, document, self.settings, diagnostics)

        data = normalize_pdf(raw, _document_info(document, self.metadata))
        facts = read_pdf(data)
        if facts.encrypted:
            raise RenderError("rendered PDF is encrypted; print files must not be")
        if any(size != facts.size for size in facts.page_sizes):
            raise RenderError(
                "rendered pages do not share one page size; check the layout stylesheet"
            )
        if facts.page_count < 1:
            raise RenderError("rendered PDF has no pages")
        labels = _page_labels(laid_out.pages, layout)
        locations = _heading_locations(laid_out.pages, build.anchors, labels)
        if not locations:
            raise RenderError(
                "rendered PDF has no located headings; the table of contents would be empty"
            )

        atomic_write_bytes(output_path, data)
        digest = hashlib.sha256(data).hexdigest()
        log.debug(
            "rendered %s: %d pages, %d heading(s), sha256 %s",
            output_path,
            facts.page_count,
            len(locations),
            digest[:12],
        )
        return RenderResult(
            path=output_path,
            page_count=facts.page_count,
            size=facts.size,
            inside_margin=layout.geometry.inside,
            headings=locations,
            toc=(),
            fonts=tuple(sorted({font.base_name for font in facts.fonts})),
            diagnostics=tuple(diagnostics),
            sha256=digest,
        )

    def _renderer(self) -> InteriorRenderer:
        if self.renderer is None:
            from printforge.render.weasy import WeasyPrintRenderer

            self.renderer = WeasyPrintRenderer()
        return self.renderer


# ---------------------------------------------------------------- validation


def _settings_metadata(settings: PrintSettings) -> dict[str, Any]:
    meta = settings.metadata
    return {
        "title": meta.title,
        "author": meta.author,
        "description": meta.description,
    }


def _document_info(document: Document, metadata: Mapping[str, Any]) -> dict[str, str]:
    producer = f"PrintForge {__version__}"
    info = {
        "Title": metadata.get("title") or document.title,
        "Producer": producer,
        "Creator": producer,
    }
    author = metadata.get("author")
    if author:
        info["Author"] = str(author)
    description = metadata.get("description")
    if description:
        info["Subject"] = str(description)
    return info


def _heading_locations(
    pages: tuple[RenderedPage, ...],
    anchors: tuple[HeadingAnchor, ...],
    labels: dict[int, str],
) -> tuple[HeadingLocation, ...]:
    found: dict[str, RenderedPage] = {}
    for page in pages:
        for anchor in page.anchors:
            found.setdefault(anchor, page)
    return tuple(
        HeadingLocation(
            anchor.id,
            anchor.text,
            anchor.level,
            anchor.kind,
            anchor.unit,
            found[anchor.id].index + 1,
            labels[found[anchor.id].index],
        )
        for anchor in anchors
        if anchor.id in found
    )


_ROMAN = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


def roman(number: int) -> str:
    """Lowercase roman numeral for front-matter folios (``4`` -> ``"iv"``)."""
    if number <= 0:
        return ""
    out: list[str] = []
    for value, symbol in _ROMAN:
        count, number = divmod(number, value)
        out.append(symbol * count)
    return "".join(out)


def _page_labels(pages: tuple[RenderedPage, ...], layout: LayoutPlan) -> dict[int, str]:
    """Page labels in the book's own sequence, keyed by physical page index.

    Front matter is numbered in lower roman from the first page; the first page
    of the main matter resets the decimal counter to 1 (the stylesheet's
    ``counter-reset``), so later blank pages still advance the printed folio.
    """
    main_start = next(
        (
            page.index
            for page in pages
            if (policy := layout.sections.get(page.name)) is not None and policy.restart_numbering
        ),
        None,
    )
    labels: dict[int, str] = {}
    for page in pages:
        if main_start is None or page.index < main_start:
            labels[page.index] = roman(page.index + 1)
        else:
            labels[page.index] = str(page.index - main_start + 1)
    return labels


def _check_fonts(
    families: tuple[str, ...],
    document: Document,
    settings: PrintSettings,
    diagnostics: Diagnostics,
) -> None:
    typography = settings.typography
    embedded = set(families)
    expected = {typography.body_font, typography.heading_font}
    if _uses_monospace(document):
        expected.add(typography.mono_font)

    missing = sorted(expected - embedded)
    if missing:
        raise RenderError(
            "required font(s) were not embedded: " + ", ".join(missing),
            hint=(
                "install the font or change typography.body_font / heading_font / "
                "mono_font; a silent substitution would change the printed page"
            ),
        )
    unexpected = sorted(embedded - expected)
    if unexpected:
        diagnostics.add(
            Severity.WARNING,
            "RENDER-FONT-FALLBACK",
            "glyphs from font(s) outside the configured families were embedded: "
            f"{', '.join(unexpected)}",
            context="rendered PDF",
            suggestion="check for characters the configured fonts do not cover",
        )


def _uses_monospace(document: Document) -> bool:
    return any(_blocks_have_code(chapter.blocks) for chapter in document.chapters)


def _blocks_have_code(blocks: tuple[Block, ...]) -> bool:
    for block in blocks:
        if isinstance(block, CodeBlock):
            return True
        if isinstance(block, BlockQuote) and _blocks_have_code(block.blocks):
            return True
        if isinstance(block, ListBlock) and any(
            _blocks_have_code(item.blocks) for item in block.items
        ):
            return True
        if any(_inlines_have_code(inlines) for inlines in _block_inlines(block)):
            return True
    return False


def _block_inlines(block: Block) -> tuple[tuple[Inline, ...], ...]:
    if isinstance(block, Paragraph):
        return (block.children,)
    if isinstance(block, Table):
        cells = [cell for row in (*block.header, *block.body) for cell in row]
        return tuple(cell.children for cell in cells)
    return ()


def _inlines_have_code(inlines: tuple[Inline, ...]) -> bool:
    for node in inlines:
        if isinstance(node, InlineCode):
            return True
        children = getattr(node, "children", None)
        if children and _inlines_have_code(children):
            return True
    return False


# ---------------------------------------------------------------- images


def _check_image_resolution(
    document: Document,
    layout: LayoutPlan,
    settings: PrintSettings,
    diagnostics: Diagnostics,
) -> None:
    text_width = _inches(layout.geometry.text_width)
    text_height = _inches(layout.geometry.text_height) * 0.85  # stylesheet max-height
    minimum = settings.images.min_dpi
    for chapter, image in document.images:
        size = _pixel_size(image)
        context = f"{chapter.source} ({image.relative_path or image.source})"
        if size is None:
            if image.path is not None and image.path.suffix.lower() != ".svg":
                diagnostics.add(
                    Severity.ERROR,
                    "RENDER-IMAGE-UNREADABLE",
                    "image file cannot be decoded; it would be silently dropped from the PDF",
                    context=context,
                    suggestion="re-export the image as PNG, JPEG or SVG",
                )
            continue
        dpi = _effective_dpi(size, text_width, text_height)
        if dpi < minimum:
            diagnostics.add(
                Severity.WARNING,
                "RENDER-IMAGE-DPI",
                f"image is about {dpi:.0f} DPI at its printed size, below the "
                f"{minimum} DPI minimum",
                context=context,
                suggestion="replace it with a higher-resolution file or print it smaller",
            )
        elif dpi > MAX_EFFECTIVE_IMAGE_DPI:
            diagnostics.add(
                Severity.WARNING,
                "RENDER-IMAGE-LARGE",
                f"image is about {dpi:.0f} DPI at its printed size, above the "
                f"{MAX_EFFECTIVE_IMAGE_DPI} DPI guideline",
                context=context,
                suggestion="downsample the file to keep the PDF small; print quality is unaffected",
            )


def _pixel_size(image: Image) -> tuple[int, int] | None:
    if image.path is None:
        return None
    from PIL import Image as PILImage

    try:
        with PILImage.open(image.path) as handle:
            return handle.size
    except Exception:
        return None  # SVG and unreadable files: no raster DPI to report


def _effective_dpi(size: tuple[int, int], text_width: float, text_height: float) -> float:
    """DPI at the size the image is printed: natural CSS size, shrunk to fit."""
    width_px, height_px = size
    if width_px <= 0 or height_px <= 0:
        return 0.0
    natural_width = width_px / CSS_PIXELS_PER_INCH
    natural_height = height_px / CSS_PIXELS_PER_INCH
    scale = min(1.0, text_width / natural_width, text_height / natural_height)
    if scale <= 0:
        return 0.0
    return CSS_PIXELS_PER_INCH / scale


def _inches(length: Any) -> float:
    return float(length.exact_inches)


__all__ = [
    "MAX_EFFECTIVE_IMAGE_DPI",
    "HeadingLocation",
    "InteriorPdfBuilder",
    "RenderResult",
]
