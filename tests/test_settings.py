import json
from pathlib import Path

import pytest

from printforge.cli import main
from printforge.config import (
    Ink,
    Paper,
    SpineText,
    normalize_isbn,
    resolve_print_job,
)
from printforge.config.cli_overrides import parse_trim
from printforge.errors import ConfigError, ExitCode
from printforge.importer import load_book
from printforge.units import Length

EXAMPLE = Path(__file__).parent.parent / "examples" / "print.json"


@pytest.fixture
def book_dir(tmp_path, minimal_book):
    import shutil

    target = tmp_path / "minimal-book"
    shutil.copytree(minimal_book, target)
    return target


def write_config(path: Path, data) -> Path:
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


def resolve(book_dir, **kwargs):
    return resolve_print_job(load_book(book_dir), **kwargs)


# ---------------------------------------------------------------- defaults


def test_defaults_without_print_json(book_dir):
    job = resolve(book_dir)
    s = job.settings
    assert s.provider == "kdp" and s.format == "paperback"
    assert (s.trim.width, s.trim.height) == (Length.parse("6in"), Length.parse("9in"))
    assert s.interior.bleed is False
    assert (s.interior.ink, s.interior.paper) == (Ink.BLACK, Paper.WHITE)
    assert s.margins.inside is None  # auto
    assert s.metadata.isbn is None and s.metadata.copyright_year is None
    assert job.layers == ("platform defaults", "provider defaults (kdp)")
    assert job.config_label is None and job.config_sha256 is None
    assert job.provenance["trim.width"] == "provider defaults (kdp)"
    assert job.provenance["typography.font_size"] == "platform defaults"
    assert job.metadata["title"] == "A Minimal Book"
    assert not (book_dir / "print.json").exists()  # never created


def test_example_print_json_is_valid(book_dir):
    job = resolve(book_dir, config_path=EXAMPLE)
    assert job.config_label == "print.json"
    assert job.settings.metadata.language == "en"


# ---------------------------------------------------------------- precedence


def test_precedence_platform_provider_config_cli(book_dir):
    write_config(
        book_dir / "print.json",
        {
            "trim": {"width": "5in", "height": "8in"},
            "interior": {"paper": "cream"},
            "toc": {"depth": 2},
        },
    )
    job = resolve(
        book_dir,
        cli_overrides={"trim": parse_trim("5.5x8.5"), "toc": {"depth": 3}},
    )
    s = job.settings
    assert s.trim.width == Length.parse("5.5in")  # CLI beats print.json
    assert s.interior.paper is Paper.CREAM  # print.json beats provider
    assert s.interior.ink is Ink.BLACK  # provider default kept
    assert s.toc.depth == 3
    assert job.layers[-2:] == ("print.json", "command line")
    assert job.provenance["trim.width"] == "command line"
    assert job.provenance["interior.paper"] == "print.json"
    assert job.provenance["interior.ink"] == "provider defaults (kdp)"


def test_config_flag_replaces_sibling_print_json(book_dir, tmp_path):
    write_config(book_dir / "print.json", {"interior": {"paper": "cream"}})
    other = write_config(tmp_path / "alt.json", {"toc": {"depth": 2}})
    job = resolve(book_dir, config_path=other)
    assert job.settings.interior.paper is Paper.WHITE  # sibling ignored
    assert job.settings.toc.depth == 2
    assert job.config_label == "alt.json"
    assert job.config_dir == tmp_path.resolve()


def test_missing_config_flag_file(book_dir, tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        resolve(book_dir, config_path=tmp_path / "nope.json")


# ---------------------------------------------------------------- determinism


def test_resolution_is_deterministic_and_machine_independent(book_dir, tmp_path):
    write_config(book_dir / "print.json", {"margins": {"outside": "15.875mm"}})
    a = json.dumps(resolve(book_dir).to_dict(), sort_keys=True)
    b = json.dumps(resolve(book_dir).to_dict(), sort_keys=True)
    assert a == b
    assert str(tmp_path) not in a and "/home/" not in a
    assert "output" not in json.loads(a)["settings"]
    assert json.loads(a)["settings"]["margins"]["outside"] == "15.875mm"
    assert json.loads(a)["settings"]["margins"]["inside"] == "auto"


def test_mm_and_inch_inputs_resolve_to_same_geometry(book_dir):
    write_config(book_dir / "print.json", {"trim": {"width": "152.4mm", "height": "228.6mm"}})
    s = resolve(book_dir).settings
    assert s.trim.width == Length.parse("6in") and s.trim.height == Length.parse("9in")


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"interior": {"paper": "pink"}}, "print.json: interior.paper: must be one of"),
        ({"interior": {"bleed": "no"}}, "interior.bleed: must be true or false"),
        ({"trim": {"width": 6}}, "trim.width: expected a length with explicit units"),
        ({"trim": {"width": "30in"}}, "trim.width: must be between 1in and 20in"),
        ({"typography": {"font_size": "40pt"}}, "typography.font_size: must be between"),
        ({"typography": {"line_height": "x"}}, "typography.line_height: must be a number"),
        ({"typography": {"language": "english!"}}, "typography.language: invalid value"),
        ({"toc": {"depth": 0}}, "toc.depth: must be between 1 and 3"),
        ({"images": {"min_dpi": 30}}, "images.min_dpi: must be between 72 and 2400"),
        ({"version": 2}, "version: must be one of: 1"),
        ({"format": "hardcover"}, "format: must be one of: paperback"),
        ({"interior": {"papr": "white"}}, "interior.papr: unknown setting (did you mean 'paper'?)"),
        ({"bogus": 1}, "bogus: unknown setting"),
        ({"trim": "6x9"}, "trim: must be an object"),
        ({"metadata": {"isbn": "978-0-00-000000-1"}}, "not a valid ISBN"),
        ({"metadata": {"isbn": 9780306406157}}, "metadata.isbn: must be a string"),
        ({"metadata": {"copyright_year": "2026"}}, "copyright_year: must be an integer"),
        ({"cover": {"front_image": "https://x.test/a.png"}}, "remote URLs are not allowed"),
        ({"cover": {"front_image": "/etc/a.png"}}, "must be relative to the print.json"),
        ({"cover": {"front_image": "../outside.png"}}, "must not contain '..'"),
        ({"cover": {"background_color": "navy"}}, "use #RRGGBB"),
        ({"cover": {"spine_text": "sometimes"}}, "cover.spine_text: must be one of"),
        (
            {"cover": {"wrap_image": "w.png", "front_image": "f.png"}},
            "cannot be combined with front_image",
        ),
        ({"cover": {"back_image": "b.png"}}, "back_image requires front_image"),
        ({"margins": {"top": "2.5in", "bottom": "2.5in"}}, "less than half the page height"),
        ({"margins": {"inside": "1.5in", "outside": "1.6in"}}, "less than half the width"),
        ({"toc": {"enabled": False, "include_front_matter": True}}, "set toc.enabled"),
    ],
)
def test_invalid_settings_have_field_specific_errors(book_dir, config, message):
    write_config(book_dir / "print.json", config)
    with pytest.raises(ConfigError) as info:
        resolve(book_dir)
    assert message in str(info.value)


