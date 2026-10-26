"""Markdown (CommonMark + tables + strikethrough) -> semantic :class:`Document`.

Safety policy:

* **Raw HTML is never passed through.** Inline/block HTML is printed literally as
  text (``DOC-RAW-HTML`` warning). The only interpreted subset is ``<br>`` (line
  break) and HTML comments (dropped, ``DOC-HTML-COMMENT`` info).
* **No remote assets.** Images must be local files inside the book root; remote,
  absolute, escaping or missing images produce ``ERROR`` diagnostics and an
  unresolved :class:`Image` (``path=None``). Nothing is ever fetched.
* Links keep only ``http``, ``https``, ``mailto`` and in-document ``#`` targets;
  other schemes (``javascript:``, ``file:``, ...) are dropped to plain text.
* Punctuation and Unicode are preserved exactly (no "smart quotes" rewriting).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token

from printforge.book import Book, Chapter
from printforge.diagnostics import Diagnostics, Severity
from printforge.document.model import (
    Align,
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
    ListItem,
    Paragraph,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    Text,
    ThematicBreak,
    plain_text,
)
from printforge.errors import InputError
from printforge.importer.paths import UnsafePathError, resolve_local_asset

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:")
_BR = re.compile(r"^<br\s*/?>$", re.IGNORECASE)
_COMMENT = re.compile(r"^\s*<!--.*?-->\s*$", re.DOTALL)
_UNDEFINED_REF_IMAGE = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")


def _markdown() -> MarkdownIt:
    # html=True only so raw HTML arrives as html_* tokens we can neutralize and
    # report; it is never emitted as markup.
    md = MarkdownIt("commonmark", {"html": True, "typographer": False, "linkify": False})
    md.enable(["table", "strikethrough"])
    return md


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or "section"


def chapter_kind(chapter: Chapter, after_appendix: bool) -> ChapterKind:
    if chapter.is_front_matter:
        return ChapterKind.FRONT_MATTER
    if chapter.slug.lower().startswith("appendix") or chapter.title.lower().startswith("appendix"):
        return ChapterKind.APPENDIX
    if after_appendix:
        return ChapterKind.BACK_MATTER
    return ChapterKind.CHAPTER


class _ChapterParser:
    def __init__(self, book: Book, chapter: Chapter, ids: set[str], diags: Diagnostics) -> None:
        self.book = book
        self.chapter = chapter
        self.ids = ids
        self.diags = diags

    # ------------------------------------------------------------ utilities
    def line(self, token: Token) -> int | None:
        if token.map is None:
            return None
        return self.chapter.body_start_line + token.map[0]

    def where(self, token: Token | None = None) -> str:
        line = self.line(token) if token is not None else None
        return f"{self.chapter.relative_path}:{line}" if line else self.chapter.relative_path

    def unique_id(self, base: str) -> str:
        candidate, n = base, 2
        while candidate in self.ids:
            candidate = f"{base}-{n}"
            n += 1
        self.ids.add(candidate)
        return candidate

    # ------------------------------------------------------------ blocks
    def blocks(self, tokens: list[Token], start: int, end: int) -> tuple[Block, ...]:
        out: list[Block] = []
        i = start
        while i < end:
            tok = tokens[i]
            t = tok.type
            if t == "heading_open":
                close = self._close(tokens, i)
                children = self.inlines(tokens[i + 1], tok)
                level = int(tok.tag[1])
                text = plain_text(children)
                hid = self.unique_id(f"{self.chapter.slug}--{slugify(text)}")
                if not text.strip():
                    self.diags.add(
                        Severity.WARNING,
                        "DOC-EMPTY-HEADING",
                        "empty heading",
                        context=self.where(tok),
                    )
                out.append(Heading(level, children, hid, self.line(tok)))
                i = close + 1
            elif t == "paragraph_open":
                close = self._close(tokens, i)
                children = self.inlines(tokens[i + 1], tok)
                if len(children) == 1 and isinstance(children[0], Image):
                    out.append(Figure(children[0], self.line(tok)))
                elif children:
                    out.append(Paragraph(children, self.line(tok)))
                i = close + 1
            elif t in ("bullet_list_open", "ordered_list_open"):
                close = self._close(tokens, i)
                items: list[ListItem] = []
                tight = True
                j = i + 1
                while j < close:
                    item_close = self._close(tokens, j)
                    for k in range(j + 1, item_close):
                        if tokens[k].type == "paragraph_open" and not tokens[k].hidden:
                            tight = False
                    items.append(ListItem(self.blocks(tokens, j + 1, item_close)))
                    j = item_close + 1
                start_attr = tok.attrGet("start")
                out.append(
                    ListBlock(
                        ordered=t == "ordered_list_open",
                        items=tuple(items),
                        start=int(start_attr) if start_attr is not None else 1,
                        tight=tight,
                        line=self.line(tok),
                    )
                )
                i = close + 1
            elif t == "blockquote_open":
                close = self._close(tokens, i)
                out.append(BlockQuote(self.blocks(tokens, i + 1, close), self.line(tok)))
                i = close + 1
            elif t in ("fence", "code_block"):
                language = tok.info.strip().split()[0] if tok.info.strip() else None
                out.append(CodeBlock(tok.content, language, self.line(tok)))
                i += 1
            elif t == "hr":
                out.append(ThematicBreak(self.line(tok)))
                i += 1
            elif t == "html_block":
                block = self._html_block(tok)
                if block is not None:
                    out.append(block)
                i += 1
            elif t == "table_open":
                close = self._close(tokens, i)
                out.append(self._table(tokens, i, close))
                i = close + 1
            else:  # pragma: no cover - every CommonMark block type is handled above
                raise InputError(f"{self.where(tok)}: unsupported Markdown construct {t!r}")
        return tuple(out)

    @staticmethod
    def _close(tokens: list[Token], i: int) -> int:
        depth = 0
        for j in range(i, len(tokens)):
            depth += tokens[j].nesting
            if depth == 0:
                return j
        raise InputError("unbalanced Markdown token stream")  # pragma: no cover

    def _html_block(self, tok: Token) -> Block | None:
        if _COMMENT.match(tok.content):
            self.diags.add(
                Severity.INFO,
                "DOC-HTML-COMMENT",
                "HTML comment omitted from print",
                context=self.where(tok),
            )
            return None
        self.diags.add(
            Severity.WARNING,
            "DOC-RAW-HTML",
            "raw HTML block is printed literally, not interpreted",
            context=self.where(tok),
            suggestion="replace the HTML with Markdown",
        )
        return Paragraph((Text(tok.content.rstrip("\n")),), self.line(tok))

    def _table(self, tokens: list[Token], start: int, end: int) -> Table:
        header: list[tuple[TableCell, ...]] = []
        body: list[tuple[TableCell, ...]] = []
        section = header
        row: list[TableCell] = []
        i = start + 1
        while i < end:
            tok = tokens[i]
            if tok.type == "thead_open":
                section = header
            elif tok.type == "tbody_open":
                section = body
            elif tok.type == "tr_open":
                row = []
            elif tok.type == "tr_close":
                section.append(tuple(row))
            elif tok.type in ("th_open", "td_open"):
                style = str(tok.attrGet("style") or "")
                align = Align.NONE
                match = re.search(r"text-align:\s*(left|center|right)", style)
                if match:
                    align = Align(match.group(1))
                row.append(TableCell(self.inlines(tokens[i + 1], tok), align))
                i += 2  # skip inline token; *_close handled by loop
            i += 1
        return Table(tuple(header), tuple(body), self.line(tokens[start]))

    # ------------------------------------------------------------ inlines
    def inlines(self, inline: Token, block_tok: Token) -> tuple[Inline, ...]:
        children = inline.children or []
        nodes, _ = self._inline_seq(children, 0, None, block_tok)
        self._check_text(nodes, block_tok)
        return _merge_text(nodes)

    def _inline_seq(
        self, toks: list[Token], i: int, closing: str | None, block_tok: Token
    ) -> tuple[list[Inline], int]:
        out: list[Inline] = []
        while i < len(toks):
            tok = toks[i]
            t = tok.type
            if closing is not None and t == closing:
                return out, i + 1
            if t == "text":
                out.append(Text(tok.content))
                i += 1
            elif t == "softbreak":
                out.append(SoftBreak())
                i += 1
            elif t == "hardbreak":
                out.append(LineBreak())
                i += 1
            elif t == "code_inline":
                out.append(InlineCode(tok.content))
                i += 1
            elif t in ("em_open", "strong_open", "s_open"):
                inner, i = self._inline_seq(toks, i + 1, t.replace("_open", "_close"), block_tok)
                cls = {"em_open": Emphasis, "strong_open": Strong, "s_open": Strikethrough}[t]
                out.append(cls(_merge_text(inner)))
            elif t == "link_open":
                inner, i = self._inline_seq(toks, i + 1, "link_close", block_tok)
                out.append(
                    Link(
                        self._safe_href(str(tok.attrGet("href") or ""), block_tok),
                        _merge_text(inner),
                    )
                )
            elif t == "image":
                out.append(self._image(tok, block_tok))
                i += 1
            elif t == "html_inline":
                out.extend(self._html_inline(tok, block_tok))
                i += 1
            else:  # pragma: no cover - defensive
                out.append(Text(tok.content))
                i += 1
        return out, i

    def _html_inline(self, tok: Token, block_tok: Token) -> list[Inline]:
        content = tok.content
        if _BR.match(content):
            return [LineBreak()]
        if _COMMENT.match(content):
            self.diags.add(
                Severity.INFO,
                "DOC-HTML-COMMENT",
                "HTML comment omitted from print",
                context=self.where(block_tok),
            )
            return []
        self.diags.add(
            Severity.WARNING,
            "DOC-RAW-HTML",
            f"inline HTML {content!r} is printed literally, not interpreted",
            context=self.where(block_tok),
            suggestion="replace the HTML with Markdown",
        )
        return [Text(content)]

    def _safe_href(self, href: str, block_tok: Token) -> str | None:
        if href.startswith("#") or href.lower().startswith(SAFE_LINK_SCHEMES):
            return href
        if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", href):
            return href  # relative link: kept as text target, never fetched
        self.diags.add(
            Severity.WARNING,
            "DOC-UNSAFE-LINK",
            f"link target {href!r} removed (only http, https, mailto and # are kept)",
            context=self.where(block_tok),
        )
        return None

    def _image(self, tok: Token, block_tok: Token) -> Image:
        source = str(tok.attrGet("src") or "")
        alt = plain_text(_merge_text(self._inline_seq(tok.children or [], 0, None, block_tok)[0]))
        title = tok.attrGet("title")
        title = str(title) if title else None
        where = self.where(block_tok)
        ref = unquote(source)
        try:
            path = resolve_local_asset(
                ref, root=self.book.root, bases=(self.chapter.directory, self.book.root)
            )
        except UnsafePathError as exc:
            self.diags.add(
                Severity.ERROR,
                "DOC-IMAGE-UNSAFE",
                f"image {source!r} not loaded: {exc.message}",
                context=where,
                suggestion=exc.hint,
            )
            return Image(source, None, alt, None, title)
        except InputError as exc:
            self.diags.add(
                Severity.ERROR,
                "DOC-IMAGE-MISSING",
                exc.message,
                context=where,
                suggestion=exc.hint,
            )
            return Image(source, None, alt, None, title)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            self.diags.add(
                Severity.ERROR,
                "DOC-IMAGE-FORMAT",
                f"unsupported image format {path.suffix!r} for {source!r}",
                context=where,
                suggestion="convert to PNG or JPEG",
            )
            return Image(source, None, alt, None, title)
        relative = path.relative_to(self.book.root.resolve()).as_posix()
        return Image(source, path, alt, relative, title)

    def _check_text(self, nodes: list[Inline], block_tok: Token) -> None:
        text = plain_text(tuple(nodes))
        if _UNDEFINED_REF_IMAGE.search(text):
            self.diags.add(
                Severity.WARNING,
                "DOC-UNDEFINED-REF",
                "reference-style image with no matching definition is printed as text",
                context=self.where(block_tok),
                suggestion="add the [label]: path definition or use ![alt](path)",
            )


def _merge_text(nodes: list[Inline]) -> tuple[Inline, ...]:
    merged: list[Inline] = []
    for node in nodes:
        if isinstance(node, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].text + node.text)
        else:
            merged.append(node)
    return tuple(merged)


def _normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_chapter(
    book: Book, chapter: Chapter, kind: ChapterKind, ids: set[str], diags: Diagnostics
) -> DocChapter:
    tokens = _markdown().parse(chapter.body)
    parser = _ChapterParser(book, chapter, ids, diags)
    chapter_id = parser.unique_id(slugify(chapter.slug) if chapter.slug else "chapter")
    blocks = parser.blocks(tokens, 0, len(tokens))
    # The chapter title is typeset by the chapter opener; drop an identical leading heading.
    if (
        blocks
        and isinstance(blocks[0], Heading)
        and _normalize_title(blocks[0].text) == _normalize_title(chapter.title)
    ):
        diags.add(
            Severity.INFO,
            "DOC-DUP-TITLE",
            "leading heading repeats the chapter title; typeset once by the chapter opener",
            context=chapter.relative_path,
        )
        blocks = blocks[1:]
    if not blocks and not chapter.is_front_matter:
        diags.add(
            Severity.WARNING,
            "DOC-EMPTY-CHAPTER",
            "chapter has no printable content",
            context=chapter.relative_path,
        )
    return DocChapter(
        id=chapter_id,
        slug=chapter.slug,
        title=chapter.title,
        kind=kind,
        source=chapter.relative_path,
        blocks=blocks,
        number=chapter.chapter_number,
        part_number=chapter.part_number,
        part_title=chapter.part_title,
    )


def parse_book(book: Book) -> Document:
    """Parse every chapter of ``book`` into one :class:`Document` (deterministic)."""
    diags = Diagnostics()
    ids: set[str] = set()
    chapters: list[DocChapter] = []
    after_appendix = False
    for chapter in book.chapters:
        kind = chapter_kind(chapter, after_appendix)
        after_appendix = after_appendix or kind is ChapterKind.APPENDIX
        chapters.append(parse_chapter(book, chapter, kind, ids, diags))
    return Document(title=book.title, chapters=tuple(chapters), diagnostics=tuple(diags))


__all__ = ["IMAGE_EXTENSIONS", "chapter_kind", "parse_book", "parse_chapter", "slugify"]
