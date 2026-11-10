"""HTML contract tests for the interior renderer (no PDF stack needed)."""

from dataclasses import replace
from pathlib import Path

import pytest

from printforge.config import resolve_print_job
from printforge.document import parse_book
from printforge.document.model import (
    ChapterKind,
    DocChapter,
    Document,
    Heading,
    Text,
)
from printforge.importer import load_book
from printforge.layout import plan_layout
from printforge.providers import get_provider
from printforge.render import build_html

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "bookforge-root/src/content/books/sample-book"


@pytest.fixture(scope="module")
def book():
    return load_book(FIXTURES / "markdown-book")


@pytest.fixture(scope="module")
def document(book):
    return parse_book(book)


@pytest.fixture(scope="module")
def job(book):
    return resolve_print_job(book)


@pytest.fixture(scope="module")
def settings(job):
    return job.settings


@pytest.fixture(scope="module")
def plan(settings):
    return plan_layout(settings, get_provider("kdp"), 100, book_title="Markdown Coverage")


def render_html(document, plan, *, title="Markdown Coverage", author="PrintForge Tests"):
    return build_html(
        document,
        plan.layout,
        language=plan.typography.language,
        title=title,
        author=author,
    )


@pytest.fixture(scope="module")
def html(document, plan):
    return render_html(document, plan)


@pytest.fixture(scope="module")
def body(html):
    return html.html.split("<body>", 1)[1]


def test_document_shell(html):
    assert html.html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html.html
    assert "<title>Markdown Coverage</title>" in html.html
    assert '<meta name="author" content="PrintForge Tests">' in html.html
    assert html.html.rstrip().endswith("</html>")


def test_every_chapter_is_one_section(document, body):
    assert body.count("<section ") == len(document.chapters) + 1  # + one part divider
    assert body.count('<section class="pf-front"') + body.count(
        '<section class="pf-chapter'
    ) == len(document.chapters)


def test_first_chapter_is_front_matter_and_main_matter_starts_a_part(body):
    assert body.lstrip().startswith('<section class="pf-front" id="sec-01-preface">')
    assert '<section class="pf-part pf-start" id="sec-part-1-part-i-structure">' in body
    assert body.count("pf-start") == 1


def test_part_divider_carries_label_title_and_anchor(body):
    assert '<p class="pf-part-label">Part 1</p>' in body
    assert '<h1 class="pf-part-title" id="part-1-part-i-structure">PART I: STRUCTURE</h1>' in body


def test_chapter_labels_are_printed_for_numbered_chapters(body):
    assert body.count('class="pf-chapter-label"') == 2
    assert '<p class="pf-chapter-label">Chapter 1</p>' in body
    assert '<p class="pf-chapter-label">Chapter 2</p>' in body


def test_chapter_label_can_be_disabled(document, settings):
    layout = replace(settings.layout, chapter_label=None)
    plan = plan_layout(
        replace(settings, layout=layout),
        get_provider("kdp"),
        100,
        book_title="Markdown Coverage",
    )
    html = render_html(document, plan)
    assert "pf-chapter-label" not in html.html.split("<body>", 1)[1]


def test_front_matter_never_gets_a_chapter_label():
    book = load_book(SAMPLE)
    document = parse_book(book)
    plan = plan_layout(
        resolve_print_job(book).settings, get_provider("kdp"), 100, book_title=book.title
    )
    html = render_html(document, plan, title=book.title, author=book.author)
    assert '<section class="pf-front" id="sec-foreword">' in html.html
    assert '<h1 class="pf-chapter-title" id="foreword">Foreword</h1>' in html.html


def test_markdown_headings_shift_down_one_level(document, body):
    assert '<h3 id="02-blocks--lists">Lists</h3>' in body
    assert '<h3 id="02-blocks--lists-2">Lists</h3>' in body
    assert body.count("<h1 ") == len(document.chapters) + 1


def test_heading_levels_clamp_at_six(plan):
    chapter = DocChapter(
        id="clamp",
        slug="clamp",
        title="Clamp",
        kind=ChapterKind.CHAPTER,
        source="chapters/clamp.md",
        blocks=(Heading(6, (Text("Deep heading"),), "clamp--deep"),),
    )
    html = render_html(Document(title="Clamp", chapters=(chapter,)), plan)
    assert '<h6 id="clamp--deep">Deep heading</h6>' in html.html


def test_inline_markup_maps_to_html(body):
    assert "<em>emphasis</em>" in body
    assert "<strong>strong text</strong>" in body
    assert "<del>struck text</del>" in body
    assert "<code>inline code</code>" in body
    assert '<a href="https://example.com/path?q=1">web link</a>' in body
    assert '<a href="mailto:author@example.com">mail link</a>' in body
    assert '<a href="#blocks-inlines">internal link</a>' in body
    assert "hard break<br>" in body


def test_nested_lists_and_ordered_start(body):
    assert "<ul>" in body
    assert '<ol start="3">' in body
    assert "nested bullet" in body


def test_tables_keep_header_scope_and_alignment(body):
    assert (
        '<th style="text-align: left">Left</th><th style="text-align: center">Center</th>'
        '<th style="text-align: right">Right</th>'
    ) in body
    assert '<td style="text-align: left"><code>x</code></td>' in body
    assert '<td style="text-align: right"><a href="https://example.org">z</a></td>' in body


def test_code_blocks_escape_markup_and_keep_language(body):
    assert 'class="language-python"' in body
    assert "&lt;not html&gt;" in body


def test_thematic_break_uses_the_stylesheet_hook(body):
    assert '<hr class="pf-break">' in body


def test_images_render_as_figures_and_are_the_only_allowed_assets(html, book):
    assert '<figure><img src="file://' in html.html
    assert 'alt="A local diagram"' in html.html
    assert 'alt="tiny"' in html.html
    assert {path.name for path in html.assets} == {"diagram.png"}
    for path in html.assets:
        assert path.is_absolute()
        assert path.is_relative_to(book.root)


def test_content_is_escaped(body):
    assert "Blocks &amp; Inlines" in body
    assert "Blocks & Inlines</h1>" not in body
    assert "<not html>" not in body


def test_anchors_follow_document_order_and_match_ids(html, body):
    ids = [anchor.id for anchor in html.anchors]
    assert ids[0] == "01-preface"
    assert ids[1] == "part-1-part-i-structure"
    assert ids[2] == "02-blocks"
    assert len(ids) == len(set(ids))
    for anchor in html.anchors:
        assert f'id="{anchor.id}"' in body


def test_unit_ids_and_first_main_unit(html):
    assert html.unit_ids[0] == "sec-01-preface"
    assert html.first_main_id == "part-1-part-i-structure"
    assert len(html.unit_ids) == html.html.count("<section ")


def test_part_pages_can_be_disabled(document, settings):
    layout = replace(settings.layout, part_pages=False)
    plan = plan_layout(
        replace(settings, layout=layout),
        get_provider("kdp"),
        100,
        book_title="Markdown Coverage",
    )
    html = render_html(document, plan)
    body = html.html.split("<body>", 1)[1]
    assert "pf-part" not in body
    assert body.count("pf-start") == 1
