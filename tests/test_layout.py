import io
import logging
import re
import shutil

import pytest

from printforge.config import resolve_print_job
from printforge.importer import load_book
from printforge.layout import (
    LayoutConvergenceError,
    PageSide,
    describe,
    inside_margin,
    paginate_until_stable,
    plan_layout,
    stylesheet,
)
from printforge.layout.plan import CHAPTER, DISPLAY, FRONT, PART, FolioStyle
from printforge.layout.styles import css_string
from printforge.providers import get_provider
from printforge.units import Length

KDP = get_provider("kdp")
IN = Length.inches


@pytest.fixture
def book(tmp_path, minimal_book):
    shutil.copytree(minimal_book, tmp_path / "b")
    return tmp_path / "b"


def settings(book, **cli):
    return resolve_print_job(load_book(book), cli_overrides=cli).settings


def page_rule(css: str, selector: str) -> str:
    match = re.search(r"^@page " + re.escape(selector) + r" \{.*$", css, re.MULTILINE)
    assert match, selector
    return match.group(0)


# ------------------------------------------------------------------ geometry


def test_mirrored_margins_swap_gutter(book):
    plan = plan_layout(settings(book), KDP, 100, book_title="T")
    g = plan.geometry
    recto, verso = g.margins(PageSide.RECTO), g.margins(PageSide.VERSO)
    assert (recto.left, recto.right) == (g.inside, g.outside)  # binding on the left of rectos
    assert (verso.left, verso.right) == (g.outside, g.inside)  # binding on the right of versos
    assert g.inside == IN("0.5") and g.outside == IN("0.625")
    assert g.text_width == IN("4.875") and g.text_height == IN("7.5")
    assert g.page.width == IN("6") and g.page.height == IN("9")


@pytest.mark.parametrize(
    ("pages", "inside"),
    [
        (24, "0.5"),
        (150, "0.5"),
        (151, "0.625"),
        (300, "0.625"),
        (301, "0.75"),
        (500, "0.75"),
        (501, "0.875"),
        (700, "0.875"),
        (701, "1"),
        (828, "1"),
    ],
)
def test_auto_gutter_follows_provider_tiers_plus_extra(book, pages, inside):
    value, rule = inside_margin(settings(book), KDP, pages)
    assert value == IN(inside)
    assert f"for {pages} pages" in rule


@pytest.mark.parametrize(("pages", "clamped"), [(5, 24), (900, 828)])
def test_out_of_range_page_counts_use_nearest_tier(book, pages, clamped):
    value, rule = inside_margin(settings(book), KDP, pages)
    assert f"tier for {clamped} used" in rule
    assert value == KDP.min_inside_margin(clamped) + IN("0.125")


def test_explicit_inside_margin_is_used_verbatim(book):
    s = settings(book, margins={"inside": "0.8in"})
    for pages in (24, 400, 800):
        assert inside_margin(s, KDP, pages)[0] == IN("0.8")


def test_gutter_extra_zero_hits_provider_minimum_exactly(book):
    s = settings(book, margins={"gutter_extra": "0in"})
    assert inside_margin(s, KDP, 151)[0] == KDP.min_inside_margin(151)


# ------------------------------------------------------------------ sections


def test_section_policies(book):
    plan = plan_layout(settings(book), KDP, 100, book_title="T")
    s = plan.sections
    assert s[DISPLAY].folio is FolioStyle.NONE and not s[DISPLAY].running_heads
    assert s[FRONT].folio is FolioStyle.LOWER_ROMAN and not s[FRONT].running_heads
    assert s[PART].folio is FolioStyle.NONE
    assert s[CHAPTER].folio is FolioStyle.DECIMAL and s[CHAPTER].running_heads
    assert s["chapter-start"].restart_numbering and s["part-start"].restart_numbering
    assert not s[CHAPTER].restart_numbering
    assert all(p.start == "recto" for p in s.values())


def test_chapter_start_any_and_options(book):
    s = settings(
        book,
        layout={"chapter_start": "any", "front_matter_folios": "none", "running_heads": False},
    )
    plan = plan_layout(s, KDP, 100, book_title="T")
    assert plan.sections[CHAPTER].start == "any"
    assert plan.sections["chapter-start"].start == "recto"  # main matter still opens recto
    assert plan.sections[FRONT].folio is FolioStyle.NONE
    css = stylesheet(plan)
    assert "section.pf-chapter { page: chapter; break-before: page; }" in css
    assert "string(pf-chapter)" not in css
    assert "lower-roman" not in css


