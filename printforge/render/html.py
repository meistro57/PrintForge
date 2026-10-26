"""Semantic document -> HTML following the layout contract (printforge.layout.styles).

All text is HTML-escaped; nothing from the manuscript is ever emitted as markup.
Images are referenced by ``file://`` URIs of already-resolved local paths and
the set of those paths is returned so the renderer can allow exactly those.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from printforge.config.settings import LayoutSettings
from printforge.document.model import (
    Block,
    BlockQuote,
    ChapterKind,
    CodeBlock,
    DocChapter,
    Document,
    Emphasis,
    Figure,
    Heading,
    Image,
    Inline,
    InlineCode,
    LineBreak,
    Link,
    ListBlock,
    Paragraph,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    Text,
    ThematicBreak,
)
from printforge.errors import RenderError


def esc(text: str) -> str:
    return escape(text, quote=True)


@dataclass
class HtmlBuild:
    html: str
    assets: frozenset[Path]
    unit_ids: tuple[str, ...]  # ids of top-level units in order (sections)
    first_main_id: str | None


@dataclass
class _Writer:
    assets: set[Path] = field(default_factory=set)

    # ---------------------------------------------------------------- inlines
    def inlines(self, nodes: tuple[Inline, ...]) -> str:
        return "".join(self.inline(n) for n in nodes)

    def inline(self, node: Inline) -> str:
        if isinstance(node, Text):
            return esc(node.text)
        if isinstance(node, Emphasis):
            return f"<em>{self.inlines(node.children)}</em>"
        if isinstance(node, Strong):
            return f"<strong>{self.inlines(node.children)}</strong>"
        if isinstance(node, Strikethrough):
            return f"<del>{self.inlines(node.children)}</del>"
        if isinstance(node, InlineCode):
            return f"<code>{esc(node.text)}</code>"
        if isinstance(node, Link):
            inner = self.inlines(node.children)
            if node.href and (
                node.href.startswith("#") or node.href.startswith(("http://", "https://", "mailto:"))
            ):
                return f'<a href="{esc(node.href)}">{inner}</a>'
            return f"<span>{inner}</span>"
        if isinstance(node, Image):
            return self.image(node)
        if isinstance(node, LineBreak):
            return "<br>"
        if isinstance(node, SoftBreak):
            return "\n"
        raise RenderError(f"unsupported inline node {type(node).__name__}")  # pragma: no cover

    def image(self, image: Image) -> str:
        if image.path is None:
            raise RenderError(f"image {image.source!r} was not resolved; fix the image errors first")
        self.assets.add(image.path)
        title = f' title="{esc(image.title)}"' if image.title else ""
        return f'<img src="{esc(image.path.as_uri())}" alt="{esc(image.alt)}"{title}>'

    # ---------------------------------------------------------------- blocks
    def blocks(self, blocks: tuple[Block, ...]) -> str:
        return "\n".join(self.block(b) for b in blocks)

    def block(self, block: Block) -> str:
        if isinstance(block, Heading):
            level = min(block.level + 1, 6)  # chapter title is h1
            return f'<h{level} id="{esc(block.id)}">{self.inlines(block.children)}</h{level}>'
        if isinstance(block, Paragraph):
            return f"<p>{self.inlines(block.children)}</p>"
        if isinstance(block, Figure):
            caption = f"<figcaption>{esc(block.image.alt)}</figcaption>" if block.image.alt else ""
            return f"<figure>{self.image(block.image)}{caption}</figure>"
        if isinstance(block, ListBlock):
            tag = "ol" if block.ordered else "ul"
            start = f' start="{block.start}"' if block.ordered and block.start != 1 else ""
            items = "".join(f"<li>{self.blocks(item.blocks)}</li>" for item in block.items)
            return f"<{tag}{start}>{items}</{tag}>"
        if isinstance(block, BlockQuote):
            return f"<blockquote>{self.blocks(block.blocks)}</blockquote>"
        if isinstance(block, CodeBlock):
            lang = f' class="language-{esc(block.language)}"' if block.language else ""
            return f"<pre><code{lang}>{esc(block.text.rstrip(chr(10)))}</code></pre>"
        if isinstance(block, ThematicBreak):
            return '<hr class="pf-break">'
        if isinstance(block, Table):
            head = "".join(f"<tr>{self.cells(row, 'th')}</tr>" for row in block.header)
            body = "".join(f"<tr>{self.cells(row, 'td')}</tr>" for row in block.body)
            return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"
        raise RenderError(f"unsupported block {type(block).__name__}")  # pragma: no cover

    def cells(self, row: tuple[TableCell, ...], tag: str) -> str:
        out = []
        for cell in row:
            style = f' style="text-align: {cell.align.value}"' if cell.align.value else ""
            out.append(f"<{tag}{style}>{self.inlines(cell.children)}</{tag}>")
        return "".join(out)


def _opener(chapter: DocChapter, layout: LayoutSettings) -> str:
    label = ""
    if layout.chapter_label and chapter.kind is ChapterKind.CHAPTER and chapter.number is not None:
        number = int(chapter.number) if float(chapter.number).is_integer() else chapter.number
        label = f'<p class="pf-chapter-label">{esc(layout.chapter_label)} {esc(str(number))}</p>'
    title = f'<h1 class="pf-chapter-title" id="{esc(chapter.id)}">{esc(chapter.title)}</h1>'
    return f'<header class="pf-opener">{label}{title}</header>'


def part_id(number, title: str | None) -> str:
    from printforge.document.parse import slugify

    return "part-" + slugify(f"{number if number is not None else ''} {title or ''}")


def build_html(
    document: Document,
    layout: LayoutSettings,
    *,
    language: str,
    title: str,
    author: str,
    front_units: tuple[str, ...] = (),
    front_unit_ids: tuple[str, ...] = (),
) -> HtmlBuild:
    """Render ``document`` to contract HTML.

    ``front_units`` are pre-rendered ``<section>`` strings (title page, contents, ...)
    inserted before the manuscript's own front matter; see #8.
    """
    errors = [d for d in document.diagnostics if d.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{d.context}: {d.message}" for d in errors)
        raise RenderError(f"document has {len(errors)} error(s): {details}")

    writer = _Writer()
    units: list[str] = list(front_units)
    ids: list[str] = list(front_unit_ids)
    first_main: str | None = None
    previous_part: tuple | None = None
    for chapter in document.chapters:
        body = writer.blocks(chapter.blocks)
        if chapter.kind is ChapterKind.FRONT_MATTER:
            units.append(
                f'<section class="pf-front" id="sec-{esc(chapter.id)}">'
                f"{_opener(chapter, layout)}{body}</section>"
            )
            ids.append(f"sec-{chapter.id}")
            continue
        part = (chapter.part_number, chapter.part_title)
        if (
            layout.part_pages
            and chapter.part_title
            and chapter.kind is ChapterKind.CHAPTER
            and part != previous_part
        ):
            pid = part_id(*part)
            start = " pf-start" if first_main is None else ""
            first_main = first_main or pid
            units.append(
                f'<section class="pf-part{start}" id="sec-{pid}">'
                f'<h1 class="pf-part-title" id="{pid}">{esc(chapter.part_title)}</h1></section>'
            )
            ids.append(f"sec-{pid}")
        previous_part = part
        start = " pf-start" if first_main is None else ""
        first_main = first_main or chapter.id
        units.append(
            f'<section class="pf-chapter{start}" id="sec-{esc(chapter.id)}">'
            f"{_opener(chapter, layout)}{body}</section>"
        )
        ids.append(f"sec-{chapter.id}")

    html = (
        f'<!DOCTYPE html><html lang="{esc(language)}"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title>"
        f'<meta name="author" content="{esc(author)}"></head><body>\n'
        + "\n".join(units)
        + "\n</body></html>\n"
    )
    return HtmlBuild(html, frozenset(writer.assets), tuple(ids), first_main)
