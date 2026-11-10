"""Cover geometry, specification and full-wrap PDF tests."""

from __future__ import annotations

import io
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from printforge.config import resolve_print_job
from printforge.config.settings import SpineText
from printforge.cover import COVER_SPEC_VERSION, build_cover, cover_geometry
from printforge.document import parse_book
from printforge.errors import ConfigError, InputError, RenderError
from printforge.importer import load_book
from printforge.providers import get_provider
from printforge.render import read_pdf
from printforge.units import Length

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "print-book"
KDP = get_provider("kdp")


@pytest.fixture(scope="module")
def job():
    return resolve_print_job(load_book(FIXTURE))


@pytest.fixture(scope="module")
def document(job):
    return parse_book(load_book(FIXTURE))


def build(job, page_count, tmp_path, *, settings=None, name="cover", config_dir=None):
    settings = settings or job.settings
    pdf = tmp_path / f"{name}.pdf"
    spec = tmp_path / f"{name}-spec.json"
    result = build_cover(
        settings,
        KDP,
        page_count,
        pdf_path=pdf,
        spec_path=spec,
        metadata=job.metadata,
        config_dir=config_dir or job.config_dir,
    )
    return result, pdf, spec


# ------------------------------------------------------------------ geometry


def test_49_page_geometry_matches_kdp_cover_formulas(job):
    geometry = cover_geometry(job.settings, KDP, 49)
    assert geometry.spine.to_str("in") == "0.110348in"  # 49 * 0.002252
    assert geometry.width.to_str("in") == "12.360348in"  # 2*6 + 2*0.125 + spine
    assert geometry.height.to_str("in") == "9.25in"  # 9 + 2*0.125
    assert [fold.to_str("in") for fold in geometry.folds] == ["6.125in", "6.235348in"]
    assert geometry.back.to_dict() == {
        "x": "0.125in",
        "y": "0.125in",
        "width": "6in",
        "height": "9in",
    }
    assert geometry.front.x.to_str("in") == "6.235348in"
    assert geometry.spine_area.to_dict()["width"] == "0.110348in"


def test_barcode_reserve_sits_inside_the_back_cover(job):
    geometry = cover_geometry(job.settings, KDP, 49)
    assert geometry.barcode.to_dict() == {
        "x": "3.875in",
        "y": "7.675in",
        "width": "2in",
        "height": "1.2in",
    }
    # 0.25in from the trim edges (the provider's barcode inset).
    assert geometry.barcode.x + geometry.barcode.width + Length.inches("0.25") == (
        geometry.back.x + geometry.back.width
    )
    assert geometry.barcode.y + geometry.barcode.height + Length.inches("0.25") == (
        geometry.back.y + geometry.back.height
    )


def test_safe_areas_are_inset_from_the_trim(job):
    geometry = cover_geometry(job.settings, KDP, 49)
    assert geometry.back_safe.to_dict() == {
        "x": "0.25in",
        "y": "0.25in",
        "width": "5.75in",
        "height": "8.75in",
    }
    assert geometry.front_safe.x.to_str("in") == "6.360348in"
    # A thin spine leaves no room between the clearances; never negative.
    assert geometry.spine_safe.width == Length(0)


def test_spine_uses_paper_and_page_count(job):
    cream = replace(job.settings, interior=replace(job.settings.interior, paper="cream"))
    assert cover_geometry(cream, KDP, 200).spine.to_str("in") == "0.5in"  # 200 * 0.0025
    assert cover_geometry(job.settings, KDP, 200).spine.to_str("in") == "0.4504in"
    assert cover_geometry(job.settings, KDP, 200).width.to_str("in") == "12.7004in"


def test_spine_text_threshold_follows_the_provider(job):
    assert cover_geometry(job.settings, KDP, 79).spine_text_allowed is False
    assert cover_geometry(job.settings, KDP, 80).spine_text_allowed is True


@pytest.mark.parametrize("page_count", [0, -1, 1.5, True])
def test_page_count_must_be_a_positive_integer(job, page_count):
    with pytest.raises(ConfigError):
        cover_geometry(job.settings, KDP, page_count)


# ------------------------------------------------------------------ spec


