"""Render a full-wrap cover PDF and write its machine-readable specification.

The cover is one page: back cover, spine and front cover left to right, sized from
the provider's cover rules and the *finished* interior page count. Artwork may be
a full wrap image, or separate front/back images, or no artwork at all (a
typography-based cover). The barcode area is reserved and never drawn: PrintForge
does not fabricate an ISBN, barcode or its image.

The production PDF carries no crop or guide marks. Determinism matches the
interior renderer: embedded font timestamps are normalized and the information
dictionary is written explicitly, so repeat builds are byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from printforge import __version__
from printforge.config.settings import PrintSettings, SpineText
from printforge.cover.geometry import Box, CoverGeometry, cover_geometry
from printforge.diagnostics import Diagnostic, Diagnostics, Severity
from printforge.errors import ConfigError, RenderError
from printforge.fsutil import atomic_write_bytes, atomic_write_text
from printforge.importer.paths import resolve_local_asset
from printforge.layout.styles import css_string
from printforge.log import get_logger
from printforge.providers.base import PageSize, ProviderProfile
from printforge.render.base import InteriorRenderer
from printforge.render.html import esc
from printforge.render.pdf import normalize_pdf, read_pdf
from printforge.units import ZERO, Length

log = get_logger("cover")

#: Raster formats WeasyPrint can place. SVG is accepted but has no raster DPI.
SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})

#: Spine text smaller than this is unreadable; ``auto`` omits it instead.
MIN_SPINE_TEXT_PT = 6.0
MAX_SPINE_TEXT_PT = 36.0
#: Rough average advance width of a fallback sans/serif glyph, in em.
SPINE_CHAR_WIDTH_EM = 0.6
#: Above this much artwork cropping, warn: the image aspect does not match.
ASPECT_TOLERANCE = 0.02


@dataclass(frozen=True, slots=True)
class Artwork:
    """One placed image: the role it plays, its file and the box it must cover."""

    role: str  # "wrap", "front" or "back"
    path: Path
    box: Box
    pixels: tuple[int, int] | None  # None for SVG


@dataclass(frozen=True, slots=True)
class CoverResult:
    """Facts about a finished cover, for the build manifest and preflight."""

    pdf_path: Path
    spec_path: Path
    spec: dict[str, Any]
    interior_page_count: int  # the page count the spine was derived from
    size: PageSize
    diagnostics: tuple[Diagnostic, ...]
    sha256: str


def build_cover(
    settings: PrintSettings,
    provider: ProviderProfile,
    page_count: int,
    *,
    pdf_path: Path,
    spec_path: Path,
    metadata: Mapping[str, Any] | None = None,
    config_dir: Path | None = None,
    renderer: InteriorRenderer | None = None,
) -> CoverResult:
    """Render ``cover.pdf`` and write ``cover-spec.json`` for ``page_count`` pages."""
    pdf_path = Path(pdf_path)
    spec_path = Path(spec_path)
    geometry = cover_geometry(settings, provider, page_count)
    book = _book_metadata(settings, metadata)

    diagnostics = Diagnostics()
    artwork = _artwork(settings, geometry, config_dir)
    _check_artwork(artwork, geometry, diagnostics)
    # A full wrap image already contains the spine; generated spine text would
    # double up, so the artwork owns it.
    has_wrap = any(art.role == "wrap" for art in artwork)
    spine_text, spine_pt = (
        (None, 0.0) if has_wrap else _spine_text(settings, geometry, book, diagnostics)
    )

    html = _cover_html(settings, geometry, artwork, book, spine_text, spine_pt)
    css = _cover_css(settings, geometry)
    assets = frozenset(art.path for art in artwork)

    laid_out = _renderer(renderer).lay_out(html, css, assets)
    raw = laid_out.write_pdf()
    if _has_text(settings, artwork, book, spine_text):
        _check_font(laid_out.font_families, settings)

    data = normalize_pdf(raw, _document_info(book))
    facts = read_pdf(data)
    if facts.page_count != 1:
        raise RenderError(
            f"cover rendered as {facts.page_count} pages; a full-wrap cover must be one page",
            hint="check the cover artwork and text sizes",
        )
    _check_page_size(facts.size, geometry)

    atomic_write_bytes(pdf_path, data)
    spec = geometry.to_spec(settings, provider)
    atomic_write_text(spec_path, json.dumps(spec, indent=2) + "\n")

    digest = hashlib.sha256(data).hexdigest()
    log.debug(
        "cover %s: %s x %s, spine %s, %d page(s), sha256 %s",
        pdf_path,
        geometry.width,
        geometry.height,
        geometry.spine,
        page_count,
        digest[:12],
    )
    return CoverResult(
        pdf_path=pdf_path,
        spec_path=spec_path,
        spec=spec,
        interior_page_count=page_count,
        size=facts.size,
        diagnostics=tuple(diagnostics),
        sha256=digest,
    )


# ---------------------------------------------------------------- artwork


def _artwork(
    settings: PrintSettings, geometry: CoverGeometry, config_dir: Path | None
) -> tuple[Artwork, ...]:
    cover = settings.cover
    if cover.wrap_image:
        return (
            _place_artwork(
                "wrap",
                cover.wrap_image,
                Box(ZERO, ZERO, geometry.width, geometry.height),
                config_dir,
            ),
        )
    placed: list[Artwork] = []
    if cover.back_image:
        placed.append(
            _place_artwork(
                "back",
                cover.back_image,
                Box(ZERO, ZERO, geometry.folds[0], geometry.height),
                config_dir,
            )
        )
    if cover.front_image:
        placed.append(
            _place_artwork(
                "front",
                cover.front_image,
                Box(
                    geometry.folds[1],
                    ZERO,
                    geometry.width - geometry.folds[1],
                    geometry.height,
                ),
                config_dir,
            )
        )
    return tuple(placed)


def _place_artwork(role: str, reference: str, box: Box, config_dir: Path | None) -> Artwork:
    if config_dir is None:
        raise ConfigError(
            "cover artwork paths are relative to the configuration directory",
            hint="pass the directory that contains print.json/book.json",
        )
    path = resolve_local_asset(reference, root=Path(config_dir))
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise RenderError(
            f"cover artwork {reference!r} has an unsupported format ({path.suffix or 'none'})",
            hint="use PNG, JPEG or SVG artwork",
        )
    return Artwork(role, path, box, _pixel_size(path, reference))


def _pixel_size(path: Path, reference: str) -> tuple[int, int] | None:
    if path.suffix.lower() == ".svg":
        return None
    from PIL import Image as PILImage

    try:
        with PILImage.open(path) as handle:
            return handle.size
    except Exception as exc:
        raise RenderError(
            f"cover artwork {reference!r} cannot be decoded: {exc}",
            hint="re-export the cover artwork as PNG or JPEG",
        ) from exc


def _check_artwork(
    artwork: tuple[Artwork, ...], geometry: CoverGeometry, diagnostics: Diagnostics
) -> None:
    minimum = geometry.rules.min_image_dpi
    for art in artwork:
        if art.pixels is None:
            continue
        width = _placement(art)[2]
        dpi = art.pixels[0] / float(width.exact_inches)
        context = f"{art.role} cover artwork: {art.path.name}"
        if dpi < minimum:
            expected_w = _ceil_inches(art.box.width, minimum)
            expected_h = _ceil_inches(art.box.height, minimum)
            diagnostics.add(
                Severity.WARNING,
                "COVER-IMAGE-DPI",
                f"artwork is about {dpi:.0f} DPI at its printed size, below the "
                f"{minimum} DPI minimum",
                context=context,
                suggestion=f"provide at least {expected_w} x {expected_h} pixels",
            )
        box_ratio = art.box.width.exact_inches / art.box.height.exact_inches
        image_ratio = Fraction(*art.pixels)
        if abs(float(image_ratio / box_ratio) - 1.0) > ASPECT_TOLERANCE:
            diagnostics.add(
                Severity.WARNING,
                "COVER-IMAGE-ASPECT",
                "artwork aspect ratio does not match its print area, so it will be cropped",
                context=context,
                suggestion="match the ratio in cover-spec.json or accept the crop",
            )


def _ceil_inches(length: Length, dpi: int) -> int:
    return int(length.exact_inches * dpi) + 1


def _placement(art: Artwork) -> tuple[Length, Length, Length, Length]:
    """Cover-fit ``art`` into its box: preserve aspect, crop the overflow."""
    box = art.box
    if art.pixels is None or 0 in art.pixels:
        return box.x, box.y, box.width, box.height
    image_ratio = Fraction(*art.pixels)
    box_ratio = box.width.exact_inches / box.height.exact_inches
    if image_ratio >= box_ratio:
        height = box.height
        width = height * image_ratio
    else:
        width = box.width
        height = width / image_ratio
    return (
        box.x - (width - box.width) / 2,
        box.y - (height - box.height) / 2,
        width,
        height,
    )


# ---------------------------------------------------------------- spine text


def _spine_text(
    settings: PrintSettings,
    geometry: CoverGeometry,
    book: Mapping[str, Any],
    diagnostics: Diagnostics,
) -> tuple[str | None, float]:
    mode = settings.cover.spine_text
    if mode is SpineText.NEVER:
        return None, 0.0
    parts = [text for text in (_text(book, "title"), _text(book, "author")) if text]
    if not parts:
        return None, 0.0
    text = " · ".join(parts)
    if not geometry.spine_text_allowed:
        message = (
            f"spine text needs at least {geometry.rules.spine_text_min_pages} pages, "
            f"the book has {geometry.page_count}"
        )
        if mode is SpineText.ALWAYS:
            raise RenderError(
                message,
                hint="set cover.spine_text to 'auto' or 'never', or add pages",
            )
        return None, 0.0

    usable_width_pt = float(geometry.spine_safe.width.exact_inches) * 72
    usable_height_pt = float(geometry.spine_safe.height.exact_inches) * 72
    font_pt = min(
        MAX_SPINE_TEXT_PT,
        usable_width_pt * 0.8,
        usable_height_pt / (SPINE_CHAR_WIDTH_EM * max(len(text), 1)),
    )
    if font_pt < MIN_SPINE_TEXT_PT:
        message = (
            f"spine text does not fit the {geometry.spine.to_str('in')} spine: "
            f"it would be {font_pt:.1f}pt, below the {MIN_SPINE_TEXT_PT:.0f}pt minimum"
        )
        if mode is SpineText.ALWAYS:
            raise RenderError(
                message,
                hint="set cover.spine_text to 'auto' or 'never', or shorten the text",
            )
        diagnostics.add(
            Severity.WARNING,
            "COVER-SPINE-TEXT-TIGHT",
            message,
            context="cover spine",
            suggestion="leave the spine blank (spine_text 'auto' or 'never')",
        )
        return None, 0.0
    return text, font_pt


# ---------------------------------------------------------------- html / css


def _has_text(
    settings: PrintSettings,
    artwork: tuple[Artwork, ...],
    book: Mapping[str, Any],
    spine_text: str | None,
) -> bool:
    """Whether the cover contains any typography (and therefore needs fonts)."""
    if spine_text:
        return True
    if not any(art.role in ("front", "wrap") for art in artwork):
        return True
    if any(art.role in ("back", "wrap") for art in artwork):
        return False
    return bool(_text(book, "description") or settings.cover.back_text)


def _cover_html(
    settings: PrintSettings,
    geometry: CoverGeometry,
    artwork: tuple[Artwork, ...],
    book: Mapping[str, Any],
    spine_text: str | None,
    spine_pt: float,
) -> str:
    has_front_art = any(art.role in ("front", "wrap") for art in artwork)
    has_back_art = any(art.role in ("back", "wrap") for art in artwork)
    has_wrap = any(art.role == "wrap" for art in artwork)

    parts: list[str] = []
    for art in artwork:
        left, top, width, height = _placement(art)
        parts.append(
            f'<img class="pf-art" src="{esc(art.path.as_uri())}" '
            f'alt="{esc(art.role)} cover artwork" '
            f'style="left:{left.css()};top:{top.css()};'
            f'width:{width.css()};height:{height.css()}">'
        )

    if not has_front_art:
        parts.extend(_front_blocks(geometry, book))
    if not has_back_art:
        back = _text(book, "description") or settings.cover.back_text
        if back:
            safe = geometry.back_safe
            parts.append(
                f'<div class="pf-back" style="left:{safe.x.css()};'
                f"top:{(safe.y + safe.height * Fraction(1, 10)).css()};"
                f'width:{safe.width.css()};height:{(safe.height * Fraction(13, 20)).css()}">'
                f"<p>{esc(back)}</p></div>"
            )
    if spine_text and not has_wrap:
        safe = geometry.spine_safe
        parts.append(
            f'<div class="pf-spine" style="left:{safe.x.css()};top:{safe.y.css()};'
            f'width:{safe.width.css()};height:{safe.height.css()}">'
            f'<span style="width:{safe.height.css()};height:{safe.width.css()};'
            f'line-height:{safe.width.css()};font-size:{spine_pt:.2f}pt">'
            f"{esc(spine_text)}</span></div>"
        )

    title = _text(book, "title") or "Cover"
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title>"
        f'</head><body><div class="pf-cover">{"".join(parts)}</div></body></html>\n'
    )


def _front_blocks(geometry: CoverGeometry, book: Mapping[str, Any]) -> list[str]:
    safe = geometry.front_safe
    title = _text(book, "title") or ""
    subtitle = _text(book, "subtitle")
    author = _text(book, "author")
    publisher = _text(book, "publisher")

    blocks = [f'<p class="pf-cover-title">{esc(title)}</p>']
    if subtitle:
        blocks.append(f'<p class="pf-cover-subtitle">{esc(subtitle)}</p>')
    parts = [
        f'<div class="pf-title" style="left:{safe.x.css()};'
        f"top:{(safe.y + safe.height * Fraction(1, 5)).css()};"
        f'width:{safe.width.css()}">{"".join(blocks)}</div>'
    ]
    if author:
        parts.append(
            f'<div class="pf-author" style="left:{safe.x.css()};'
            f"top:{(safe.y + safe.height * Fraction(7, 10)).css()};"
            f'width:{safe.width.css()}">'
            f'<p class="pf-cover-author">{esc(author)}</p></div>'
        )
    if publisher:
        parts.append(
            f'<p class="pf-imprint" style="left:{safe.x.css()};'
            f"top:{(safe.y + safe.height * Fraction(17, 20)).css()};"
            f'width:{safe.width.css()}">{esc(publisher)}</p>'
        )
    return parts


def _cover_css(settings: PrintSettings, geometry: CoverGeometry) -> str:
    width = geometry.width.css()
    height = geometry.height.css()
    family = css_string(settings.typography.heading_font)
    trim_height = float(geometry.trim[1].exact_inches)
    title_pt = 3.2 * trim_height
    subtitle_pt = 1.5 * trim_height
    imprint_pt = 0.95 * trim_height
    return (
        "\n".join(
            [
                f"@page {{ size: {width} {height}; margin: 0; }}",
                "html, body { margin: 0; padding: 0; }",
                f".pf-cover {{ position: relative; width: {width}; height: {height}; "
                f"overflow: hidden; background: {settings.cover.background_color}; "
                f"color: {settings.cover.text_color}; font-family: {family}; }}",
                ".pf-art { position: absolute; }",
                ".pf-title, .pf-author { position: absolute; text-align: center; }",
                f".pf-cover-title {{ margin: 0; font-size: {title_pt:.2f}pt; line-height: 1.15; }}",
                f".pf-cover-subtitle {{ margin: 0.35em 0 0; font-size: {subtitle_pt:.2f}pt; "
                "font-style: italic; line-height: 1.3; }",
                f".pf-cover-author {{ margin: 0; font-size: {subtitle_pt:.2f}pt; "
                "line-height: 1.3; }",
                f".pf-imprint {{ position: absolute; margin: 0; text-align: center; "
                f"font-size: {imprint_pt:.2f}pt; letter-spacing: 0.12em; "
                "text-transform: uppercase; }",
                f".pf-back {{ position: absolute; font-size: {subtitle_pt:.2f}pt; "
                "line-height: 1.5; }",
                ".pf-back p { margin: 0; text-align: left; text-indent: 0; hyphens: auto; }",
                ".pf-spine { position: absolute; }",
                ".pf-spine span { display: block; text-align: center; "
                "transform-origin: 0 0; transform: rotate(90deg) translateY(-100%); }",
            ]
        )
        + "\n"
    )


# ---------------------------------------------------------------- helpers


def _book_metadata(settings: PrintSettings, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    book = dict(metadata or {})
    book.setdefault("title", settings.metadata.title)
    book.setdefault("author", settings.metadata.author)
    book.setdefault("subtitle", settings.metadata.subtitle)
    book.setdefault("publisher", settings.metadata.publisher)
    book.setdefault("description", settings.metadata.description)
    return book


def _text(book: Mapping[str, Any], key: str) -> str | None:
    value = book.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _document_info(book: Mapping[str, Any]) -> dict[str, str]:
    producer = f"PrintForge {__version__}"
    info = {
        "Title": _text(book, "title") or "Cover",
        "Producer": producer,
        "Creator": producer,
    }
    author = _text(book, "author")
    if author:
        info["Author"] = author
    return info


def _check_font(families: tuple[str, ...], settings: PrintSettings) -> None:
    if settings.typography.heading_font not in families:
        raise RenderError(
            f"cover font was not embedded: {settings.typography.heading_font}",
            hint="install the font or change typography.heading_font",
        )


def _check_page_size(size: PageSize, geometry: CoverGeometry) -> None:
    tolerance = Length.pt("0.5")
    for axis, expected in (("width", geometry.width), ("height", geometry.height)):
        actual = getattr(size, axis)
        if abs((actual - expected).exact_inches) > tolerance.exact_inches:
            raise RenderError(
                f"cover page {axis} {actual.to_str('in', 4)} does not match the required "
                f"{expected.to_str('in', 4)}",
                hint="check the cover stylesheet page size",
            )


def _renderer(renderer: InteriorRenderer | None) -> InteriorRenderer:
    if renderer is not None:
        return renderer
    from printforge.render.weasy import WeasyPrintRenderer

    return WeasyPrintRenderer()


__all__ = [
    "MIN_SPINE_TEXT_PT",
    "SUPPORTED_IMAGE_SUFFIXES",
    "Artwork",
    "CoverResult",
    "build_cover",
]
