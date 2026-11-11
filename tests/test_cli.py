"""CLI behaviour: build, inspect, discover, exit codes and overwrite rules."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from printforge import __version__
from printforge.cli import main
from printforge.errors import ExitCode
from printforge.publish import ARTIFACTS

FIXTURE = Path(__file__).parent / "fixtures" / "print-book"


def hash_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


MANUSCRIPT_BEFORE = hash_tree(FIXTURE)


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """One quiet build, shared by the read-only assertions."""
    out = tmp_path_factory.mktemp("cli-build") / "out"
    assert main(["-q", "build", str(FIXTURE), "--output", str(out)]) == ExitCode.OK
    return out


def test_help_exits_zero(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: printforge" in out
    assert "exit codes" in out
    assert "examples" in out
    assert "manual upload" in out


def test_version(capsys):
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_usage_error(capsys):
    assert main([]) == ExitCode.USAGE
    assert "required" in capsys.readouterr().err


def test_unknown_command_is_usage_error(capsys):
    assert main(["publish-to-amazon"]) == ExitCode.USAGE
    assert "invalid choice" in capsys.readouterr().err


def test_unknown_option_is_usage_error(capsys, minimal_book):
    assert main(["build", str(minimal_book), "--no-such-flag"]) == ExitCode.USAGE
    assert "unrecognized arguments" in capsys.readouterr().err


def test_unknown_provider_is_a_config_error(capsys, minimal_book):
    assert main(["build", str(minimal_book), "--provider", "nope"]) == ExitCode.CONFIG
    assert "unknown provider" in capsys.readouterr().err


def test_build_help_documents_the_outputs(capsys):
    assert main(["build", "--help"]) == 0
    out = capsys.readouterr().out
    assert "interior.pdf" in out
    assert "cover-spec.json" in out
    assert "--force" in out


@pytest.mark.pdf
def test_build_writes_all_artifacts(built):
    assert sorted(path.name for path in built.iterdir()) == sorted(ARTIFACTS)
    for name in ("interior.pdf", "cover.pdf"):
        assert (built / name).read_bytes().startswith(b"%PDF")
    metadata = json.loads((built / "metadata.json").read_text())
    report = json.loads((built / "build-report.json").read_text())
    assert metadata["book"] == "print-book"
    assert metadata["print"]["page_count"] >= 24
    assert metadata["files"] == {
        "interior": "interior.pdf",
        "cover": "cover.pdf",
        "cover_spec": "cover-spec.json",
        "report": "build-report.json",
    }
    assert report["book"] == "print-book"
    assert report["summary"]["errors"] == 0
    assert set(report["artifacts"]) == {"interior.pdf", "cover.pdf", "cover-spec.json"}


@pytest.mark.pdf
def test_build_does_not_touch_the_manuscript(built):
    assert hash_tree(FIXTURE) == MANUSCRIPT_BEFORE


@pytest.mark.pdf
def test_build_refuses_to_replace_without_force(built, capsys):
    before = hash_tree(built)
    assert main(["build", str(FIXTURE), "--output", str(built)]) == ExitCode.OUTPUT
    assert "already contains a PrintForge build" in capsys.readouterr().err
    assert hash_tree(built) == before


@pytest.mark.pdf
def test_force_replaces_the_build_deterministically(tmp_path, built):
    out = tmp_path / "out"
    shutil.copytree(built, out)
    original = hash_tree(built)
    args = ["-q", "build", str(FIXTURE), "--output", str(out), "--force"]
    assert main(args) == ExitCode.OK
    assert hash_tree(out) == original
    assert main([*args, "--paper", "cream"]) == ExitCode.OK
    assert hash_tree(out)["cover.pdf"] != original["cover.pdf"]
    assert json.loads((out / "metadata.json").read_text())["print"]["paper"] == "cream"


@pytest.mark.pdf
def test_failed_build_leaves_the_previous_output_intact(tmp_path, built):
    out = tmp_path / "out"
    shutil.copytree(built, out)
    original = hash_tree(out)
    broken = tmp_path / "book"
    shutil.copytree(FIXTURE, broken)
    (broken / "chapters" / "zz-broken.md").write_text(
        '---\ntitle: "Broken"\norder: 99\n---\n\n![missing](nope.png)\n', encoding="utf-8"
    )
    assert main(["build", str(broken), "--output", str(out), "--force"]) == ExitCode.INPUT
    assert hash_tree(out) == original
    assert [path.name for path in out.parent.iterdir() if path.name.startswith(".")] == []


def test_build_refuses_unrelated_files_even_with_force(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.txt").write_text("keep me", encoding="utf-8")
    assert main(["build", str(FIXTURE), "--output", str(out), "--force"]) == ExitCode.OUTPUT
    assert (out / "notes.txt").read_text() == "keep me"
    assert not (out / "interior.pdf").exists()


@pytest.mark.pdf
def test_build_reports_provider_constraints(tmp_path, capsys, minimal_book):
    out = tmp_path / "out"
    assert main(["build", str(minimal_book), "--output", str(out)]) == ExitCode.CONSTRAINT
    err = capsys.readouterr().err
    assert "KDP-PAGES-MIN" in err
    assert not out.exists()


def test_inspect_prints_a_json_report(tmp_path, capsys):
    unused = tmp_path / "unused"
    assert main(["inspect", str(FIXTURE), "--output", str(unused)]) == ExitCode.OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["book"]["slug"] == "print-book"
    assert payload["book"]["chapters"] == len(payload["chapters"])
    assert payload["chapters"][0]["kind"] == "front-matter"
    assert payload["document"]["images"] == 1
    assert payload["provider"]["name"] == "kdp"
    assert payload["settings"]["provider"] == "kdp"
    assert payload["diagnostics"] == []
    assert not unused.exists()


def test_inspect_reports_errors_as_preflight_failures(tmp_path, capsys):
    broken = tmp_path / "book"
    shutil.copytree(FIXTURE, broken)
    (broken / "chapters" / "zz-broken.md").write_text(
        '---\ntitle: "Broken"\norder: 99\n---\n\n![missing](nope.png)\n', encoding="utf-8"
    )
    assert main(["inspect", str(broken)]) == ExitCode.PREFLIGHT
    payload = json.loads(capsys.readouterr().out)
    diagnostics = {(item["stage"], item["rule_id"]) for item in payload["diagnostics"]}
    assert ("document", "DOC-IMAGE-MISSING") in diagnostics


def test_quiet_inspect_writes_nothing_to_stderr(capsys):
    assert main(["-q", "inspect", str(FIXTURE)]) == ExitCode.OK
    assert capsys.readouterr().err == ""


def test_discover_lists_book_directories(capsys, bookforge_root):
    assert main(["discover", str(bookforge_root)]) == ExitCode.OK
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "src/content/books/sample-book",
        "src/content/books/second-book",
    ]


def test_discover_of_an_empty_directory_prints_nothing(capsys, tmp_path):
    assert main(["discover", str(tmp_path)]) == ExitCode.OK
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("entry", [["-m", "printforge"]])
def test_module_entrypoint(entry):
    proc = subprocess.run([sys.executable, *entry, "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage: printforge" in proc.stdout
