"""End-to-end regression: build, publish, preflight and audit the fixture book.

This is the contract a fresh clone must satisfy on Linux with only the packages
in ``pyproject.toml`` plus the native WeasyPrint libraries: one command builds a
KDP paperback, preflight proves the artifacts agree with the manifest, and the
navigation/page map is consistent with the rendered PDF.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from printforge.cli import main
from printforge.config import resolve_print_job
from printforge.errors import ExitCode
from printforge.importer import load_book
from printforge.providers import get_provider
from printforge.publish import ARTIFACTS, build_book
from printforge.units import Length

FIXTURE = Path(__file__).parent / "fixtures" / "print-book"


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    out = tmp_path_factory.mktemp("e2e") / "print-book"
    result = build_book(FIXTURE, output_dir=out)
    return out, result


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.pdf
def test_full_pipeline_writes_the_agreed_artifact_set(published):
    out, _result = published
    assert sorted(path.name for path in out.iterdir()) == sorted(ARTIFACTS)
    for name in ("interior.pdf", "cover.pdf"):
        assert (out / name).read_bytes().startswith(b"%PDF")
    assert (out / "preflight.md").read_text(encoding="utf-8").startswith("# Print preflight")


@pytest.mark.pdf
def test_manifest_matches_the_rendered_pdfs(published):
    out, result = published
    metadata = read_json(out / "metadata.json")
    interior = PdfReader(out / "interior.pdf")
    cover = PdfReader(out / "cover.pdf")
    assert metadata["schema_version"] == 2
    assert metadata["print"]["page_count"] == len(interior.pages) == result.interior.page_count
    assert len(cover.pages) == 1
    assert metadata["hashes"]["interior.pdf"] == sha256(out / "interior.pdf")
    assert metadata["hashes"]["cover.pdf"] == sha256(out / "cover.pdf")
    assert metadata["hashes"]["cover-spec.json"] == sha256(out / "cover-spec.json")

    book = load_book(FIXTURE)
    settings = resolve_print_job(book).settings
    provider = get_provider(settings.provider)
    expected_spine = provider.spine_width(
        len(interior.pages), settings.interior.ink, settings.interior.paper
    )
    assert Length.parse(metadata["print"]["spine"]) == expected_spine
    assert metadata["source"]["book_json"]["sha256"] == book.metadata_sha256
    assert [item["file"] for item in metadata["source"]["chapters"]] == [
        chapter.relative_path for chapter in book.chapters
    ]


@pytest.mark.pdf
def test_navigation_and_page_map_are_consistent(published):
    out, result = published
    page_count = len(PdfReader(out / "interior.pdf").pages)
    assert page_count == result.interior.page_count
    assert result.interior.headings
    assert result.interior.toc
    assert {heading.kind for heading in result.interior.headings} >= {
        "front-matter",
        "part",
        "chapter",
        "appendix",
        "back-matter",
    }
    pages = [heading.page for heading in result.interior.headings]
    assert pages == sorted(pages)
    assert all(1 <= page <= page_count for page in pages)
    assert all(entry.folio for entry in result.interior.toc)


@pytest.mark.pdf
def test_preflight_agrees_with_the_manifest(published):
    out, _result = published
    preflight = read_json(out / "preflight.json")
    metadata = read_json(out / "metadata.json")
    assert preflight["summary"]["ready"] is True
    assert preflight["summary"]["errors"] == 0
    assert preflight["provider"]["name"] == metadata["provider"]
    assert preflight["artifacts"]["interior.pdf"]["sha256"] == metadata["hashes"]["interior.pdf"]
    assert preflight["artifacts"]["interior.pdf"]["pages"] == metadata["print"]["page_count"]
    assert preflight["source"] == metadata["source"]
    assert preflight["settings"] == metadata["settings"]["resolved"]


@pytest.mark.pdf
def test_check_is_repeatable_and_leaves_the_pdfs_alone(published, capsys):
    out, _result = published
    before = {name: sha256(out / name) for name in ("interior.pdf", "cover.pdf")}
    assert main(["-q", "check", str(out)]) == ExitCode.OK
    assert capsys.readouterr().err == ""
    assert before == {name: sha256(out / name) for name in ("interior.pdf", "cover.pdf")}
    first = (out / "preflight.json").read_bytes()
    assert main(["-q", "check", str(out)]) == ExitCode.OK
    assert (out / "preflight.json").read_bytes() == first


@pytest.mark.pdf
def test_a_corrupt_artifact_can_never_be_reported_ready(published, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(published[0], out)
    (out / "interior.pdf").write_bytes(b"not a PDF")
    assert main(["-q", "check", str(out)]) == ExitCode.PREFLIGHT
    preflight = read_json(out / "preflight.json")
    assert preflight["summary"]["ready"] is False
    assert any(item["rule_id"] == "PREFLIGHT-PDF-INVALID" for item in preflight["checks"])