def test_spec_is_complete_and_deterministic(job):
    first = cover_geometry(job.settings, KDP, 49).to_spec(job.settings, KDP)
    second = cover_geometry(job.settings, KDP, 49).to_spec(job.settings, KDP)
    assert first == second
    assert first["schema_version"] == COVER_SPEC_VERSION
    assert first["provider"] == "kdp"
    assert first["trim"] == {"width": "6in", "height": "9in"}
    assert first["bleed"] == "0.125in"
    assert first["spine"] == {"width": "0.110348in", "page_count": 49}
    assert first["full_cover"] == {"width": "12.360348in", "height": "9.25in"}
    assert first["fold_lines"] == ["6.125in", "6.235348in"]
    assert first["interior"] == {"page_count": 49, "paper": "white", "ink": "black"}
    assert first["spine_text"]["allowed"] is False
    assert first["spine_text"]["min_pages"] == 80
    assert first["spine_text"]["mode"] == "auto"
    assert first["cover"]["finish"] == "matte"
    assert {source["url"] for source in first["sources"]}  # KDP help pages
    assert json.dumps(first).count(str(FIXTURE)) == 0


# ------------------------------------------------------------------ PDF


@pytest.fixture(scope="module")
def cover(tmp_path_factory, job):
    directory = tmp_path_factory.mktemp("cover")
    result, pdf, spec = build(job, 49, directory)
    return result, read_pdf(pdf.read_bytes()), pdf, spec


@pytest.mark.pdf
def test_cover_is_one_page_of_the_computed_size(cover):
    result, facts, _pdf, _spec = cover
    assert facts.page_count == 1
    assert result.interior_page_count == 49
    expected_width = 12.360348 * 72
    expected_height = 9.25 * 72
    assert abs(float(facts.size.width.exact_inches) - expected_width / 72) < 0.01
    assert abs(float(facts.size.height.exact_inches) - expected_height / 72) < 0.01


@pytest.mark.pdf
def test_cover_has_no_crop_marks_or_trim_boxes(cover):
    _result, _facts, pdf, _spec = cover
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf.read_bytes()))
    for page in reader.pages:
        assert page.mediabox == page.cropbox
        assert page.mediabox == page.trimbox
        assert page.mediabox == page.bleedbox


@pytest.mark.pdf
def test_fallback_cover_prints_front_and_back_text(cover):
    _result, facts, _pdf, _spec = cover
    assert "The Printer's Field Guide" in facts.text
    assert "A Synthetic Manuscript for Print Testing" in facts.text
    assert "PrintForge Fixtures" in facts.text
    assert "A generated, copyright-free manuscript" in facts.text
    assert "ISBN" not in facts.text
    assert "barcode" not in facts.text.lower()


@pytest.mark.pdf
def test_below_threshold_books_have_no_spine_text(cover):
    _result, facts, _pdf, _spec = cover
    assert facts.text.count("The Printer's Field Guide") == 1


@pytest.mark.pdf
def test_long_books_get_spine_text(tmp_path, job):
    result, pdf, spec = build(job, 200, tmp_path, name="long")
    facts = read_pdf(pdf.read_bytes())
    assert facts.page_count == 1
    assert facts.text.count("The Printer's Field Guide") == 2
    assert result.spec["spine"]["width"] == "0.4504in"
    assert json.loads(spec.read_text())["spine"]["page_count"] == 200
    assert result.diagnostics == ()


@pytest.mark.pdf
def test_spine_text_never_suppresses_it(tmp_path, job):
    settings = replace(job.settings, cover=replace(job.settings.cover, spine_text=SpineText.NEVER))
    _result, pdf, _spec = build(job, 200, tmp_path, settings=settings, name="never")
    assert read_pdf(pdf.read_bytes()).text.count("The Printer's Field Guide") == 1


@pytest.mark.pdf
def test_spine_text_always_fails_below_the_threshold(tmp_path, job):
    settings = replace(job.settings, cover=replace(job.settings.cover, spine_text=SpineText.ALWAYS))
    with pytest.raises(RenderError, match="at least 80 pages"):
        build(job, 49, tmp_path, settings=settings, name="always")
    assert not (tmp_path / "always.pdf").exists()


