import json
from pathlib import Path

import pytest

from printforge.document import ChapterKind, parse_book, to_data
from printforge.document.model import (
    BlockQuote,
    CodeBlock,
    Emphasis,
    Figure,
    Heading,
    Image,
    InlineCode,
    LineBreak,
    Link,
    ListBlock,
    Paragraph,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    Text,
    ThematicBreak,
    plain_text,
)
from printforge.document.parse import slugify
from printforge.importer import load_book

FIXTURE = Path(__file__).parent / "fixtures" / "markdown-book"
GOLDEN = Path(__file__).parent / "fixtures" / "markdown-book.document.json"


@pytest.fixture(scope="module")
def doc():
    return parse_book(load_book(FIXTURE))


def chapter(doc, slug):
    return next(c for c in doc.chapters if c.slug == slug)


def rules(doc):
    return [d.rule_id for d in doc.diagnostics]


def make_book(tmp_path, body: str, files: dict[str, bytes] | None = None) -> Path:
    root = tmp_path / "b"
    (root / "chapters").mkdir(parents=True)
    (root / "book.json").write_text('{"slug":"b","title":"B","author":"A"}')
    (root / "chapters" / "c.md").write_text(f"---\ntitle: C\norder: 1\n---\n{body}")
    for name, data in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root


# ------------------------------------------------------------------ structure


def test_chapter_boundaries_kinds_and_parts(doc):
    assert [(c.slug, c.kind) for c in doc.chapters] == [
        ("01-preface", ChapterKind.FRONT_MATTER),
        ("02-blocks", ChapterKind.CHAPTER),
        ("03-media", ChapterKind.CHAPTER),
        ("04-appendix-a", ChapterKind.APPENDIX),
        ("05-afterword", ChapterKind.BACK_MATTER),
    ]
    blocks = chapter(doc, "02-blocks")
    assert (blocks.part_number, blocks.part_title, blocks.number) == (1, "PART I: STRUCTURE", 1)
    assert blocks.source == "chapters/02-blocks.md"
    assert doc.title == "Markdown Coverage"


def test_leading_duplicate_title_dropped(doc):
    first = chapter(doc, "02-blocks").blocks[0]
    assert isinstance(first, Paragraph)
    assert "DOC-DUP-TITLE" in rules(doc)


def test_no_front_matter_leaks(doc):
    for c in doc.chapters:
        text = json.dumps(to_data(c.blocks))
        assert "order:" not in text and "isFrontMatter" not in text
    media = chapter(doc, "03-media")
    assert plain_text(media.blocks[-1].children) == "title: not metadata"


def test_inlines(doc):
    para = chapter(doc, "02-blocks").blocks[0]
    kinds = {type(n) for n in para.children}
    assert {Text, Emphasis, Strong, Strikethrough, InlineCode, Link, LineBreak, SoftBreak} <= kinds
    links = [n for n in para.children if isinstance(n, Link)]
    assert [link.href for link in links] == [
        "https://example.com/path?q=1",
        "mailto:author@example.com",
        "#blocks-inlines",
    ]
    nested = next(n for n in para.children if isinstance(n, Emphasis) and n.children)
    assert nested is not None


def test_headings_have_stable_unique_ids(doc):
    ids = [h.id for c in doc.chapters for h in c.headings]
    assert len(ids) == len(set(ids))
    blocks = chapter(doc, "02-blocks")
    assert [(h.level, h.id) for h in blocks.headings] == [
        (2, "02-blocks--lists"),
        (2, "02-blocks--quotes-and-code"),
        (2, "02-blocks--table"),
        (2, "02-blocks--lists-2"),
    ]
    assert blocks.headings[0].line == 15  # source line in the chapter file


def test_lists_nested_and_ordered(doc):
    lists = [b for b in chapter(doc, "02-blocks").blocks if isinstance(b, ListBlock)]
    bullets, ordered = lists
    assert not bullets.ordered and len(bullets.items) == 3 and bullets.tight
    nested = bullets.items[1].blocks[1]
    assert isinstance(nested, ListBlock) and not nested.ordered
    deep = nested.items[0].blocks[1]
    assert isinstance(deep, ListBlock) and deep.ordered and len(deep.items) == 2
    assert ordered.ordered and ordered.start == 3


def test_quotes_code_rules_tables(doc):
    blocks = chapter(doc, "02-blocks").blocks
    quote = next(b for b in blocks if isinstance(b, BlockQuote))
    assert isinstance(quote.blocks[1], BlockQuote)
    codes = [b for b in blocks if isinstance(b, CodeBlock)]
    assert codes[0].language == "python" and '"<not html>"' in codes[0].text
    assert codes[1].language is None and codes[1].text == "indented code block\n"
    assert any(isinstance(b, ThematicBreak) for b in blocks)
    table = next(b for b in blocks if isinstance(b, Table))
    assert [c.align for c in table.header[0]] == ["left", "center", "right"]
    assert len(table.body) == 2
    assert isinstance(table.body[1][2].children[0], Link)


def test_images_resolved_locally(doc):
    media = chapter(doc, "03-media")
    figure = media.blocks[0]
    assert isinstance(figure, Figure)
    assert figure.image.alt == "A local diagram" and figure.image.title == "Diagram title"
    assert figure.image.relative_path == "images/diagram.png"
    assert figure.image.path == (FIXTURE / "images/diagram.png").resolve()
    inline = [n for n in media.blocks[1].children if isinstance(n, Image)]
    assert len(inline) == 1
    assert len(doc.images) == 2


