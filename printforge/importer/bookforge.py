"""Read-only importer for the BookForge manuscript convention.

Mirrors BookForge's ``src/content.config.ts`` (checked 2026-10-26)::

    <book>/book.json          slug, title, author (required); subtitle, description,
                              badge, cover, ogImage (optional strings); order (default 999);
                              theme, audiobook (web-only, ignored for print)
    <book>/chapters/*.md      front matter: title (str), order (number) required;
                              chapterNumber, partNumber (number|null), partTitle (str|null),
                              description (str), isFrontMatter (bool, default false),
                              slug (str) optional

Files are only ever opened for reading. Chapter order: ascending numeric
``order``; ties are broken by a natural sort of the filename (``ch-2.md`` before
``ch-10.md``) and reported as ``IMPORT-DUP-ORDER`` warnings.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from printforge.book import Book, Chapter, Number
from printforge.diagnostics import Diagnostics, Severity
from printforge.errors import InputError
from printforge.importer.frontmatter import decode_source, split_front_matter
from printforge.log import get_logger

log = get_logger("importer")

BOOKS_SUBDIR = Path("src/content/books")
WEB_ONLY_BOOK_FIELDS = ("theme", "audiobook")
KNOWN_BOOK_FIELDS = {
    "slug",
    "title",
    "author",
    "subtitle",
    "description",
    "badge",
    "cover",
    "ogImage",
    "order",
    *WEB_ONLY_BOOK_FIELDS,
}
KNOWN_CHAPTER_FIELDS = {
    "title",
    "chapterNumber",
    "partNumber",
    "partTitle",
    "description",
    "order",
    "isFrontMatter",
    "slug",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Natural sort key: digit runs compare numerically (``ch-2`` < ``ch-10``)."""
    parts = re.split(r"(\d+)", name.casefold())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def _read_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror or exc}") from exc


# --------------------------------------------------------------------- book.json


def _load_book_json(path: Path) -> tuple[dict[str, Any], str]:
    data = _read_bytes(path)
    text = decode_source(data, str(path))
    try:
        meta = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}",
            hint="validate book.json with a JSON linter",
        ) from exc
    if not isinstance(meta, dict):
        raise InputError(f"{path}: book.json must contain a JSON object")
    return meta, hashlib.sha256(data).hexdigest()


