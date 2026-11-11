"""Preflight: artifact inspection, rule IDs, reports and the check command."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from printforge.cli import main
from printforge.errors import ExitCode
from printforge.preflight import inspect_build

FIXTURE = Path(__file__).parent / "fixtures" / "print-book"


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("preflight") / "out"
    assert main(["-q", "build", str(FIXTURE), "--output", str(out)]) == ExitCode.OK
    return out


@pytest.fixture
def copy_build(built, tmp_path) -> Path:
    out = tmp_path / "out"
    shutil.copytree(built, out)
    return out


def rules(result) -> set[str]:
    return {item.rule_id for item in result.diagnostics}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_bytes(pages: int, *, font: bool = False) -> bytes:
    writer = PdfWriter()
    first = writer.add_blank_page(width=432, height=648)
    if font:
        descriptor = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        reference = writer._add_object(descriptor)
        first[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference})}
        )
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 24 Tf 72 600 Td (Hello) Tj ET")
        first[NameObject("/Contents")] = writer._add_object(content)
    for _ in range(pages - 1):
        writer.add_blank_page(width=432, height=648)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def replace_interior(out: Path, data: bytes) -> None:
    (out / "interior.pdf").write_bytes(data)
    metadata = read_json(out / "metadata.json")
    metadata["hashes"]["interior.pdf"] = hashlib.sha256(data).hexdigest()
    write_json(out / "metadata.json", metadata)


@pytest.mark.pdf
def test_clean_build_is_ready(built):
    result = inspect_build(built)
    assert not result.has_errors
    assert result.ready
    summary = result.report["summary"]
    assert summary["errors"] == 0
    assert summary["ready"] is True
    assert summary["requires_human_inspection"] is True
    assert result.report["provider"]["name"] == "kdp"
    assert result.report["provider"]["sources"]
    assert result.report["artifacts"]["interior.pdf"]["pages"] >= 24
    assert result.report["source"]["chapters"]
    assert "PREFLIGHT-PAGES-ODD" in rules(result)
    assert "PREFLIGHT-MANUAL-INSPECTION" in rules(result)
    assert "PREFLIGHT-PROVIDER-PREVIEW" in rules(result)


@pytest.mark.pdf
def test_check_command_writes_reports(copy_build, capsys):
    before = {name: sha256(copy_build / name) for name in ("interior.pdf", "cover.pdf")}
    assert main(["-q", "check", str(copy_build)]) == ExitCode.OK
    assert capsys.readouterr().err == ""
    assert (copy_build / "preflight.json").is_file()
    markdown = (copy_build / "preflight.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Print preflight: print-book")
    assert "**Status: READY**" in markdown
    assert "Print Previewer" in markdown
    assert "physical proof" in markdown
    assert before == {name: sha256(copy_build / name) for name in ("interior.pdf", "cover.pdf")}


@pytest.mark.pdf
def test_check_reports_are_path_free(copy_build):
    assert main(["-q", "check", str(copy_build)]) == ExitCode.OK
    text = (copy_build / "preflight.json").read_text(encoding="utf-8")
    assert str(copy_build) not in text
    assert str(copy_build.parent) not in text


def test_check_of_a_missing_directory_is_an_input_error(tmp_path):
    assert main(["check", str(tmp_path / "nope")]) == ExitCode.INPUT


def test_check_of_an_empty_directory_reports_missing_artifacts(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert main(["-q", "check", str(out)]) == ExitCode.PREFLIGHT
    result = inspect_build(out)
    assert "PREFLIGHT-FILE-MISSING" in rules(result)
    assert (out / "preflight.json").is_file()


@pytest.mark.pdf
def test_corrupt_pdf_is_an_error(copy_build):
    (copy_build / "interior.pdf").write_bytes(b"this is not a pdf")
    result = inspect_build(copy_build)
    assert "PREFLIGHT-PDF-INVALID" in rules(result)
    assert result.has_errors


@pytest.mark.pdf
def test_missing_artifact_is_an_error(copy_build):
    (copy_build / "cover.pdf").unlink()
    result = inspect_build(copy_build)
    assert "PREFLIGHT-FILE-MISSING" in rules(result)
    assert result.has_errors


@pytest.mark.pdf
def test_wrong_cover_box_is_an_error(copy_build):
    spec = read_json(copy_build / "cover-spec.json")
    spec["full_cover"]["width"] = "99in"
    write_json(copy_build / "cover-spec.json", spec)
    result = inspect_build(copy_build)
    assert "PREFLIGHT-COVER-SPEC" in rules(result)
    assert result.has_errors


@pytest.mark.pdf
def test_wrong_spine_is_an_error(copy_build):
    spec = read_json(copy_build / "cover-spec.json")
    spec["spine"]["width"] = "0.5in"
    write_json(copy_build / "cover-spec.json", spec)
    result = inspect_build(copy_build)
    assert "PREFLIGHT-COVER-SPINE" in rules(result)


@pytest.mark.pdf
def test_manifest_hash_mismatch_is_an_error(copy_build):
    metadata = read_json(copy_build / "metadata.json")
    metadata["hashes"]["interior.pdf"] = "0" * 64
    write_json(copy_build / "metadata.json", metadata)
    result = inspect_build(copy_build)
    assert "PREFLIGHT-MANIFEST-HASH" in rules(result)


@pytest.mark.pdf
def test_manifest_page_count_mismatch_is_an_error(copy_build):
    metadata = read_json(copy_build / "metadata.json")
    metadata["print"]["page_count"] += 2
    write_json(copy_build / "metadata.json", metadata)
    result = inspect_build(copy_build)
    assert "PREFLIGHT-MANIFEST-PRINT" in rules(result)


@pytest.mark.pdf
def test_under_minimum_page_count_is_an_error(copy_build):
    replace_interior(copy_build, pdf_bytes(2))
    result = inspect_build(copy_build)
    assert "PREFLIGHT-PAGES-RANGE" in rules(result)
    assert result.has_errors


@pytest.mark.pdf
def test_unembedded_font_is_an_error(copy_build):
    replace_interior(copy_build, pdf_bytes(24, font=True))
    result = inspect_build(copy_build)
    assert "PREFLIGHT-FONT-NOT-EMBEDDED" in rules(result)


@pytest.mark.pdf
def test_low_dpi_image_is_reported_with_its_source(tmp_path):
    book = tmp_path / "book"
    shutil.copytree(FIXTURE, book)
    Image.new("RGB", (32, 32), (200, 0, 0)).save(book / "images" / "tiny.png")
    (book / "chapters" / "zz-tiny.md").write_text(
        '---\ntitle: "Tiny Image"\norder: 99\n---\n\n![tiny](images/tiny.png)\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert main(["-q", "build", str(book), "--output", str(out)]) == ExitCode.OK
    report = read_json(out / "build-report.json")
    findings = [item for item in report["diagnostics"] if item["rule_id"] == "PREFLIGHT-IMAGE-DPI"]
    assert findings
    assert "tiny.png" in findings[0]["context"]
    assert "printed at" in findings[0]["message"]
    preflight = read_json(out / "preflight.json")
    assert any(item["rule_id"] == "PREFLIGHT-IMAGE-DPI" for item in preflight["checks"])
