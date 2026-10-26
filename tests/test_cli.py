import subprocess
import sys

import pytest

from printforge import __version__
from printforge.cli import main
from printforge.errors import ExitCode


def test_help_exits_zero(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: printforge" in out
    assert "exit codes" in out


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


def test_unknown_provider_is_usage_error(capsys, minimal_book):
    assert main(["build", str(minimal_book), "--provider", "nope"]) == ExitCode.USAGE


def test_build_placeholder_fails_without_side_effects(tmp_path, capsys, minimal_book, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in minimal_book.rglob("*"))
    assert main(["build", str(minimal_book)]) == ExitCode.NOT_IMPLEMENTED
    assert "not implemented" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    assert sorted(p.name for p in minimal_book.rglob("*")) == before


@pytest.mark.parametrize("entry", [["-m", "printforge"]])
def test_module_entrypoint(entry):
    proc = subprocess.run([sys.executable, *entry, "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage: printforge" in proc.stdout