def test_unicode_and_punctuation_preserved(doc):
    text = plain_text(chapter(doc, "03-media").blocks[2].children)
    for fragment in [
        'Straight "quotes"',
        "'apostrophes'",
        "“quotes”",
        "‘apostrophes’",
        "— em dash",
        "– en dash",
        "ellipsis…",
        "non-breaking space",
        "café, naïve, Ελληνικά, 日本語, emoji 📖, math ≤ ≥ ×",
    ]:
        assert fragment in text


# ------------------------------------------------------------------ safety


def test_raw_html_is_text_not_markup(doc):
    appendix = chapter(doc, "04-appendix-a")
    dumped = json.dumps(to_data(appendix.blocks))
    assert '<script>alert(\\"x\\")</script>' in dumped  # literal text
    para = appendix.blocks[1]
    assert any(isinstance(n, Text) and "<span" in n.text for n in para.children)
    assert any(isinstance(n, LineBreak) for n in para.children)  # <br> subset
    assert "an author note" not in dumped
    assert rules(doc).count("DOC-RAW-HTML") >= 2
    assert "DOC-HTML-COMMENT" in rules(doc)


def test_unsafe_link_schemes_removed(doc):
    para = chapter(doc, "04-appendix-a").blocks[-1]
    text = plain_text(para.children)
    # markdown-it refuses javascript:/file: links outright: they stay literal text.
    assert "[js link](javascript:alert(1))" in text and "[file link](file:///etc/passwd)" in text
    # Other non-allow-listed schemes become links without a target.
    links = [n for n in para.children if isinstance(n, Link)]
    assert [(plain_text(link.children), link.href) for link in links] == [
        ("ftp link", None),
        ("phone", None),
    ]
    assert rules(doc).count("DOC-UNSAFE-LINK") == 2


@pytest.mark.parametrize(
    ("ref", "rule"),
    [
        ("https://example.com/a.png", "DOC-IMAGE-UNSAFE"),
        ("//cdn.example.com/a.png", "DOC-IMAGE-UNSAFE"),
        ("data:image/png;base64,AAAA", "DOC-IMAGE-UNSAFE"),
        ("/etc/hosts", "DOC-IMAGE-UNSAFE"),
        ("../../../../etc/hosts", "DOC-IMAGE-UNSAFE"),
        ("missing.png", "DOC-IMAGE-MISSING"),
        ("notes.txt", "DOC-IMAGE-FORMAT"),
    ],
)
def test_bad_images_are_errors_and_never_loaded(tmp_path, ref, rule):
    root = make_book(tmp_path, f"\n![x]({ref})\n", {"notes.txt": b"hi"})
    doc = parse_book(load_book(root))
    errors = [d for d in doc.diagnostics if d.severity == "ERROR"]
    assert [d.rule_id for d in errors] == [rule]
    assert errors[0].context == "chapters/c.md:6"
    image = doc.chapters[0].blocks[0].image
    assert image.path is None and image.source == ref


def test_percent_encoded_image_path(tmp_path):
    root = make_book(tmp_path, "\n![x](my%20image.png)\n", {"my image.png": b"\x89PNG"})
    image = parse_book(load_book(root)).chapters[0].blocks[0].image
    assert image.relative_path == "my image.png"


def test_undefined_reference_image_and_empty_heading(tmp_path):
    root = make_book(tmp_path, "\n# ![][image1]\n\n#\n\nText ![][missing] here.\n")
    found = rules(parse_book(load_book(root)))
    assert "DOC-UNDEFINED-REF" in found and "DOC-EMPTY-HEADING" in found


def test_empty_chapter_warning(tmp_path):
    root = make_book(tmp_path, "\n<!-- only a comment -->\n")
    assert "DOC-EMPTY-CHAPTER" in rules(parse_book(load_book(root)))


# ------------------------------------------------------------------ determinism


def test_repeat_parses_identical(doc):
    again = parse_book(load_book(FIXTURE))
    assert again == doc
    assert json.dumps(to_data(again)) == json.dumps(to_data(doc))


def test_matches_golden_snapshot(doc):
    """Structural snapshot; regenerate with PRINTFORGE_UPDATE_GOLDEN=1 after intended changes."""
    import os

    data = to_data(doc)
    text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("PRINTFORGE_UPDATE_GOLDEN"):
        GOLDEN.write_text(text, encoding="utf-8")
    assert "/home/" not in text and str(FIXTURE.resolve()) not in text
    assert GOLDEN.read_text(encoding="utf-8") == text


def test_slugify():
    assert slugify("Blocks & Inlines") == "blocks-inlines"
    assert slugify("Café — Naïve") == "cafe-naive"
    assert slugify("日本語") == "section"


def test_document_has_no_layout_or_provider_fields(doc):
    dumped = json.dumps(to_data(doc)).lower()
    for word in ("margin", "trim", "kdp", "font", "page"):
        assert f'"{word}' not in dumped


def test_heading_text_property():
    h = Heading(2, (Text("A "), Strong((Text("B"),))), "x")
    assert h.text == "A B"
