"""Provider-neutral semantic print document model.

A :class:`Document` is pure *content*: chapters made of blocks and inlines.
It has no page geometry, fonts or provider rules; layout (#6) and the renderer
(#7) decide how it looks. All nodes are immutable and comparable, so repeated
parses of the same manuscript are equal (see :func:`to_data`).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from printforge.diagnostics import Diagnostic

# ----------------------------------------------------------------- inlines


@dataclass(frozen=True, slots=True)
class Text:
    text: str


@dataclass(frozen=True, slots=True)
class Emphasis:
    children: tuple[Inline, ...]


@dataclass(frozen=True, slots=True)
class Strong:
    children: tuple[Inline, ...]


@dataclass(frozen=True, slots=True)
class Strikethrough:
    children: tuple[Inline, ...]


@dataclass(frozen=True, slots=True)
class InlineCode:
    text: str


@dataclass(frozen=True, slots=True)
class Link:
    """A hyperlink. ``href`` is ``None`` when the target was unsafe and dropped."""

    href: str | None
    children: tuple[Inline, ...]


@dataclass(frozen=True, slots=True)
class Image:
    """A local image. ``path`` is ``None`` if it could not be resolved (see diagnostics)."""

    source: str  # reference as written in Markdown
    path: Path | None  # resolved absolute path inside the book root
    alt: str
    relative_path: str | None = None  # POSIX path relative to the book root
    title: str | None = None


@dataclass(frozen=True, slots=True)
class LineBreak:
    pass


@dataclass(frozen=True, slots=True)
class SoftBreak:
    pass


Inline = (
    Text | Emphasis | Strong | Strikethrough | InlineCode | Link | Image | LineBreak | SoftBreak
)

# ----------------------------------------------------------------- blocks


@dataclass(frozen=True, slots=True)
class Heading:
    level: int  # Markdown level 1-6 within the chapter body
    children: tuple[Inline, ...]
    id: str  # stable, unique within the document
    line: int | None = None

    @property
    def text(self) -> str:
        return plain_text(self.children)


@dataclass(frozen=True, slots=True)
class Paragraph:
    children: tuple[Inline, ...]
    line: int | None = None


@dataclass(frozen=True, slots=True)
class Figure:
    """A paragraph consisting of a single image."""

    image: Image
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ListItem:
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class ListBlock:
    ordered: bool
    items: tuple[ListItem, ...]
    start: int = 1
    tight: bool = True
    line: int | None = None


@dataclass(frozen=True, slots=True)
class BlockQuote:
    blocks: tuple[Block, ...]
    line: int | None = None


@dataclass(frozen=True, slots=True)
class CodeBlock:
    text: str
    language: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ThematicBreak:
    line: int | None = None


class Align(StrEnum):
    NONE = ""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class TableCell:
    children: tuple[Inline, ...]
    align: Align = Align.NONE


@dataclass(frozen=True, slots=True)
class Table:
    header: tuple[tuple[TableCell, ...], ...]
    body: tuple[tuple[TableCell, ...], ...]
    line: int | None = None


Block = Heading | Paragraph | Figure | ListBlock | BlockQuote | CodeBlock | ThematicBreak | Table

# ----------------------------------------------------------------- structure


class ChapterKind(StrEnum):
    FRONT_MATTER = "front-matter"  # isFrontMatter: true
    CHAPTER = "chapter"
    APPENDIX = "appendix"  # slug or title starts with "appendix"
    BACK_MATTER = "back-matter"  # non-appendix chapters after the first appendix


@dataclass(frozen=True, slots=True)
class DocChapter:
    id: str  # stable anchor, e.g. "ch-1"
    slug: str
    title: str
    kind: ChapterKind
    source: str  # relative source path, e.g. "chapters/ch-1.md"
    blocks: tuple[Block, ...]
    number: int | float | None = None
    part_number: int | float | None = None
    part_title: str | None = None

    @property
    def headings(self) -> tuple[Heading, ...]:
        return tuple(_iter_headings(self.blocks))


@dataclass(frozen=True, slots=True)
class Document:
    title: str
    chapters: tuple[DocChapter, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def images(self) -> tuple[tuple[DocChapter, Image], ...]:
        found: list[tuple[DocChapter, Image]] = []
        for chapter in self.chapters:
            found.extend((chapter, image) for image in _iter_images(chapter.blocks))
        return tuple(found)


# ----------------------------------------------------------------- helpers


def plain_text(inlines: tuple[Inline, ...]) -> str:
    parts: list[str] = []
    for node in inlines:
        if isinstance(node, Text | InlineCode):
            parts.append(node.text)
        elif isinstance(node, Emphasis | Strong | Strikethrough | Link):
            parts.append(plain_text(node.children))
        elif isinstance(node, Image):
            parts.append(node.alt)
        elif isinstance(node, LineBreak | SoftBreak):
            parts.append(" ")
    return "".join(parts)


def _children_blocks(block: Block) -> tuple[Block, ...]:
    if isinstance(block, BlockQuote):
        return block.blocks
    if isinstance(block, ListBlock):
        return tuple(b for item in block.items for b in item.blocks)
    return ()


def _iter_headings(blocks: tuple[Block, ...]):
    for block in blocks:
        if isinstance(block, Heading):
            yield block
        yield from _iter_headings(_children_blocks(block))


def _iter_inline_images(inlines: tuple[Inline, ...]):
    for node in inlines:
        if isinstance(node, Image):
            yield node
        elif isinstance(node, Emphasis | Strong | Strikethrough | Link):
            yield from _iter_inline_images(node.children)


def _iter_images(blocks: tuple[Block, ...]):
    for block in blocks:
        if isinstance(block, Figure):
            yield block.image
        elif isinstance(block, Paragraph | Heading):
            yield from _iter_inline_images(block.children)
        elif isinstance(block, Table):
            for row in (*block.header, *block.body):
                for cell in row:
                    yield from _iter_inline_images(cell.children)
        yield from _iter_images(_children_blocks(block))


def to_data(node: Any, *, include_paths: bool = False) -> Any:
    """Plain, JSON-compatible representation (for snapshots and determinism tests).

    Absolute filesystem paths (``Image.path``) are machine-specific and omitted
    unless ``include_paths``; ``Image.relative_path`` is always kept.
    """
    if is_dataclass(node):
        data = {"type": type(node).__name__}
        for f in fields(node):
            if f.name == "path" and isinstance(node, Image) and not include_paths:
                continue
            data[f.name] = to_data(getattr(node, f.name), include_paths=include_paths)
        return data
    if isinstance(node, tuple | list):
        return [to_data(n, include_paths=include_paths) for n in node]
    if isinstance(node, StrEnum):
        return str(node)
    if isinstance(node, Path):
        return node.as_posix()
    return node