def test_all_errors_reported_together(book_dir):
    write_config(
        book_dir / "print.json", {"interior": {"paper": "pink", "ink": "red"}, "toc": {"depth": 7}}
    )
    with pytest.raises(ConfigError) as info:
        resolve(book_dir)
    text = str(info.value)
    assert "interior.paper" in text and "interior.ink" in text and "toc.depth" in text


def test_cli_layer_named_in_errors(book_dir):
    with pytest.raises(ConfigError, match="command line: toc.depth"):
        resolve(book_dir, cli_overrides={"toc": {"depth": 99}})


def test_invalid_json_and_types(book_dir):
    write_config(book_dir / "print.json", '{\n "trim": {,\n}')
    with pytest.raises(ConfigError, match=r"print.json:2:\d+: invalid JSON"):
        resolve(book_dir)
    write_config(book_dir / "print.json", "[1, 2]")
    with pytest.raises(ConfigError, match="must contain a JSON object"):
        resolve(book_dir)


def test_unknown_provider(book_dir):
    write_config(book_dir / "print.json", {"provider": "lulu"})
    with pytest.raises(ConfigError, match="unknown provider 'lulu'"):
        resolve(book_dir)


def test_settings_do_not_mutate_invalid_values(book_dir):
    # 0.1in outside margin is schema-valid; it must be passed through unchanged
    # (provider minimums are enforced, not silently applied, by the provider).
    write_config(book_dir / "print.json", {"margins": {"outside": "0.1in"}})
    assert resolve(book_dir).settings.margins.outside == Length.parse("0.1in")


# ---------------------------------------------------------------- ISBN


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("978-0-306-40615-7", "9780306406157"),
        ("0 306 40615 2", "0306406152"),
        ("080442957X", "080442957X"),
        ("978-0-306-40615-8", None),
        ("12345", None),
    ],
)
def test_isbn(raw, normalized):
    assert normalize_isbn(raw) == normalized


def test_metadata_overrides(book_dir):
    write_config(
        book_dir / "print.json",
        {"metadata": {"title": "Print Title", "isbn": "978-0-306-40615-7", "copyright_year": 2026}},
    )
    job = resolve(book_dir)
    assert job.metadata["title"] == "Print Title"
    assert job.metadata["author"] == "PrintForge Test Fixtures"  # from book.json
    assert job.metadata["isbn"] == "9780306406157"
    assert job.settings.cover.spine_text is SpineText.AUTO


# ---------------------------------------------------------------- CLI


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6x9", {"width": "6in", "height": "9in"}),
        ("5.5 x 8.5in", {"width": "5.5in", "height": "8.5in"}),
        ("152.4x228.6mm", {"width": "152.4mm", "height": "228.6mm"}),
    ],
)
def test_parse_trim(text, expected):
    assert parse_trim(text) == expected


def test_parse_trim_invalid():
    with pytest.raises(ConfigError, match="--trim"):
        parse_trim("six by nine")


def test_settings_command(book_dir, capsys):
    assert main(["settings", str(book_dir), "--paper", "cream", "--toc-depth", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["settings"]["interior"]["paper"] == "cream"
    assert data["provenance"]["toc.depth"] == "command line"


def test_settings_command_config_flag_and_errors(book_dir, tmp_path, capsys):
    cfg = write_config(tmp_path / "x.json", {"interior": {"paper": "pink"}})
    assert main(["settings", str(book_dir), "--config", str(cfg)]) == ExitCode.CONFIG
    assert "interior.paper" in capsys.readouterr().err
    assert main(["settings", str(book_dir), "--ink", "purple"]) == ExitCode.USAGE
    assert main(["settings", str(tmp_path / "missing")]) == ExitCode.INPUT
