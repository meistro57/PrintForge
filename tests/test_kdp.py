import ast
from pathlib import Path

import pytest

from printforge.config import Ink, Paper, resolve_print_job
from printforge.errors import ConfigError
from printforge.importer import load_book
from printforge.providers import PageSize, ProviderProfile, get_provider, provider_names
from printforge.providers import kdp as kdp_module
from printforge.units import Length

KDP = get_provider("kdp")
IN = Length.inches
PACKAGE = Path(__file__).parent.parent / "printforge"


@pytest.fixture
def book(tmp_path, minimal_book):
    import shutil

    shutil.copytree(minimal_book, tmp_path / "b")
    return tmp_path / "b"


def settings_for(book, **cli):
    return resolve_print_job(load_book(book), cli_overrides=cli).settings


def errors(diags):
    return [d.rule_id for d in diags if d.severity == "ERROR"]


# ------------------------------------------------------------------ registry & sources


def test_registry_and_protocol():
    assert provider_names() == ["kdp"]
    assert isinstance(KDP, ProviderProfile)
    with pytest.raises(ConfigError, match="unknown provider 'lulu'"):
        get_provider("lulu")


def test_sources_cite_official_kdp_pages_with_date():
    urls = {s.url for s in KDP.sources}
    assert "https://kdp.amazon.com/en_US/help/topic/G201857950" in urls
    assert "https://kdp.amazon.com/en_US/help/topic/G201953020" in urls
    assert all(s.url.startswith("https://kdp.amazon.com/") for s in KDP.sources)
    assert all(s.checked == "2026-10-26" for s in KDP.sources)


# ------------------------------------------------------------------ official examples


def test_official_values():
    rules = KDP.cover_rules()
    assert rules.bleed == IN("0.125")
    assert rules.text_safe_margin == IN("0.125")
    assert rules.spine_text_clearance == IN("0.0625")
    assert (rules.barcode_width, rules.barcode_height) == (IN("2"), IN("1.2"))
    assert rules.min_image_dpi == 300
    assert KDP.spine_width(1, Ink.BLACK, Paper.WHITE) == IN("0.002252")
    assert KDP.spine_width(1, Ink.BLACK, Paper.CREAM) == IN("0.0025")
    assert kdp_module.PAGE_LIMITS_6X9[(Ink.BLACK, Paper.WHITE)].minimum == 24


# ------------------------------------------------------------------ page-count tables

GUTTER_CASES = [
    (24, "0.375"),
    (150, "0.375"),
    (151, "0.5"),
    (300, "0.5"),
    (301, "0.625"),
    (500, "0.625"),
    (501, "0.75"),
    (700, "0.75"),
    (701, "0.875"),
    (828, "0.875"),
]


@pytest.mark.parametrize(("pages", "gutter"), GUTTER_CASES)
def test_gutter_brackets(pages, gutter):
    assert KDP.min_inside_margin(pages) == IN(gutter)


@pytest.mark.parametrize("pages", [0, 23, 829, 1000])
def test_gutter_outside_table(pages):
    with pytest.raises(ValueError, match="outside KDP's gutter table"):
        KDP.min_inside_margin(pages)


PAGE_CASES = [24, 150, 151, 300, 301, 500, 501, 701, 828, 829]


@pytest.mark.parametrize("pages", PAGE_CASES)
@pytest.mark.parametrize(
    ("paper", "maximum", "per_page"), [("white", 828, "0.002252"), ("cream", 776, "0.0025")]
)
def test_page_counts_both_papers(book, pages, paper, maximum, per_page):
    settings = settings_for(book, interior={"paper": paper})
    diags = KDP.validate_finished_book(pages, PageSize(IN("6"), IN("9")), settings=settings)
    if pages > maximum:
        assert errors(diags) == ["KDP-PAGES-MAX"]
        assert str(maximum) in diags.errors()[0].message
    else:
        assert errors(diags) == []
    # Spine: page count x per-page thickness, exactly.
    spine = KDP.spine_width(pages, Ink.BLACK, Paper(paper))
    assert spine == IN(per_page) * pages
    assert KDP.spine_text_allowed(pages) is (pages >= 80)


@pytest.mark.parametrize(
    ("pages", "expected"), [(24, "0.054048"), (300, "0.6756"), (828, "1.864656")]
)
def test_spine_examples_white(pages, expected):
    assert KDP.spine_width(pages, Ink.BLACK, Paper.WHITE) == IN(expected)


@pytest.mark.parametrize(
    ("pages", "expected"), [(23, ["KDP-PAGES-MIN"]), (24, []), (2, ["KDP-PAGES-MIN"])]
)
def test_minimum_pages(book, pages, expected):
    diags = KDP.validate_finished_book(
        pages, PageSize(IN("6"), IN("9")), settings=settings_for(book)
    )
    assert errors(diags) == expected


