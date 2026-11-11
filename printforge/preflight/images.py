"""Measure raster images actually drawn by a PDF.

WeasyPrint places every image XObject in each page's resource dictionary, so
listing resources would report one image dozens of times. This module walks the
page content streams instead, tracks the graphics state (``q`` / ``Q`` / ``cm``)
and records each ``Do`` that paints an image, giving the real printed size and
therefore the effective print resolution.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from printforge.units import Length

#: Guard against pathological (or malicious) Form XObject nesting.
_MAX_FORM_DEPTH = 8

_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PlacedImage:
    """One raster image painted on one page, with its printed size."""

    page: int  # 1-based physical page number
    name: str  # resource name, e.g. "/Im1"
    width_px: int
    height_px: int
    width: Length  # printed size on the page
    height: Length

    @property
    def dpi(self) -> float:
        """Lowest effective resolution across both axes."""
        width_in = float(self.width.exact_inches)
        height_in = float(self.height.exact_inches)
        if width_in <= 0 or height_in <= 0:
            return 0.0
        return min(self.width_px / width_in, self.height_px / height_in)

    def size_text(self) -> str:
        return f"{self.width.to_str('in', 3)} x {self.height.to_str('in', 3)}"


def placed_images(pdf_bytes: bytes) -> tuple[PlacedImage, ...]:
    """Return every image painted by ``pdf_bytes``, ordered by page then stream."""
    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    reader = PdfReader(io.BytesIO(pdf_bytes))
    found: list[PlacedImage] = []
    for index, page in enumerate(reader.pages, start=1):
        contents = page.get_contents()
        if contents is None:
            continue
        resources = page.get("/Resources")
        resources = resources.get_object() if resources is not None else None
        _scan(ContentStream(contents, reader), resources, index, found, 0)
    return tuple(found)


def _scan(
    stream: Any,
    resources: Any,
    page: int,
    found: list[PlacedImage],
    depth: int,
) -> None:
    if depth > _MAX_FORM_DEPTH:
        return
    ctm = _IDENTITY
    stack: list[tuple[float, ...]] = []
    for operands, operator in stream.operations:
        name = operator.decode("ascii", "replace") if isinstance(operator, bytes) else operator
        if name == "q":
            stack.append(ctm)
        elif name == "Q":
            if stack:
                ctm = stack.pop()
        elif name == "cm" and len(operands) == 6:
            ctm = _multiply(ctm, tuple(float(value) for value in operands))
        elif name == "Do" and operands:
            _paint(operands[0], resources, ctm, page, found, depth)


def _paint(
    name: Any,
    resources: Any,
    ctm: tuple[float, ...],
    page: int,
    found: list[PlacedImage],
    depth: int,
) -> None:
    from pypdf.generic import ContentStream

    xobject = _xobject(resources, name)
    if xobject is None:
        return
    subtype = xobject.get("/Subtype")
    if subtype == "/Image":
        width_px = _int(xobject.get("/Width"))
        height_px = _int(xobject.get("/Height"))
        if width_px <= 0 or height_px <= 0:
            return
        width_pt = (ctm[0] ** 2 + ctm[1] ** 2) ** 0.5
        height_pt = (ctm[2] ** 2 + ctm[3] ** 2) ** 0.5
        found.append(
            PlacedImage(
                page=page,
                name=str(name),
                width_px=width_px,
                height_px=height_px,
                width=Length.pt(str(width_pt)),
                height=Length.pt(str(height_pt)),
            )
        )
    elif subtype == "/Form" and depth < _MAX_FORM_DEPTH:
        form_resources = xobject.get("/Resources") or resources
        _scan(
            ContentStream(xobject, None),
            form_resources.get_object(),
            page,
            found,
            depth + 1,
        )


def _xobject(resources: Any, name: Any) -> Any:
    if resources is None:
        return None
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return None
    reference = xobjects.get_object().get(name)
    return reference.get_object() if reference is not None else None


def _multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = ["PlacedImage", "placed_images"]
