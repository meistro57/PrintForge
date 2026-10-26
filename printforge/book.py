"""Canonical, provider-neutral Book and Chapter models.

These are produced by an importer (see :mod:`printforge.importer`) and are
immutable: nothing downstream may write back to the manuscript source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from printforge.diagnostics import Diagnostic

Number = int | float


@dataclass(frozen=True, slots=True)
class Chapter:
    """One ``chapters/*.md`` file: parsed front matter plus raw Markdown body."""

    source_path: Path  # absolute path of the source file (never written)
    relative_path: str  # POSIX path relative to the book root, e.g. "chapters/ch-1.md"
    title: str
    order: Number
    slug: str  # front-matter slug, else the filename stem
    body: str  # raw Markdown body, front matter removed, newlines normalized to \n
    body_start_line: int  # 1-based line of the source file where ``body`` starts
    chapter_number: Number | None = None
    part_number: Number | None = None
    part_title: str | None = None
    is_front_matter: bool = False
    description: str | None = None
    front_matter: dict[str, Any] = field(default_factory=dict)  # as parsed, for provenance
    sha256: str = ""  # hash of the source bytes

    @property
    def filename(self) -> str:
        return self.source_path.name

    @property
    def directory(self) -> Path:
        return self.source_path.parent


@dataclass(frozen=True, slots=True)
class Part:
    """A run of consecutive chapters sharing the same part number/title."""

    number: Number | None
    title: str | None
    chapters: tuple[Chapter, ...]


@dataclass(frozen=True, slots=True)
class Book:
    """A manuscript: ``book.json`` metadata and chapters in reading order."""

    root: Path  # absolute book directory (contains book.json)
    slug: str
    title: str
    author: str
    chapters: tuple[Chapter, ...]
    subtitle: str | None = None
    description: str | None = None
    order: Number = 999
    badge: str | None = None
    # BookForge's ``cover`` / ``ogImage`` are *web* asset URLs resolved against the
    # site's public/ directory, not files inside the book. Kept for provenance only;
    # print cover artwork is configured in print.json.
    web_cover: str | None = None
    web_og_image: str | None = None
    ignored_fields: tuple[str, ...] = ()  # web-only fields present but unused (theme, ...)
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata_sha256: str = ""

    def parts(self) -> list[Part]:
        """Group chapters into consecutive runs by (part number, part title).

        Chapters without part metadata (e.g. front matter) form runs with
        ``number=None``/``title=None``; order is never changed.
        """
        groups: list[Part] = []
        current: list[Chapter] = []
        key: tuple[Number | None, str | None] | None = None
        for chapter in self.chapters:
            chapter_key = (chapter.part_number, chapter.part_title)
            if current and chapter_key != key:
                groups.append(Part(key[0], key[1], tuple(current)))  # type: ignore[index]
                current = []
            key = chapter_key
            current.append(chapter)
        if current:
            groups.append(Part(key[0], key[1], tuple(current)))  # type: ignore[index]
        return groups

    @property
    def front_matter(self) -> tuple[Chapter, ...]:
        return tuple(c for c in self.chapters if c.is_front_matter)

    @property
    def main_matter(self) -> tuple[Chapter, ...]:
        return tuple(c for c in self.chapters if not c.is_front_matter)