# ------------------------------------------------------------------ stylesheet


def test_css_page_rules_mirror_margins(book):
    css = stylesheet(plan_layout(settings(book), KDP, 100, book_title="T"))
    assert "@page { size: 6in 9in;" in css
    # CSS margin order: top right bottom left
    assert "margin: 0.75in 0.625in 0.75in 0.5in;" in page_rule(css, ":right")
    assert "margin: 0.75in 0.5in 0.75in 0.625in;" in page_rule(css, ":left")


def test_css_gutter_changes_with_tier(book):
    small = stylesheet(plan_layout(settings(book), KDP, 150, book_title="T"))
    large = stylesheet(plan_layout(settings(book), KDP, 151, book_title="T"))
    assert "0.75in 0.625in 0.75in 0.5in" in small
    assert "0.75in 0.625in 0.75in 0.625in" in large


def test_css_sections_folios_and_heads(book):
    css = stylesheet(plan_layout(settings(book), KDP, 100, book_title="My Book"))
    assert "section.pf-chapter { page: chapter; break-before: recto; }" in css
    assert "section.pf-chapter.pf-start { page: chapter-start; break-before: recto; }" in css
    assert "counter-reset: page 1" in page_rule(css, "chapter-start:nth(1 of chapter-start)")
    assert "counter-reset" not in page_rule(css, "chapter:nth(1 of chapter)")
    assert "@top-center { content: none; }" in page_rule(css, "chapter:nth(1 of chapter)")
    assert "counter(page, lower-roman)" in page_rule(css, "front:right")
    assert "counter(page" not in page_rule(css, "front-display:right")
    assert "counter(page" not in page_rule(css, "part:right")
    assert 'content: "My Book"' in page_rule(css, "chapter:left")  # verso: book title
    assert "string(pf-chapter)" in page_rule(css, "chapter:right")  # recto: chapter
    blank = page_rule(css, ":blank")
    assert "counter" not in blank and "string(" not in blank
    assert "widows: 2; orphans: 2;" in css
    assert "break-after: avoid" in css


def test_folio_outside_edge(book):
    css = stylesheet(
        plan_layout(
            settings(book, layout={"folio_position": "bottom-outside"}), KDP, 100, book_title="T"
        )
    )
    assert "@bottom-right { content: counter(page, decimal)" in page_rule(css, "chapter:right")
    assert "@bottom-left { content: counter(page, decimal)" in page_rule(css, "chapter:left")


def test_deterministic_fonts_and_no_silent_fallback(book):
    s = settings(book, typography={"body_font": "Liberation Serif", "font_size": "11pt"})
    css = stylesheet(plan_layout(s, KDP, 100, book_title="T"))
    assert 'html { font-family: "Liberation Serif"; font-size: 11pt; }' in css
    assert not re.search(r"font-family:[^;]*,", css)  # exactly one family, no fallback list
    assert stylesheet(plan_layout(s, KDP, 100, book_title="T")) == css


def test_styles_reusable_across_books(book):
    s = settings(book)
    a = stylesheet(plan_layout(s, KDP, 100, book_title="Book A"))
    b = stylesheet(plan_layout(s, KDP, 100, book_title="Book B"))
    diff = [(x, y) for x, y in zip(a.splitlines(), b.splitlines(), strict=True) if x != y]
    assert diff and all('"Book A"' in x and '"Book B"' in y for x, y in diff)
    assert "Meistro" not in a


def test_css_string_escaping():
    assert css_string('He said "hi" \\o/\nbye') == '"He said \\"hi\\" \\\\o/\\A bye"'


def test_describe_plan(book):
    data = describe(plan_layout(settings(book), KDP, 200, book_title="T"))
    assert (
        data["recto_margins"]["left"] == "0.625in" and data["verso_margins"]["right"] == "0.625in"
    )
    assert data["page_count_basis"] == 200
    assert data["sections"]["chapter"]["folio"] == "decimal"


# ------------------------------------------------------------------ convergence


def fake_renderer(pages_for_gutter: dict[str, int]):
    calls = []

    def render(plan):
        key = plan.geometry.inside.to_str("in")
        calls.append(key)
        return pages_for_gutter[key], f"pdf@{key}"

    return render, calls