@pytest.mark.pdf
def test_thin_spine_omits_text_with_a_warning(tmp_path, job):
    result, pdf, _spec = build(job, 80, tmp_path, name="thin")
    facts = read_pdf(pdf.read_bytes())
    assert facts.text.count("The Printer's Field Guide") == 1
    assert [item.rule_id for item in result.diagnostics] == ["COVER-SPINE-TEXT-TIGHT"]


@pytest.mark.pdf
def test_spec_file_matches_the_result(cover):
    result, _facts, _pdf, spec = cover
    assert json.loads(spec.read_text()) == result.spec


@pytest.mark.pdf
def test_wrap_artwork_suppresses_generated_text(tmp_path, job):
    settings = replace(
        job.settings, cover=replace(job.settings.cover, wrap_image="images/cover.jpg")
    )
    result, pdf, _spec = build(job, 100, tmp_path, settings=settings, name="art")
    facts = read_pdf(pdf.read_bytes())
    assert facts.page_count == 1
    assert "The Printer's Field Guide" not in facts.text
    assert result.diagnostics == ()


@pytest.mark.pdf
def test_low_resolution_artwork_is_reported(tmp_path, job):
    settings = replace(
        job.settings, cover=replace(job.settings.cover, wrap_image="images/spread.png")
    )
    result, _pdf, _spec = build(job, 100, tmp_path, settings=settings, name="lowdpi")
    rules = {item.rule_id for item in result.diagnostics}
    assert "COVER-IMAGE-DPI" in rules
    assert "COVER-IMAGE-ASPECT" in rules


@pytest.mark.pdf
def test_missing_artwork_is_actionable(tmp_path, job):
    settings = replace(
        job.settings, cover=replace(job.settings.cover, front_image="images/nope.png")
    )
    with pytest.raises(InputError, match="nope.png"):
        build(job, 49, tmp_path, settings=settings, name="missing")
    assert not (tmp_path / "missing.pdf").exists()
    assert not (tmp_path / "missing-spec.json").exists()


@pytest.mark.pdf
def test_undecodable_artwork_is_actionable(tmp_path, job):
    (tmp_path / "broken.png").write_bytes(b"not an image")
    settings = replace(job.settings, cover=replace(job.settings.cover, front_image="broken.png"))
    with pytest.raises(RenderError, match="cannot be decoded"):
        build(job, 49, tmp_path, settings=settings, name="broken", config_dir=tmp_path)


@pytest.mark.pdf
def test_unsupported_artwork_format_is_rejected(tmp_path, job):
    (tmp_path / "art.txt").write_text("not an image")
    settings = replace(job.settings, cover=replace(job.settings.cover, front_image="art.txt"))
    with pytest.raises(RenderError, match="unsupported format"):
        build(job, 49, tmp_path, settings=settings, name="format", config_dir=tmp_path)


@pytest.mark.pdf
def test_repeat_builds_are_byte_identical(tmp_path, job):
    first, first_pdf, first_spec = build(job, 100, tmp_path, name="one")
    time.sleep(1.1)
    second, second_pdf, second_spec = build(job, 100, tmp_path, name="two")
    assert first.sha256 == second.sha256
    assert first_pdf.read_bytes() == second_pdf.read_bytes()
    assert first_spec.read_text() == second_spec.read_text()


@pytest.mark.pdf
def test_cover_size_follows_the_page_count(cover, tmp_path, job):
    _result, facts, _pdf, _spec = cover
    _long, long_pdf, _long_spec = build(job, 200, tmp_path, name="wide")
    long_facts = read_pdf(long_pdf.read_bytes())
    assert long_facts.size.width > facts.size.width
    assert long_facts.size.height == facts.size.height


@pytest.mark.pdf
def test_cover_uses_the_finished_interior_page_count(tmp_path, document, job):
    from printforge.render import build_interior_pdf

    interior = build_interior_pdf(
        document,
        job.settings,
        KDP,
        tmp_path / "interior.pdf",
        metadata=job.metadata,
    )
    result, _pdf, _spec = build(job, interior.page_count, tmp_path, name="from-interior")
    assert result.interior_page_count == interior.page_count
    assert result.spec["spine"]["page_count"] == interior.page_count
    expected = KDP.spine_width(
        interior.page_count, job.settings.interior.ink, job.settings.interior.paper
    )
    assert result.spec["spine"]["width"] == expected.to_str("in")
