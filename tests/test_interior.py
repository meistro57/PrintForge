"""End-to-end interior PDF tests.

Marked ``pdf``: these render real PDFs with WeasyPrint, so they need the native
Pango libraries (see docs/INSTALL.md). ``pytest -m "not pdf"`` skips them.

The manuscript is ``tests/fixtures/print-book``, a synthetic 45-page book
regenerated with ``python tools/generate_print_fixture.py``.
"""

from __future__ import annotations

import io
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

from printforge import __version__
from printforge.config import resolve_print_job
from printforge.document import parse_book
from printforge.errors import RenderError
from printforge.importer import load_book
from printforge.layout import inside_margin, paginate_until_stable, plan_layout
from printforge.providers import get_provider
from printforge.providers.base import PageSize
from printforge.render import InteriorPdfBuilder, read_pdf
from printforge.units import Length

pytestmark = pytest.mark.pdf

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "print-book"
KDP = get_provider("kdp")


@pytest.fixture(scope="module")
def book():
    return load_book(FIXTURE)


@pytest.fixture(scope="module")
def document(book):
    return parse_book(book)


@pytest.fixture(scope="module")
def job(book):
    return resolve_print_job(book)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory, document, job):
    """Render the fixture for real, converging the gutter like the build will."""
    out = tmp_path_factory.mktemp("interior") / "interior.pdf"
    builder = InteriorPdfBuilder(job.settings, metadata=job.metadata)

    def render(plan):
        result = builder.render(document, plan, out)
        return result.page_count, result

    converged = paginate_until_stable(job.settings, KDP, render, book_title=document.title)
    return converged, read_pdf(out.read_bytes())


# ------------------------------------------------------------------ geometry


def test_pages_are_trim_sized_single_pages(rendered):
    _converged, facts = rendered
    assert facts.size == PageSize(Length.inches(6), Length.inches(9))
    assert set(facts.page_sizes) == {facts.size}
    assert facts.page_count == len(facts.text_pages)


def test_page_boxes_match_the_trim_with_no_bleed_or_crop_marks(rendered):
    converged, facts = rendered
    assert facts.page_count > 0
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(converged.result.path.read_bytes()))
    for page in reader.pages:
        assert page.mediabox == page.cropbox
        assert page.mediabox == page.trimbox
        assert page.mediabox == page.bleedbox
        assert [float(value) for value in page.mediabox] == [0.0, 0.0, 432.0, 648.0]


def test_pdf_is_not_encrypted(rendered):
    _converged, facts = rendered
    assert facts.encrypted is False


# ------------------------------------------------------------------ content


def test_text_is_extractable(rendered):
    _converged, facts = rendered
    assert "Chapter Title 1" in facts.text
    assert "Appendix A: Reference Tables" in facts.text
    assert "page = trim + bleed" in facts.text
    assert "Folio" in facts.text


def test_part_pages_and_chapter_openers_are_printed(rendered):
    _converged, facts = rendered
    assert "PART I: THE PAGE" in facts.text
    assert "PART 1" in facts.text
    assert "CHAPTER 1" in facts.text


def test_page_count_meets_the_provider_minimum(rendered, job):
    converged, facts = rendered
    assert facts.page_count >= 24
    diagnostics = KDP.validate_finished_book(
        facts.page_count,
        facts.size,
        settings=job.settings,
        inside_margin=converged.plan.geometry.inside,
    )
    assert not diagnostics.has_errors, [item.format() for item in diagnostics]


def test_layout_converges_on_a_consistent_gutter(rendered, job):
    converged, _facts = rendered
    required, _rule = inside_margin(job.settings, KDP, converged.page_count)
    assert converged.plan.geometry.inside == required
    assert converged.page_count == converged.result.page_count
    assert len(converged.passes) >= 1


# ------------------------------------------------------------------ facts


def test_fonts_are_embedded_and_subset(rendered):
    converged, facts = rendered
    assert facts.fonts
    assert all(font.embedded for font in facts.fonts)
    assert all(font.subset for font in facts.fonts)
    assert all(font.base_name.startswith("DejaVu-") for font in facts.fonts)
    assert "DejaVu-Serif" in converged.result.fonts
    assert "DejaVu-Sans-Mono" in converged.result.fonts


def test_metadata_is_normalized(rendered, book):
    _converged, facts = rendered
    assert facts.metadata["/Title"] == book.title
    assert facts.metadata["/Author"] == book.author
    assert facts.metadata["/Producer"] == f"PrintForge {__version__}"
    assert facts.metadata["/Creator"] == f"PrintForge {__version__}"
    assert "/CreationDate" not in facts.metadata
    assert "/ModDate" not in facts.metadata
    assert not any("WeasyPrint" in value for value in facts.metadata.values())