def test_converges_first_pass_for_short_book(book):
    render, calls = fake_renderer({"0.5in": 120})
    out = paginate_until_stable(settings(book), KDP, render, book_title="T")
    assert out.page_count == 120 and out.result == "pdf@0.5in" and calls == ["0.5in"]
    assert out.plan.page_count_basis == 120 and len(out.passes) == 1


def test_recomputes_when_crossing_gutter_tier(book):
    render, calls = fake_renderer({"0.5in": 155, "0.625in": 158})
    out = paginate_until_stable(settings(book), KDP, render, book_title="T")
    assert calls == ["0.5in", "0.625in"]
    assert out.page_count == 158 and out.plan.geometry.inside == IN("0.625")
    assert [p.page_count for p in out.passes] == [155, 158]


def test_oscillation_is_reported(book):
    render, _ = fake_renderer({"0.5in": 151, "0.625in": 149})
    with pytest.raises(LayoutConvergenceError, match="oscillates.*gutter 0.5in -> 151 pages"):
        paginate_until_stable(settings(book), KDP, render, book_title="T")


def test_bounded_passes(book):
    render, calls = fake_renderer({"0.5in": 200, "0.625in": 400, "0.75in": 600, "0.875in": 800})
    with pytest.raises(LayoutConvergenceError, match="no stable gutter after 3 passes"):
        paginate_until_stable(settings(book), KDP, render, book_title="T", max_passes=3)
    assert len(calls) == 3


def test_explicit_gutter_needs_one_pass(book):
    render, calls = fake_renderer({"0.9in": 400})
    out = paginate_until_stable(
        settings(book, margins={"inside": "0.9in"}), KDP, render, book_title="T"
    )
    assert calls == ["0.9in"] and out.page_count == 400


# ------------------------------------------------------------------ real renderer check


@pytest.mark.pdf
def test_stylesheet_renders_page_model_with_weasyprint(book):
    import pypdf
    import weasyprint

    warnings: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())

    handler = Capture(level=logging.WARNING)
    logging.getLogger("weasyprint").addHandler(handler)
    try:
        plan = plan_layout(settings(book), KDP, 24, book_title="Book Title")
        para = "<p>" + "word " * 120 + "</p>"
        html = f"""<html lang="en"><body>
        <section class="pf-display"><div class="pf-page pf-recto"><p>Title</p></div>
          <div class="pf-page pf-verso"><p>Copyright</p></div></section>
        <section class="pf-front"><header class="pf-opener">
          <h1 class="pf-chapter-title">Contents</h1></header><p>toc</p></section>
        <section class="pf-chapter pf-start"><header class="pf-opener">
          <h1 class="pf-chapter-title">First</h1></header>{para * 12}</section>
        <section class="pf-chapter"><header class="pf-opener">
          <h1 class="pf-chapter-title">Second</h1></header>{para}</section>
        </body></html>"""
        doc = weasyprint.HTML(string=html).render(
            stylesheets=[weasyprint.CSS(string=stylesheet(plan))]
        )
    finally:
        logging.getLogger("weasyprint").removeHandler(handler)
    assert warnings == []  # every generated CSS rule was understood
    reader = pypdf.PdfReader(io.BytesIO(doc.write_pdf()))
    texts = [p.extract_text().split("\n") for p in reader.pages]
    for page in reader.pages:
        assert (float(page.mediabox.width), float(page.mediabox.height)) == (432, 648)
    boxes = [p._page_box for p in doc.pages]
    sides = [b.page_type.side for b in boxes]
    assert sides[:2] == ["right", "left"]
    for box in boxes:  # gutter always on the binding edge
        left, right = round(box.margin_left / 96, 4), round(box.margin_right / 96, 4)
        assert (left, right) == ((0.5, 0.625) if box.page_type.side == "right" else (0.625, 0.5))
    assert boxes[3].page_type.blank  # blank verso before the recto main-matter start
    first = 4  # main matter starts on physical page 5 (recto) with folio 1
    assert texts[first][-1] == "1" and "First" in texts[first][0]
    assert texts[first + 1][-2:] == ["BOOK TITLE", "2"]  # verso running head
    assert texts[first + 2][-2:] == ["FIRST", "3"]  # recto running head
    assert texts[2][-1] == "iii"  # front matter roman folio
    assert texts[0] == ["Title"]  # display page: no folio
    assert all(t == [""] for t, b in zip(texts, boxes, strict=True) if b.page_type.blank)
