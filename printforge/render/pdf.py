"""PDF normalization and inspection helpers.

Rendering a PDF is not reproducible out of the box: the font subsetter records
the current time in the ``head.modified`` field of every embedded font. These
helpers rewrite embedded fonts with a fixed timestamp and write the document
information dictionary from an explicit mapping, so repeated builds of the same
input are byte-identical.

pypdf and fontTools are imported inside the functions, so ``printforge.render``
stays importable without the native rendering stack.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from printforge.errors import RenderError
from printforge.providers.base import PageSize
from printforge.units import Length

#: Fixed ``head.modified`` value for embedded fonts (seconds since 1904-01-01).
#: Zero is the sfnt epoch, so the normalized font has no wall-clock dependency.
FIXED_FONT_TIMESTAMP = 0

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True, slots=True)
class EmbeddedFont:
    """One font referenced by a page, with its embedding details."""

    name: str  # BaseFont as written, e.g. "ABCDEF+DejaVu-Serif"
    base_name: str  # without the subset prefix
    subset: bool  # six-letter subset prefix present
    font_file: str | None  # "/FontFile2", "/FontFile3", "/FontFile" or None

    @property
    def embedded(self) -> bool:
        return self.font_file is not None


@dataclass(frozen=True, slots=True)
class PdfFacts:
    """What a finished interior PDF actually contains."""

    page_count: int
    size: PageSize
    page_sizes: tuple[PageSize, ...]
    text_pages: tuple[str, ...]
    fonts: tuple[EmbeddedFont, ...]
    encrypted: bool
    metadata: dict[str, str]

    @property
    def text(self) -> str:
        return "\n".join(self.text_pages)


def normalize_pdf(pdf_bytes: bytes, info: Mapping[str, str]) -> bytes:
    """Return a reproducible copy of ``pdf_bytes`` with normalized metadata.

    ``info`` becomes the PDF information dictionary (``/Title``, ``/Author``,
    ...). Every embedded font program is rewritten with a fixed modification
    timestamp, which is what makes otherwise identical builds differ byte-wise.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    for stream in _font_streams(reader):
        stream.set_data(_reproducible_font(stream.get_data()))
    writer = PdfWriter(clone_from=reader)
    writer.add_metadata({f"/{key.lstrip('/')}": value for key, value in info.items()})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def read_pdf(pdf_bytes: bytes) -> PdfFacts:
    """Inspect a finished PDF: page count, page size, text, fonts, metadata."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    if not reader.pages:
        raise RenderError("rendered PDF has no pages")
    sizes = tuple(_page_size(page) for page in reader.pages)
    size = sizes[0]
    metadata: dict[str, str] = {}
    for key, value in (reader.metadata or {}).items():
        metadata[str(key)] = str(value)
    fonts: list[EmbeddedFont] = []
    seen: set[str] = set()
    for page in reader.pages:
        for font in _page_fonts(page):
            if font.name not in seen:
                seen.add(font.name)
                fonts.append(font)
    return PdfFacts(
        page_count=len(reader.pages),
        size=size,
        page_sizes=sizes,
        text_pages=tuple(page.extract_text() or "" for page in reader.pages),
        fonts=tuple(fonts),
        encrypted=bool(reader.is_encrypted),
        metadata=metadata,
    )


# ---------------------------------------------------------------- internals


def _page_size(page: Any) -> PageSize:
    box = page.mediabox
    return PageSize(Length.pt(str(box.width)), Length.pt(str(box.height)))


def _reproducible_font(data: bytes) -> bytes:
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    except Exception as exc:  # fontTools raises several unrelated types
        raise RenderError(
            f"cannot normalize an embedded font program: {exc}",
            hint="use a TrueType or OpenType (CFF) font; reproducible builds need it",
        ) from exc
    if "head" not in font:
        raise RenderError(
            "cannot normalize an embedded font program without a 'head' table",
            hint="use a TrueType or OpenType (CFF) font; reproducible builds need it",
        )
    font.recalcTimestamp = False
    font["head"].modified = FIXED_FONT_TIMESTAMP
    output = io.BytesIO()
    font.save(output, reorderTables=True)
    return output.getvalue()


def _font_streams(reader: Any):
    """Yield each embedded font program stream exactly once."""
    seen: set[int] = set()
    for page in reader.pages:
        for descriptor in _font_descriptors(page):
            for key in ("/FontFile2", "/FontFile3", "/FontFile"):
                stream = descriptor.get(key)
                if stream is None:
                    continue
                stream = stream.get_object()
                if id(stream) in seen:
                    continue
                seen.add(id(stream))
                yield stream


def _font_descriptors(page: Any):
    resources = page.get("/Resources")
    if resources is None:
        return
    fonts = resources.get_object().get("/Font")
    if fonts is None:
        return
    for reference in fonts.get_object().values():
        font = reference.get_object()
        candidates = [font]
        candidates.extend(item.get_object() for item in font.get("/DescendantFonts", []))
        for candidate in candidates:
            descriptor = candidate.get("/FontDescriptor")
            if descriptor is not None:
                yield descriptor.get_object()


def _page_fonts(page: Any) -> list[EmbeddedFont]:
    found: list[EmbeddedFont] = []
    resources = page.get("/Resources")
    if resources is None:
        return found
    fonts = resources.get_object().get("/Font")
    if fonts is None:
        return found
    for reference in fonts.get_object().values():
        font = reference.get_object()
        raw = str(font.get("/BaseFont", "")).lstrip("/")
        descriptor = font.get("/FontDescriptor")
        if descriptor is None:
            descendants = font.get("/DescendantFonts", [])
            if descendants:
                descriptor = descendants[0].get_object().get("/FontDescriptor")
        descriptor = descriptor.get_object() if descriptor is not None else None
        font_file = None
        if descriptor is not None:
            for key in ("/FontFile2", "/FontFile3", "/FontFile"):
                if key in descriptor:
                    font_file = key
                    break
        found.append(
            EmbeddedFont(
                name=raw,
                base_name=_SUBSET_PREFIX.sub("", raw),
                subset=bool(_SUBSET_PREFIX.match(raw)),
                font_file=font_file,
            )
        )
    return found


__all__ = [
    "FIXED_FONT_TIMESTAMP",
    "EmbeddedFont",
    "PdfFacts",
    "normalize_pdf",
    "read_pdf",
]
