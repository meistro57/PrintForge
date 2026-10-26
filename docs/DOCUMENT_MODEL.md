# Semantic document model

`printforge.document.parse_book(book) -> Document` turns imported chapters into a
provider-neutral tree of blocks and inlines (`printforge/document/model.py`). The
model holds **content only**: no page sizes, fonts, margins or provider rules.
Layout (#6) and rendering (#7) consume it.

Parser: markdown-it-py, CommonMark plus GFM tables and `~~strikethrough~~`. The
typographer is **off**, so straight and curly punctuation and all Unicode come
through exactly as written.

## Mapping

| Markdown | Node |
|---|---|
| `#`–`######` | `Heading(level, children, id, line)` |
| paragraph | `Paragraph`; a paragraph containing only one image becomes `Figure` |
| `-`, `*`, `1.` lists (nested) | `ListBlock(ordered, start, tight, items[ListItem(blocks)])` |
| `>` | `BlockQuote(blocks)` (nesting is preserved) |
| fenced / indented code | `CodeBlock(text, language)` |
| `---` | `ThematicBreak` |
| tables | `Table(header, body)` of `TableCell(children, align)` |
| `*em*`, `**strong**`, `~~s~~`, `` `code` `` | `Emphasis`, `Strong`, `Strikethrough`, `InlineCode` |
| `[text](url)` | `Link(href, children)` |
| `![alt](path "title")` | `Image(source, path, alt, relative_path, title)` |
| hard / soft line break | `LineBreak` / `SoftBreak` |

## Chapters and semantic flags

Each source chapter becomes one `DocChapter`. It keeps its `slug`, `title`, `source`
path, `number`, `part_number` and `part_title`, so pagination and the TOC can work
with chapter and part boundaries. `kind` is one of:

- `front-matter`: `isFrontMatter: true`
- `appendix`: the slug or title starts with "appendix"
- `back-matter`: any non-appendix chapter after the first appendix
- `chapter`: everything else

If a chapter body *starts* with a heading identical to the chapter title (ignoring case
and whitespace), that heading is dropped (`DOC-DUP-TITLE`), because the chapter opener
already typesets the title. No other content is removed. Web mastheads repeated inside
a chapter body (e.g. `# THE MEISTRO MANUAL` at the top of every chapter) are printed
as written.

Heading IDs are stable and unique across the document: `<chapter-slug>--<slugified
text>`, with `-2`, `-3`, ... suffixes for repeats. Chapter IDs are the slugified
chapter slug. `line` values are 1-based line numbers in the source chapter file.

## Safety policy

- **Raw HTML is never interpreted.** HTML blocks and inline tags are kept as literal
  text and reported as `DOC-RAW-HTML` warnings. Only two things are interpreted:
  `<br>`, which becomes a line break, and HTML comments, which are dropped
  (`DOC-HTML-COMMENT` info). No script or remote content can execute or load.
- **No remote assets.** Images must be local files inside the book root. They are
  resolved against the chapter's directory first, then the book root. URL
  percent-escapes are decoded. If an image is remote (`http:`, `//`, `data:`),
  absolute, escaping (`..`, symlinks), missing or of an unsupported format (allowed:
  png, jpg/jpeg, gif, webp, svg), it produces an **ERROR** diagnostic
  (`DOC-IMAGE-UNSAFE`, `DOC-IMAGE-MISSING`, `DOC-IMAGE-FORMAT`) with the file and line,
  and an `Image` with `path=None`. Nothing is ever fetched.
- **Links:** only `http`, `https`, `mailto`, in-document `#` and relative targets are
  kept. Other schemes lose their target (`DOC-UNSAFE-LINK`). markdown-it already refuses
  `javascript:`, `vbscript:`, `file:` and `data:` links, which stay as literal text.
- A reference-style image without a definition (`![][image1]`) is printed as text
  and flagged as `DOC-UNDEFINED-REF`.

## Determinism

All nodes are frozen dataclasses. Parsing the same manuscript twice gives equal
objects. `to_data(document)` yields JSON-compatible data without absolute paths, and
`tests/fixtures/markdown-book.document.json` is the golden snapshot (regenerate it with
`PRINTFORGE_UPDATE_GOLDEN=1 pytest tests/test_document.py`).
