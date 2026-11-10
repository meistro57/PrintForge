"""Printed front matter: half title, title page, copyright page and contents.

Everything here comes from resolved settings and book metadata. Fields that were
not supplied are omitted rather than invented: no placeholder ISBN, no assumed
copyright holder, no legal boilerplate, no publisher identity.

The generated units are plain HTML strings in the layout contract; the renderer
inserts them before the manuscript's own front matter (see
:func:`printforge.render.html.build_html`).
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from printforge.config.settings import PrintSettings, TocSettings
from printforge.render.result import HeadingLocation, TocEntry

DISPLAY_UNIT_ID = "sec-front-display"
TOC_UNIT_ID = "sec-toc"
TOC_TITLE_ID = "toc"

#: Heading kinds that name a whole unit rather than a Markdown heading.
UNIT_KINDS = ("part", "front-matter", "chapter", "appendix", "back-matter")


def build_front_units(
    settings: PrintSettings,
    metadata: Mapping[str, Any],
    entries: tuple[TocEntry, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the generated ``<section>`` units and their IDs, in print order."""
    units: list[str] = []
    ids: list[str] = []

    pages = display_pages(settings, metadata)
    if pages:
        units.append(
            f'<section class="pf-display" id="{DISPLAY_UNIT_ID}">' + "".join(pages) + "</section>"
        )
        ids.append(DISPLAY_UNIT_ID)
    if settings.toc.enabled:
        units.append(toc_unit(settings.toc, entries))
        ids.append(TOC_UNIT_ID)
    return tuple(units), tuple(ids)


def display_pages(settings: PrintSettings, metadata: Mapping[str, Any]) -> list[str]:
    """Half-title, title and copyright pages, each as its own display page."""
    pages: list[str] = []
    if settings.front_matter.half_title:
        pages.append(_half_title_page(metadata))
    if settings.front_matter.title_page:
        pages.append(_title_page(metadata))
    if settings.front_matter.copyright_page:
        # The copyright page is the verso of the title page when both exist.
        pages.append(_copyright_page(metadata, verso=settings.front_matter.title_page))
    return pages


def toc_unit(toc: TocSettings, entries: tuple[TocEntry, ...]) -> str:
    """The contents section; ``entries`` may be empty on the first pass."""
    rows = "".join(_toc_row(entry) for entry in entries)
    return (
        f'<section class="pf-front" id="{TOC_UNIT_ID}">'
        '<header class="pf-opener">'
        f'<h1 class="pf-chapter-title" id="{TOC_TITLE_ID}">{escape(toc.title)}</h1>'
        "</header>"
        f'<nav class="pf-toc">{rows}</nav>'
        "</section>"
    )


def toc_entries(headings: tuple[HeadingLocation, ...], toc: TocSettings) -> tuple[TocEntry, ...]:
    """Filter headings into printed contents rows.

    ``toc.depth`` 1 lists parts and chapters, 2 adds ``##`` headings, 3 adds
    ``###`` headings. Empty heading text and disabled kinds are dropped so a
    malformed manuscript cannot corrupt the page.
    """
    entries: list[TocEntry] = []
    for heading in headings:
        if not heading.text.strip():
            continue
        if heading.kind == "front-matter" and not toc.include_front_matter:
            continue
        if heading.kind == "part" and not toc.include_parts:
            continue
        level = 1 if heading.unit else heading.level - 1
        if level > toc.depth:
            continue
        entries.append(TocEntry(heading.id, heading.text, level, heading.folio, heading.kind))
    return tuple(entries)


# ---------------------------------------------------------------- pages


def _half_title_page(metadata: Mapping[str, Any]) -> str:
    title = _text(metadata, "title") or ""
    return f'<div class="pf-page pf-recto"><p class="pf-half-title">{escape(title)}</p></div>'


def _title_page(metadata: Mapping[str, Any]) -> str:
    title = _text(metadata, "title") or ""
    blocks = [f'<p class="pf-book-title">{escape(title)}</p>']
    subtitle = _text(metadata, "subtitle")
    if subtitle:
        blocks.append(f'<p class="pf-subtitle">{escape(subtitle)}</p>')
    author = _text(metadata, "author")
    if author:
        blocks.append(f'<p class="pf-author">{escape(author)}</p>')
    publisher = _text(metadata, "publisher")
    if publisher:
        blocks.append(f'<p class="pf-imprint">{escape(publisher)}</p>')
    return (
        f'<div class="pf-page pf-recto"><div class="pf-title-block">{"".join(blocks)}</div></div>'
    )


def _copyright_page(metadata: Mapping[str, Any], *, verso: bool) -> str:
    lines: list[str] = []
    year = metadata.get("copyright_year")
    holder = _text(metadata, "copyright_holder")
    if year or holder:
        parts = ["©"]
        if year is not None:
            parts.append(str(year))
        if holder:
            parts.append(holder)
        lines.append(" ".join(parts))
    edition = _text(metadata, "edition")
    if edition:
        lines.append(edition)
    isbn = _text(metadata, "isbn")
    if isbn:
        lines.append(f"ISBN {isbn}")
    publisher = _text(metadata, "publisher")
    if publisher:
        lines.append(publisher)

    body = "".join(f"<p>{escape(line)}</p>" for line in lines)
    side = "pf-verso" if verso else "pf-recto"
    return f'<div class="pf-page {side}"><div class="pf-copyright">{body}</div></div>'


def _toc_row(entry: TocEntry) -> str:
    classes = ["pf-toc-entry", f"pf-toc-level-{entry.level}"]
    if entry.kind == "part":
        classes.append("pf-toc-part")
    folio = f'<span class="pf-toc-folio">{escape(entry.folio)}</span>' if entry.folio else ""
    return (
        f'<div class="{" ".join(classes)}">'
        f'<a href="#{escape(entry.id)}">{escape(entry.text)}</a>'
        f'<span class="pf-toc-dots"></span>{folio}</div>'
    )


def _text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DISPLAY_UNIT_ID",
    "TOC_TITLE_ID",
    "TOC_UNIT_ID",
    "build_front_units",
    "display_pages",
    "toc_entries",
    "toc_unit",
]
