from printforge.diagnostics import Diagnostics, Severity
from printforge.errors import (
    ConfigError,
    ConstraintError,
    ExitCode,
    InputError,
    OutputError,
    PreflightError,
    PrintForgeError,
    RenderError,
)
from printforge.interfaces import BookImporter, ProviderProfile, Renderer
from printforge.log import get_logger


def test_exit_codes_are_unique_and_stable():
    values = [c.value for c in ExitCode]
    assert len(values) == len(set(values))
    assert ExitCode.OK == 0 and ExitCode.USAGE == 2


def test_error_classes_map_to_categories():
    assert InputError("x").exit_code is ExitCode.INPUT
    assert ConfigError("x").exit_code is ExitCode.CONFIG
    assert ConstraintError("x").exit_code is ExitCode.CONSTRAINT
    assert RenderError("x").exit_code is ExitCode.RENDER
    assert PreflightError("x").exit_code is ExitCode.PREFLIGHT
    assert OutputError("x").exit_code is ExitCode.OUTPUT


def test_error_hint_in_message():
    assert str(PrintForgeError("bad", hint="do this")) == "bad\n  hint: do this"


def test_diagnostics_collect_and_classify():
    d = Diagnostics()
    d.add(Severity.WARNING, "T-1", "careful", context="ch-1.md")
    assert not d.has_errors
    d.add(Severity.ERROR, "T-2", "broken", suggestion="fix it")
    assert d.has_errors and len(d) == 2
    assert [x.rule_id for x in d.errors()] == ["T-2"]
    assert "fix: fix it" in d.errors()[0].format()
    assert d.items[0].to_dict()["severity"] == "WARNING"


def test_logger_namespace():
    assert get_logger("x").name == "printforge.x"
    assert get_logger("printforge.y").name == "printforge.y"


def test_protocols_are_runtime_checkable():
    class Imp:
        def load(self, book_dir):
            return None

    assert isinstance(Imp(), BookImporter)
    assert not isinstance(Imp(), Renderer)
    assert not isinstance(Imp(), ProviderProfile)
