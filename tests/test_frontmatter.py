"""Front matter and table-of-contents generation (no PDF stack needed)."""

from dataclasses import replace
from pathlib import Path

import pytest

from printforge.config import resolve_print_job
from printforge.config.settings import TocSettings
from printforge.importer import load_book
from printforge.render import HeadingLocation, build_front_units, toc_entries
from printforge.render.frontmatter import display_pages, toc_unit

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "print-book"


@pytest.fixture(scope="module")
def job():
    return resolve_print_job(load_book(FIXTURE))


def toc(**overrides) -> TocSettings:
    base = TocSettings(
        enabled=True,
        depth=1,
        title="Contents",
        include_front_matter=False,
        include_parts=True,
    )
    return replace(base, **overrides)


def heading(
    anchor_id: str,
    text: str,
    *,
    level: int = 1,
    kind: str = "chapter",
    unit: bool = True,
    page: int = 1,
    folio: str = "1",
) -> HeadingLocation:
    return HeadingLocation(anchor_id, text, level, kind, unit, page, folio)


# ---------------------------------------------------------------- display pages


def test_default_display_pages_are_title_then_copyright(job):
    pages = display_pages(job.settings, job.metadata)
    assert len(pages) == 2
    assert pages[0].startswith('<div class="pf-page pf-recto">')
    assert pages[1].startswith('<div class="pf-page pf-verso">')
    assert 'class="pf-book-title"' in pages[0]
    assert 'class="pf-copyright"' in pages[1]


def test_half_title_is_optional(job):
    front = replace(job.settings.front_matter, half_title=True)
    settings = replace(job.settings, front_matter=front)
    pages = display_pages(settings, job.metadata)
    assert len(pages) == 3
    assert 'class="pf-half-title"' in pages[0]


def test_display_pages_can_all_be_disabled(job):
    settings = replace(
        job.settings,
        front_matter=replace(
            job.settings.front_matter,
            half_title=False,
            title_page=False,
            copyright_page=False,
        ),
    )
    assert display_pages(settings, job.metadata) == []


def test_title_page_uses_only_supplied_metadata(job):
    page = display_pages(job.settings, job.metadata)[0]
    assert "The Printer&#x27;s Field Guide" in page
    assert "A Synthetic Manuscript for Print Testing" in page
    assert "PrintForge Fixtures" in page
    assert 'class="pf-subtitle"' in page
    assert 'class="pf-author"' in page
    assert 'class="pf-imprint"' in page


def test_title_page_omits_missing_subtitle_and_publisher(job):
    metadata = {"title": "A Book", "author": "An Author", "subtitle": None, "publisher": None}
    page = display_pages(job.settings, metadata)[0]
    assert "A Book" in page
    assert "An Author" in page
    assert "pf-subtitle" not in page
    assert "pf-imprint" not in page


def test_copyright_page_prints_supplied_fields(job):
    page = display_pages(job.settings, job.metadata)[1]
    assert "© 2026 PrintForge Fixtures" in page
    assert "<p>First edition</p>" in page
    assert "<p>ISBN 9781234567897</p>" in page
    assert "<p>PrintForge Fixtures</p>" in page


def test_copyright_page_never_invents_legal_text(job):
    metadata = {"title": "A Book", "author": "An Author"}
    page = display_pages(job.settings, metadata)[1]
    for invented in ("©", "ISBN", "All rights reserved", "Printed in", "Publisher"):
        assert invented not in page


def test_copyright_notice_survives_a_missing_holder(job):
    metadata = {"title": "A Book", "copyright_year": 2020}
    page = display_pages(job.settings, metadata)[1]
    assert "© 2020" in page
    assert "None" not in page


def test_front_units_are_display_then_contents(job):
    units, ids = build_front_units(job.settings, job.metadata, ())
    assert ids == ("sec-front-display", "sec-toc")
    assert units[0].startswith('<section class="pf-display"')
    assert units[1].startswith('<section class="pf-front" id="sec-toc">')
    assert "Contents" in units[1]


def test_contents_unit_can_be_disabled(job):
    settings = replace(job.settings, toc=toc(enabled=False))
    units, ids = build_front_units(settings, job.metadata, ())
    assert ids == ("sec-front-display",)
    assert all("sec-toc" not in unit for unit in units)


