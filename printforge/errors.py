"""Error and exit-code conventions.

Every expected failure is raised as a :class:`PrintForgeError` subclass. The CLI
maps each subclass to a stable, documented exit code so scripts and CI can tell
*why* a run failed without parsing messages. Unexpected exceptions exit with
:attr:`ExitCode.INTERNAL`.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes by failure category (stable public contract)."""

    OK = 0
    INTERNAL = 1  # unexpected bug; please report
    USAGE = 2  # bad command line (argparse convention)
    INPUT = 3  # manuscript/source could not be read or is invalid
    CONFIG = 4  # print settings (print.json / CLI overrides) invalid
    CONSTRAINT = 5  # provider rules violated (trim, page count, paper, ...)
    RENDER = 6  # PDF rendering failed
    PREFLIGHT = 7  # preflight found ERROR-level findings
    OUTPUT = 8  # output directory could not be written/committed
    NOT_IMPLEMENTED = 9  # requested feature is not implemented yet


class PrintForgeError(Exception):
    """Base class for expected, user-actionable failures."""

    exit_code: ExitCode = ExitCode.INTERNAL

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n  hint: {self.hint}"
        return self.message


class InputError(PrintForgeError):
    exit_code = ExitCode.INPUT


class ConfigError(PrintForgeError):
    exit_code = ExitCode.CONFIG


class ConstraintError(PrintForgeError):
    exit_code = ExitCode.CONSTRAINT


class RenderError(PrintForgeError):
    exit_code = ExitCode.RENDER


class PreflightError(PrintForgeError):
    exit_code = ExitCode.PREFLIGHT


class OutputError(PrintForgeError):
    exit_code = ExitCode.OUTPUT


class NotImplementedYetError(PrintForgeError):
    exit_code = ExitCode.NOT_IMPLEMENTED
