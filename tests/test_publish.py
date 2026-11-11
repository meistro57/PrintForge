"""Publishing engine: the artifact contract and cross-directory determinism."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from printforge.publish import ARTIFACTS, build_book

FIXTURE = Path(__file__).parent / "fixtures" / "print-book"


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    base = tmp_path_factory.mktemp("publish")
    first = build_book(FIXTURE, output_dir=base / "one")
    second = build_book(FIXTURE, output_dir=base / "two")
    return base, first, second


@pytest.mark.pdf
def test_artifacts_are_identical_across_output_directories(builds):
    base, first, second = builds
    assert first.output_dir == base / "one"
    assert sorted(path.name for path in (base / "one").iterdir()) == sorted(ARTIFACTS)
    for name in ARTIFACTS:
        assert (base / "one" / name).read_bytes() == (base / "two" / name).read_bytes(), name
    assert first.metadata == second.metadata
    assert first.report == second.report


@pytest.mark.pdf
def test_report_matches_the_written_artifacts(builds):
    base, first, _second = builds
    report = json.loads((base / "one" / "build-report.json").read_text())
    manifest = json.loads((base / "one" / "metadata.json").read_text())
    assert report["summary"] == {"errors": 0, "warnings": 0, "infos": 0}
    assert report["diagnostics"] == []
    assert report["artifacts"]["interior.pdf"]["sha256"] == manifest["hashes"]["interior.pdf"]
    assert report["artifacts"]["cover.pdf"]["sha256"] == manifest["hashes"]["cover.pdf"]
    assert (
        report["artifacts"]["cover-spec.json"]["sha256"] == (manifest["hashes"]["cover-spec.json"])
    )
    assert manifest["print"]["page_count"] == first.interior.page_count
    assert manifest["print"]["spine"] == first.cover.spec["spine"]["width"]


@pytest.mark.pdf
def test_default_output_directory_is_relative_to_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = build_book(FIXTURE)
    assert result.output_dir == Path("printforge-output") / "print-book"
    assert (tmp_path / "printforge-output" / "print-book" / "interior.pdf").is_file()
