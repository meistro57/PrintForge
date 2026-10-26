"""Typed print settings (``print.json`` schema version 1) and their validator.

The validator works on a fully merged plain-``dict`` (see
:mod:`printforge.config.resolve`) and either returns a :class:`PrintSettings` or
raises :class:`~printforge.errors.ConfigError` listing *every* problem, each with
its dotted field path and the layer (print.json, CLI, ...) that supplied it.
Invalid values are never silently corrected.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from printforge.errors import ConfigError
from printforge.units import Length, UnitError

SCHEMA_VERSION = 1


class Ink(StrEnum):
    BLACK = "black"
    STANDARD_COLOR = "standard-color"
    PREMIUM_COLOR = "premium-color"


class Paper(StrEnum):
    WHITE = "white"
    CREAM = "cream"
    GROUNDWOOD = "groundwood"


class Finish(StrEnum):
    MATTE = "matte"
    GLOSSY = "glossy"


class SpineText(StrEnum):
    AUTO = "auto"  # print spine text only when the provider allows it
    NEVER = "never"
    ALWAYS = "always"  # fail if the provider does not allow spine text


class Format(StrEnum):
    PAPERBACK = "paperback"


class ChapterStart(StrEnum):
    RECTO = "recto"  # chapters open on a right-hand (odd) page; blank verso inserted if needed
    ANY = "any"  # chapters open on the next page


class FolioPosition(StrEnum):
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_OUTSIDE = "bottom-outside"


class FrontFolios(StrEnum):
    LOWER_ROMAN = "lower-roman"
    NONE = "none"


# ----------------------------------------------------------------- models


@dataclass(frozen=True, slots=True)
class Trim:
    width: Length
    height: Length


@dataclass(frozen=True, slots=True)
class InteriorSettings:
    bleed: bool
    ink: Ink
    paper: Paper


@dataclass(frozen=True, slots=True)
class Margins:
    top: Length
    bottom: Length
    outside: Length
    inside: Length | None  # None = "auto": provider minimum gutter + gutter_extra
    gutter_extra: Length


@dataclass(frozen=True, slots=True)
class Typography:
    body_font: str
    heading_font: str
    mono_font: str
    font_size: Length
    line_height: Decimal  # multiple of font size
    paragraph_indent: Length
    justify: bool
    hyphenate: bool
    language: str


@dataclass(frozen=True, slots=True)
class ImageSettings:
    min_dpi: int


@dataclass(frozen=True, slots=True)
class TocSettings:
    enabled: bool
    depth: int  # 1 = chapters, 2 = + level-2 headings, 3 = + level-3 headings
    title: str
    include_front_matter: bool
    include_parts: bool


@dataclass(frozen=True, slots=True)
class FrontMatterSettings:
    half_title: bool
    title_page: bool
    copyright_page: bool


@dataclass(frozen=True, slots=True)
class Metadata:
    """Optional overrides/additions to book.json. Nothing here is ever invented."""

    title: str | None
    subtitle: str | None
    author: str | None
    description: str | None
    language: str | None
    isbn: str | None  # normalized digits (and X), checksum-validated
    publisher: str | None
    copyright_year: int | None
    copyright_holder: str | None
    edition: str | None


@dataclass(frozen=True, slots=True)
class CoverSettings:
    finish: Finish
    front_image: str | None  # relative to the config base directory
    back_image: str | None
    wrap_image: str | None  # a complete back+spine+front artwork
    spine_text: SpineText
    background_color: str
    text_color: str
    back_text: str | None


@dataclass(frozen=True, slots=True)
class LayoutSettings:
    chapter_start: ChapterStart
    part_pages: bool  # a divider page before each part
    running_heads: bool  # verso: book title, recto: chapter title
    folio_position: FolioPosition
    front_matter_folios: FrontFolios
    chapter_label: str | None  # e.g. "Chapter" -> "Chapter 3" above numbered chapter titles
    widows: int
    orphans: int


@dataclass(frozen=True, slots=True)
class OutputSettings:
    directory: str | None  # relative to the working directory; not in reproducible metadata


@dataclass(frozen=True, slots=True)
class PrintSettings:
    version: int
    provider: str
    format: Format
    trim: Trim
    interior: InteriorSettings
    margins: Margins
    typography: Typography
    images: ImageSettings
    toc: TocSettings
    front_matter: FrontMatterSettings
    metadata: Metadata
    cover: CoverSettings
    layout: LayoutSettings
    output: OutputSettings

    def to_dict(self) -> dict[str, Any]:
        data = _serialize(self)
        if self.margins.inside is None:
            data["margins"]["inside"] = "auto"
        return data


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {f.name: _serialize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Length):
        return value.to_str()
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return value


# ----------------------------------------------------------------- validation


class _Errors:
    def __init__(self, source_of: Callable[[str], str]) -> None:
        self.items: list[str] = []
        self.source_of = source_of

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{self.source_of(path)}: {path}: {message}")


Validator = Callable[[Any, str, _Errors], Any]
_INVALID = object()


def _length(minimum: str, maximum: str, *, optional: bool = False, auto: bool = False):
    lo, hi = Length.parse(minimum), Length.parse(maximum)

    def check(value: Any, path: str, errors: _Errors) -> Any:
        if value is None and optional:
            return None
        if auto and value == "auto":
            return None
        try:
            length = Length.parse(value)
        except UnitError as exc:
            errors.add(path, str(exc) + (" or 'auto'" if auto else ""))
            return _INVALID
        if not lo <= length <= hi:
            errors.add(path, f"must be between {lo} and {hi}, got {value!r}")
            return _INVALID
        return length

    return check


def _enum(enum: type[StrEnum]):
    def check(value: Any, path: str, errors: _Errors) -> Any:
        try:
            return enum(value)
        except ValueError:
            choices = ", ".join(e.value for e in enum)
            errors.add(path, f"must be one of: {choices} (got {value!r})")
            return _INVALID

    return check


def _bool(value: Any, path: str, errors: _Errors) -> Any:
    if not isinstance(value, bool):
        errors.add(path, f"must be true or false, got {value!r}")
        return _INVALID
    return value


def _int(minimum: int, maximum: int, *, optional: bool = False):
    def check(value: Any, path: str, errors: _Errors) -> Any:
        if value is None and optional:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            errors.add(path, f"must be an integer, got {value!r}")
            return _INVALID
        if not minimum <= value <= maximum:
            errors.add(path, f"must be between {minimum} and {maximum}, got {value}")
            return _INVALID
        return value

    return check


def _decimal(minimum: str, maximum: str):
    lo, hi = Decimal(minimum), Decimal(maximum)

    def check(value: Any, path: str, errors: _Errors) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            errors.add(path, f"must be a number, got {value!r}")
            return _INVALID
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            errors.add(path, f"must be a number, got {value!r}")
            return _INVALID
        if not lo <= number <= hi:
            errors.add(path, f"must be between {lo} and {hi}, got {value!r}")
            return _INVALID
        return number

    return check


def _text(*, optional: bool = False, pattern: str | None = None, hint: str = ""):
    regex = re.compile(pattern) if pattern else None

    def check(value: Any, path: str, errors: _Errors) -> Any:
        if value is None and optional:
            return None
        if not isinstance(value, str) or not value.strip():
            errors.add(path, f"must be a non-empty string, got {value!r}")
            return _INVALID
        if regex and not regex.fullmatch(value):
            errors.add(path, f"invalid value {value!r}{hint}")
            return _INVALID
        return value

    return check


def _choice(*choices: Any):
    def check(value: Any, path: str, errors: _Errors) -> Any:
        if value not in choices:
            errors.add(path, f"must be one of: {', '.join(map(str, choices))} (got {value!r})")
            return _INVALID
        return value

    return check


def _relative_path(value: Any, path: str, errors: _Errors) -> Any:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.add(path, f"must be a relative file path or null, got {value!r}")
        return _INVALID
    if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", value) or value.startswith("//"):
        errors.add(path, f"remote URLs are not allowed ({value!r}); use a local file")
        return _INVALID
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive:
        errors.add(path, f"must be relative to the print.json directory, got {value!r}")
        return _INVALID
    if ".." in PurePosixPath(value.replace("\\", "/")).parts:
        errors.add(path, f"must not contain '..' ({value!r})")
        return _INVALID
    return value


def normalize_isbn(raw: str) -> str | None:
    """Return digits-only ISBN-10/13 if the checksum is valid, else ``None``."""
    compact = re.sub(r"[\s-]", "", raw).upper()
    if re.fullmatch(r"\d{9}[\dX]", compact):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(compact))
        return compact if total % 11 == 0 else None
    if re.fullmatch(r"97[89]\d{10}", compact):
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(compact))
        return compact if total % 10 == 0 else None
    return None


def _isbn(value: Any, path: str, errors: _Errors) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.add(path, f"must be a string such as '978-1-23456-789-7', got {value!r}")
        return _INVALID
    normalized = normalize_isbn(value)
    if normalized is None:
        errors.add(path, f"{value!r} is not a valid ISBN-10/ISBN-13 (format or checksum)")
        return _INVALID
    return normalized


_COLOR = r"#[0-9A-Fa-f]{6}"
_LANG = r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*"

SCHEMA: dict[str, Any] = {
    "version": _choice(SCHEMA_VERSION),
    "provider": _text(),
    "format": _enum(Format),
    "trim": {"width": _length("1in", "20in"), "height": _length("1in", "20in")},
    "interior": {"bleed": _bool, "ink": _enum(Ink), "paper": _enum(Paper)},
    "margins": {
        "top": _length("0in", "3in"),
        "bottom": _length("0in", "3in"),
        "outside": _length("0in", "3in"),
        "inside": _length("0in", "3in", auto=True),
        "gutter_extra": _length("0in", "1in"),
    },
    "typography": {
        "body_font": _text(),
        "heading_font": _text(),
        "mono_font": _text(),
        "font_size": _length("6pt", "18pt"),
        "line_height": _decimal("1.0", "2.5"),
        "paragraph_indent": _length("0in", "1in"),
        "justify": _bool,
        "hyphenate": _bool,
        "language": _text(pattern=_LANG, hint=" (use a BCP 47 tag such as 'en' or 'en-US')"),
    },
    "images": {"min_dpi": _int(72, 2400)},
    "toc": {
        "enabled": _bool,
        "depth": _int(1, 3),
        "title": _text(),
        "include_front_matter": _bool,
        "include_parts": _bool,
    },
    "front_matter": {"half_title": _bool, "title_page": _bool, "copyright_page": _bool},
    "metadata": {
        "title": _text(optional=True),
        "subtitle": _text(optional=True),
        "author": _text(optional=True),
        "description": _text(optional=True),
        "language": _text(optional=True, pattern=_LANG, hint=" (use a BCP 47 tag such as 'en')"),
        "isbn": _isbn,
        "publisher": _text(optional=True),
        "copyright_year": _int(1400, 9999, optional=True),
        "copyright_holder": _text(optional=True),
        "edition": _text(optional=True),
    },
    "cover": {
        "finish": _enum(Finish),
        "front_image": _relative_path,
        "back_image": _relative_path,
        "wrap_image": _relative_path,
        "spine_text": _enum(SpineText),
        "background_color": _text(pattern=_COLOR, hint=" (use #RRGGBB)"),
        "text_color": _text(pattern=_COLOR, hint=" (use #RRGGBB)"),
        "back_text": _text(optional=True),
    },
    "layout": {
        "chapter_start": _enum(ChapterStart),
        "part_pages": _bool,
        "running_heads": _bool,
        "folio_position": _enum(FolioPosition),
        "front_matter_folios": _enum(FrontFolios),
        "chapter_label": _text(optional=True),
        "widows": _int(1, 5),
        "orphans": _int(1, 5),
    },
    "output": {"directory": _text(optional=True)},
}


def _walk(schema: dict[str, Any], data: Any, prefix: str, errors: _Errors) -> dict[str, Any]:
    if not isinstance(data, dict):
        errors.add(prefix or "(root)", f"must be an object, got {data!r}")
        return {}
    result: dict[str, Any] = {}
    for key in data:
        if key not in schema:
            path = f"{prefix}.{key}" if prefix else key
            close = difflib.get_close_matches(key, list(schema), n=1)
            errors.add(
                path, "unknown setting" + (f" (did you mean '{close[0]}'?)" if close else "")
            )
    for key, spec in schema.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in data:
            errors.add(path, "missing (internal defaults incomplete)")
            continue
        if isinstance(spec, dict):
            result[key] = _walk(spec, data[key], path, errors)
        else:
            result[key] = spec(data[key], path, errors)
    return result


def validate(merged: dict[str, Any], source_of: Callable[[str], str]) -> PrintSettings:
    """Validate a merged settings dict. ``source_of(path)`` names the layer for errors."""
    errors = _Errors(source_of)
    clean = _walk(SCHEMA, merged, "", errors)

    if not errors.items:
        _cross_checks(clean, errors)
    if errors.items:
        raise ConfigError(
            "invalid print settings:\n  - " + "\n  - ".join(errors.items),
            hint="see docs/PRINT_JSON.md for every setting and its allowed values",
        )

    return PrintSettings(
        version=clean["version"],
        provider=clean["provider"],
        format=clean["format"],
        trim=Trim(**clean["trim"]),
        interior=InteriorSettings(**clean["interior"]),
        margins=Margins(**clean["margins"]),
        typography=Typography(**clean["typography"]),
        images=ImageSettings(**clean["images"]),
        toc=TocSettings(**clean["toc"]),
        front_matter=FrontMatterSettings(**clean["front_matter"]),
        metadata=Metadata(**clean["metadata"]),
        cover=CoverSettings(**clean["cover"]),
        layout=LayoutSettings(**clean["layout"]),
        output=OutputSettings(**clean["output"]),
    )


def _cross_checks(clean: dict[str, Any], errors: _Errors) -> None:
    trim, margins, cover = clean["trim"], clean["margins"], clean["cover"]
    if margins["top"] + margins["bottom"] >= trim["height"] * Decimal("0.5"):
        errors.add("margins.top", "top + bottom margins leave less than half the page height")
    inside = margins["inside"] if margins["inside"] is not None else margins["gutter_extra"]
    if inside + margins["outside"] >= trim["width"] * Decimal("0.5"):
        errors.add("margins.outside", "inside + outside margins leave less than half the width")
    if cover["wrap_image"] and (cover["front_image"] or cover["back_image"]):
        errors.add(
            "cover.wrap_image",
            "a full wrap image cannot be combined with front_image/back_image; choose one",
        )
    if cover["back_image"] and not cover["front_image"]:
        errors.add("cover.back_image", "back_image requires front_image (or use wrap_image)")
    if not clean["toc"]["enabled"] and clean["toc"]["include_front_matter"]:
        errors.add("toc.include_front_matter", "set toc.enabled to true or remove this option")