@pytest.mark.parametrize("pages", [79, 80])
def test_spine_text_threshold(pages):
    assert KDP.spine_text_allowed(pages) is (pages == 80)


def test_gutter_checked_against_final_page_count(book):
    settings = settings_for(book)
    size = PageSize(IN("6"), IN("9"))
    assert (
        errors(KDP.validate_finished_book(150, size, settings=settings, inside_margin=IN("0.375")))
        == []
    )
    diags = KDP.validate_finished_book(151, size, settings=settings, inside_margin=IN("0.375"))
    assert errors(diags) == ["KDP-GUTTER"] and "151 pages" in diags.errors()[0].message


# ------------------------------------------------------------------ trim & bleed maths


def test_interior_page_size_no_bleed(book):
    assert KDP.interior_page_size(settings_for(book)) == PageSize(IN("6"), IN("9"))


def test_interior_page_size_with_bleed_geometry(book):
    settings = settings_for(book, interior={"bleed": True})
    assert KDP.interior_page_size(settings) == PageSize(IN("6.125"), IN("9.25"))
    assert KDP.min_outside_margin(settings) == IN("0.375")


@pytest.mark.parametrize(
    ("size", "rules"),
    [
        (PageSize(IN("6"), IN("9")), []),
        (PageSize(Length.pt("432"), Length.pt("648")), []),  # 6x9 in points
        (PageSize(Length.pt("432.4"), IN("9")), []),  # within 0.5 pt tolerance
        (PageSize(IN("6.125"), IN("9")), ["KDP-PAGE-SIZE"]),
        (PageSize(IN("8.5"), IN("11")), ["KDP-PAGE-SIZE", "KDP-PAGE-SIZE"]),
    ],
)
def test_finished_page_dimensions(book, size, rules):
    assert errors(KDP.validate_finished_book(100, size, settings=settings_for(book))) == rules


# ------------------------------------------------------------------ settings validation


def test_default_settings_are_valid(book):
    assert errors(KDP.validate_settings(settings_for(book))) == []
    assert errors(KDP.validate_settings(settings_for(book, interior={"paper": "cream"}))) == []


@pytest.mark.parametrize(
    ("override", "rule"),
    [
        ({"trim": {"width": "5in", "height": "8in"}}, "KDP-TRIM-UNSUPPORTED"),
        ({"interior": {"ink": "premium-color"}}, "KDP-INK-UNSUPPORTED"),
        ({"interior": {"paper": "groundwood"}}, "KDP-PAPER-UNSUPPORTED"),
        ({"interior": {"bleed": True}}, "KDP-BLEED-UNSUPPORTED"),
        ({"margins": {"outside": "0.2in"}}, "KDP-MARGIN-OUTSIDE"),
        ({"margins": {"top": "6mm"}}, "KDP-MARGIN-OUTSIDE"),
        ({"margins": {"inside": "0.3in"}}, "KDP-MARGIN-INSIDE"),
    ],
)
def test_unsupported_or_invalid_settings_are_errors(book, override, rule):
    diags = KDP.validate_settings(settings_for(book, **override))
    assert rule in errors(diags)
    assert all(d.suggestion for d in diags.errors())


def test_color_on_cream_is_not_a_kdp_product(book):
    diags = KDP.validate_settings(
        settings_for(book, interior={"ink": "standard-color", "paper": "cream"})
    )
    assert "KDP-PAPER-INVALID" in errors(diags)


def test_low_dpi_setting_is_warning(book):
    import json

    (book / "print.json").write_text(json.dumps({"images": {"min_dpi": 150}}))
    diags = KDP.validate_settings(resolve_print_job(load_book(book)).settings)
    assert [d.rule_id for d in diags.warnings()] == ["KDP-IMAGE-DPI-SETTING"]
    assert not diags.has_errors


def test_outside_margin_minimum_exact_boundary(book):
    ok = KDP.validate_settings(settings_for(book, margins={"outside": "0.25in"}))
    assert errors(ok) == []


def test_provider_defaults_layer_feeds_resolution(book):
    job = resolve_print_job(load_book(book))
    assert job.provenance["trim.width"] == "provider defaults (kdp)"
    assert KDP.default_settings()["interior"]["bleed"] is False


# ------------------------------------------------------------------ isolation


@pytest.mark.parametrize("package", ["importer", "document", "config"])
def test_provider_code_does_not_leak_into_core(package):
    for path in (PACKAGE / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("printforge.providers.kdp"), path
                if package != "config":
                    assert not node.module.startswith("printforge.providers"), path