def _require_str(meta: dict[str, Any], key: str, label: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        found = "missing" if key not in meta else f"got {type(value).__name__} {value!r}"
        raise InputError(f"{label}: required field '{key}' must be a non-empty string ({found})")
    return value


def _optional_str(meta: dict[str, Any], key: str, label: str) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(
            f"{label}: field '{key}' must be a string, got {type(value).__name__} {value!r}"
        )
    return value


# --------------------------------------------------------------------- chapters


def _field_error(label: str, key_lines: dict[str, int], key: str, message: str) -> InputError:
    line = key_lines.get(key, 1)
    return InputError(f"{label}:{line}: front matter '{key}' {message}")


def _parse_chapter(path: Path, root: Path) -> Chapter:
    relative = path.relative_to(root).as_posix()
    data = _read_bytes(path)
    split = split_front_matter(decode_source(data, relative), relative)
    fm, lines = split.front_matter, split.key_lines

    title = fm.get("title")
    if not isinstance(title, str) or not title.strip():
        if "title" not in fm:
            raise InputError(f"{relative}:1: front matter is missing required 'title'")
        raise _field_error(relative, lines, "title", f"must be a non-empty string, got {title!r}")

    order = fm.get("order")
    if "order" not in fm:
        raise InputError(
            f"{relative}:1: front matter is missing required 'order'",
            hint="BookForge sorts chapters by the numeric 'order' field",
        )
    if not _is_number(order):
        raise _field_error(relative, lines, "order", f"must be a number, got {order!r}")

    def optional_number(key: str) -> Number | None:
        value = fm.get(key)
        if value is None:
            return None
        if not _is_number(value):
            raise _field_error(relative, lines, key, f"must be a number or null, got {value!r}")
        return value

    def optional_text(key: str) -> str | None:
        value = fm.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise _field_error(relative, lines, key, f"must be a string or null, got {value!r}")
        return value

    is_front = fm.get("isFrontMatter", False)
    if is_front is None:
        is_front = False
    if not isinstance(is_front, bool):
        raise _field_error(
            relative, lines, "isFrontMatter", f"must be true/false, got {is_front!r}"
        )

    slug = optional_text("slug") or path.stem
    return Chapter(
        source_path=path,
        relative_path=relative,
        title=title,
        order=order,
        slug=slug,
        body=split.body,
        body_start_line=split.body_start_line,
        chapter_number=optional_number("chapterNumber"),
        part_number=optional_number("partNumber"),
        part_title=optional_text("partTitle"),
        is_front_matter=is_front,
        description=optional_text("description"),
        front_matter=fm,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _check_chapters(chapters: list[Chapter], diags: Diagnostics) -> None:
    by_order: dict[Number, list[Chapter]] = {}
    by_slug: dict[str, list[Chapter]] = {}
    by_number: dict[Number, list[Chapter]] = {}
    for chapter in chapters:
        by_order.setdefault(chapter.order, []).append(chapter)
        by_slug.setdefault(chapter.slug, []).append(chapter)
        if chapter.chapter_number is not None and not chapter.is_front_matter:
            by_number.setdefault(chapter.chapter_number, []).append(chapter)
        unknown = sorted(set(chapter.front_matter) - KNOWN_CHAPTER_FIELDS)
        if unknown:
            diags.add(
                Severity.INFO,
                "IMPORT-UNKNOWN-FIELD",
                f"front matter field(s) not used for print: {', '.join(unknown)}",
                context=chapter.relative_path,
            )
        if not chapter.body.strip():
            diags.add(
                Severity.WARNING,
                "IMPORT-EMPTY-CHAPTER",
                "chapter body is empty",
                context=chapter.relative_path,
            )

    duplicate_slugs = {s: cs for s, cs in by_slug.items() if len(cs) > 1}
    if duplicate_slugs:
        details = "; ".join(
            f"{slug!r}: {', '.join(c.relative_path for c in cs)}"
            for slug, cs in sorted(duplicate_slugs.items())
        )
        raise InputError(
            f"duplicate chapter slugs make chapters ambiguous: {details}",
            hint="give each chapter a unique 'slug' in its front matter",
        )

    for order, group in sorted(by_order.items()):
        if len(group) > 1:
            names = ", ".join(c.relative_path for c in group)
            diags.add(
                Severity.WARNING,
                "IMPORT-DUP-ORDER",
                f"{len(group)} chapters share order {order}; using filename order: {names}",
                suggestion="give each chapter a distinct 'order' value",
            )
    for number, group in sorted(by_number.items()):
        if len(group) > 1:
            names = ", ".join(c.relative_path for c in group)
            diags.add(
                Severity.WARNING,
                "IMPORT-DUP-CHAPTER-NUMBER",
                f"chapterNumber {number} is used by {len(group)} chapters: {names}",
            )


def load_book(book_dir: Path) -> Book:
    """Import one BookForge book directory (``book.json`` + ``chapters/*.md``)."""
    book_dir = Path(book_dir)
    if not book_dir.exists():
        raise InputError(f"book directory does not exist: {book_dir}")
    if not book_dir.is_dir():
        raise InputError(f"not a directory: {book_dir}")
    root = book_dir.resolve()
    book_json = root / "book.json"
    if not book_json.is_file():
        raise InputError(
            f"no book.json in {book_dir}",
            hint="point at a BookForge book directory, e.g. src/content/books/<slug>",
        )

    meta, meta_hash = _load_book_json(book_json)
    label = f"{book_dir}/book.json"
    diags = Diagnostics()
    slug = _require_str(meta, "slug", label)
    title = _require_str(meta, "title", label)
    author = _require_str(meta, "author", label)
    order = meta.get("order", 999)
    if order is None:
        order = 999
    if not _is_number(order):
        raise InputError(f"{label}: field 'order' must be a number, got {order!r}")
    if slug != root.name:
        diags.add(
            Severity.INFO,
            "IMPORT-SLUG-DIR",
            f"book.json slug {slug!r} differs from directory name {root.name!r}",
            context=label,
        )
    ignored = tuple(k for k in WEB_ONLY_BOOK_FIELDS if k in meta)
    unknown = sorted(set(meta) - KNOWN_BOOK_FIELDS)
    if unknown:
        diags.add(
            Severity.INFO,
            "IMPORT-UNKNOWN-FIELD",
            f"book.json field(s) not used for print: {', '.join(unknown)}",
            context=label,
        )

    chapters_dir = root / "chapters"
    if not chapters_dir.is_dir():
        raise InputError(f"no chapters/ directory in {book_dir}")
    paths = sorted(
        (p for p in chapters_dir.glob("*.md") if p.is_file()), key=lambda p: natural_key(p.name)
    )
    if not paths:
        raise InputError(f"no chapter files matching chapters/*.md in {book_dir}")

    chapters = [_parse_chapter(p, root) for p in paths]
    # Stable sort: equal `order` keeps natural filename order (the documented tie-breaker).
    chapters.sort(key=lambda c: c.order)
    _check_chapters(chapters, diags)

    book = Book(
        root=root,
        slug=slug,
        title=title,
        author=author,
        chapters=tuple(chapters),
        subtitle=_optional_str(meta, "subtitle", label),
        description=_optional_str(meta, "description", label),
        order=order,
        badge=_optional_str(meta, "badge", label),
        web_cover=_optional_str(meta, "cover", label),
        web_og_image=_optional_str(meta, "ogImage", label),
        ignored_fields=ignored,
        diagnostics=tuple(diags),
        metadata_sha256=meta_hash,
    )
    log.debug("imported %s: %d chapters", slug, len(chapters))
    return book


def discover_books(root: Path) -> list[Path]:
    """Find book directories under a BookForge checkout (or its books directory).

    Accepts either the repository root (searches ``src/content/books/**/book.json``,
    as BookForge does) or any directory to search directly. Returns directories
    sorted by path.
    """
    root = Path(root)
    if not root.is_dir():
        raise InputError(f"not a directory: {root}")
    base = root / BOOKS_SUBDIR if (root / BOOKS_SUBDIR).is_dir() else root
    return sorted(p.parent for p in base.glob("**/book.json") if p.is_file())


class BookForgeImporter:
    """:class:`printforge.interfaces.BookImporter` for the BookForge convention."""

    def load(self, book_dir: Path) -> Book:
        return load_book(book_dir)