def test_heading_locations_cover_front_matter_parts_and_chapters(rendered, document):
    converged, facts = rendered
    headings = converged.result.headings
    assert headings
    assert headings[0].id == "foreword"
    assert headings[0].page == 1
    part = next(heading for heading in headings if heading.id.startswith("part-1-"))
    assert part.text == "PART I: THE PAGE"
    chapter = next(heading for heading in headings if heading.id == "ch-1")
    assert chapter.page > part.page
    assert {heading.id for heading in headings} >= {c.id for c in document.chapters}
    assert any(heading.level >= 3 for heading in headings)
    pages = [heading.page for heading in headings]
    assert pages == sorted(pages)
    assert pages[0] >= 1 and pages[-1] <= facts.page_count


# ------------------------------------------------------------------ repeatability


def test_repeat_builds_are_byte_identical(tmp_path, document, job, rendered):
    converged, _facts = rendered
    builder = InteriorPdfBuilder(job.settings, metadata=job.metadata)
    first = builder.render(document, converged.plan, tmp_path / "first.pdf")
    time.sleep(1.1)  # the raw WeasyPrint output embeds the current second
    second = builder.render(document, converged.plan, tmp_path / "second.pdf")
    assert first.sha256 == second.sha256
    assert (tmp_path / "first.pdf").read_bytes() == (tmp_path / "second.pdf").read_bytes()


# ------------------------------------------------------------------ failures


def test_manuscript_errors_stop_before_writing(tmp_path, job, rendered):
    converged, _facts = rendered
    broken = tmp_path / "book"
    shutil.copytree(FIXTURE, broken)
    (broken / "chapters" / "zz-broken.md").write_text(
        '---\ntitle: "Broken"\norder: 99\n---\n\n![missing](nope.png)\n', encoding="utf-8"
    )
    document = parse_book(load_book(broken))
    out = tmp_path / "output" / "interior.pdf"
    out.parent.mkdir()
    with pytest.raises(RenderError) as excinfo:
        InteriorPdfBuilder(job.settings, metadata=job.metadata).render(
            document, converged.plan, out
        )
    message = str(excinfo.value)
    assert "DOC-IMAGE-MISSING" in message
    assert "chapters/zz-broken.md" in message
    assert not out.exists()
    assert list(out.parent.iterdir()) == []


def test_undecodable_image_fails_before_writing(tmp_path, job, rendered):
    converged, _facts = rendered
    broken = tmp_path / "book"
    shutil.copytree(FIXTURE, broken)
    (broken / "chapters" / "zz-corrupt.md").write_text(
        '---\ntitle: "Corrupt"\norder: 98\n---\n\n![broken](../images/broken.png)\n',
        encoding="utf-8",
    )
    (broken / "images" / "broken.png").write_bytes(b"not a real image")
    document = parse_book(load_book(broken))
    out = tmp_path / "interior.pdf"
    with pytest.raises(RenderError) as excinfo:
        InteriorPdfBuilder(job.settings, metadata=job.metadata).render(
            document, converged.plan, out
        )
    assert "RENDER-IMAGE-UNREADABLE" in str(excinfo.value)
    assert not out.exists()


def test_missing_font_fails_clearly(tmp_path, document, job, rendered):
    converged, _facts = rendered
    typography = replace(job.settings.typography, body_font="PrintForge No Such Font")
    settings = replace(job.settings, typography=typography)
    out = tmp_path / "interior.pdf"
    with pytest.raises(RenderError, match="PrintForge No Such Font"):
        InteriorPdfBuilder(settings, metadata=job.metadata).render(document, converged.plan, out)
    assert not out.exists()


def test_output_directory_is_created(tmp_path, document, job, rendered):
    converged, _facts = rendered
    out = tmp_path / "nested" / "output" / "interior.pdf"
    result = InteriorPdfBuilder(job.settings, metadata=job.metadata).render(
        document, converged.plan, out
    )
    assert result.path == out
    assert out.read_bytes().startswith(b"%PDF")


def test_existing_output_is_replaced_atomically(tmp_path, document, job, rendered):
    converged, _facts = rendered
    out = tmp_path / "interior.pdf"
    out.write_bytes(b"stale")
    result = InteriorPdfBuilder(job.settings, metadata=job.metadata).render(
        document, converged.plan, out
    )
    assert result.path == out
    assert out.read_bytes().startswith(b"%PDF")


def test_low_resolution_images_are_reported(tmp_path):
    book = load_book(FIXTURES / "markdown-book")
    job = resolve_print_job(book)
    plan = plan_layout(job.settings, KDP, 30, book_title=book.title)
    builder = InteriorPdfBuilder(job.settings, metadata=job.metadata)
    result = builder.render(parse_book(book), plan, tmp_path / "markdown.pdf")
    rules = {item.rule_id for item in result.diagnostics}
    assert "RENDER-IMAGE-DPI" in rules


def test_renderer_satisfies_the_stage_protocol(job):
    from printforge.interfaces import Renderer

    assert isinstance(InteriorPdfBuilder(job.settings), Renderer)