def test_titles_and_entries_are_escaped(job):
    metadata = {"title": "<Title & Co>", "author": "A <b>Author</b>"}
    pages = display_pages(job.settings, metadata)
    assert "&lt;Title &amp; Co&gt;" in pages[0]
    entry = toc_entries((heading("ch-1", "<Danger> & Co"),), job.settings.toc)[0]
    assert "&lt;Danger&gt; &amp; Co" in toc_unit(job.settings.toc, (entry,))


# ---------------------------------------------------------------- contents rows


def test_contents_rows_use_dot_leaders_and_folios(job):
    html = toc_unit(job.settings.toc, (heading("ch-1", "Chapter One", folio="7"),))
    assert '<a href="#ch-1">Chapter One</a>' in html
    assert '<span class="pf-toc-dots"></span>' in html
    assert '<span class="pf-toc-folio">7</span>' in html


def test_contents_rows_carry_level_and_part_classes(job):
    headings = (
        heading("part-1-x", "PART I", kind="part"),
        heading("ch-1", "Chapter One"),
        heading("ch-1--sec", "A Section", level=3, kind="chapter", unit=False),
        heading("ch-1--sub", "A Subsection", level=4, kind="chapter", unit=False),
    )
    html = toc_unit(toc(depth=3), toc_entries(headings, toc(depth=3)))
    assert 'class="pf-toc-entry pf-toc-level-1 pf-toc-part"' in html
    assert 'class="pf-toc-entry pf-toc-level-2"' in html
    assert 'class="pf-toc-entry pf-toc-level-3"' in html


def test_depth_one_lists_parts_and_chapters_only(job):
    headings = (
        heading("part-1-x", "PART I", kind="part"),
        heading("ch-1", "Chapter One"),
        heading("ch-1--a", "Section A", level=3, unit=False),
        heading("ch-1--b", "Sub A", level=4, unit=False),
    )
    entries = toc_entries(headings, toc(depth=1))
    assert [entry.id for entry in entries] == ["part-1-x", "ch-1"]
    assert [entry.level for entry in entries] == [1, 1]


def test_depth_two_and_three_add_markdown_levels(job):
    headings = (
        heading("ch-1", "Chapter One"),
        heading("ch-1--a", "Section A", level=3, unit=False),
        heading("ch-1--b", "Sub A", level=4, unit=False),
    )
    assert [entry.id for entry in toc_entries(headings, toc(depth=2))] == ["ch-1", "ch-1--a"]
    assert [entry.id for entry in toc_entries(headings, toc(depth=3))] == [
        "ch-1",
        "ch-1--a",
        "ch-1--b",
    ]
    assert [entry.level for entry in toc_entries(headings, toc(depth=3))] == [1, 2, 3]


def test_front_matter_entries_are_opt_in(job):
    headings = (
        heading("foreword", "Foreword", kind="front-matter", folio="v"),
        heading("ch-1", "Chapter One"),
    )
    assert [entry.id for entry in toc_entries(headings, toc())] == ["ch-1"]
    assert [entry.id for entry in toc_entries(headings, toc(include_front_matter=True))] == [
        "foreword",
        "ch-1",
    ]


def test_front_matter_body_headings_follow_the_same_opt_in(job):
    headings = (
        heading("foreword", "Foreword", kind="front-matter", folio="v"),
        heading("foreword--note", "A Note", level=3, kind="front-matter", unit=False, folio="v"),
    )
    assert toc_entries(headings, toc(depth=2)) == ()
    assert toc_entries(headings, toc(depth=2, include_front_matter=False)) == ()
    assert len(toc_entries(headings, toc(depth=2, include_front_matter=True))) == 2


def test_parts_are_opt_out(job):
    headings = (heading("part-1-x", "PART I", kind="part"), heading("ch-1", "Chapter One"))
    assert [entry.id for entry in toc_entries(headings, toc(include_parts=False))] == ["ch-1"]


def test_empty_headings_are_skipped(job):
    headings = (
        heading("ch-1", "Chapter One"),
        heading("ch-1--empty", "   ", level=3, unit=False),
        heading("ch-2", ""),
    )
    assert [entry.id for entry in toc_entries(headings, toc(depth=3))] == ["ch-1"]
