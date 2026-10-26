"""Structured, non-fatal findings shared by every pipeline stage.

Stages never silently drop problems: anything that is not fatal is recorded as a
:class:`Diagnostic` with a stable ``rule_id`` (e.g. ``IMPORT-DUP-ORDER``) so it
can be surfaced by the CLI and written to build/preflight reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    rule_id: str
    message: str
    context: str | None = None  # file / chapter / section the finding refers to
    suggestion: str | None = None

    def format(self) -> str:
        text = f"[{self.severity}] {self.rule_id}: {self.message}"
        if self.context:
            text += f" ({self.context})"
        if self.suggestion:
            text += f"\n  fix: {self.suggestion}"
        return text

    def to_dict(self) -> dict[str, str | None]:
        return {
            "severity": str(self.severity),
            "rule_id": self.rule_id,
            "message": self.message,
            "context": self.context,
            "suggestion": self.suggestion,
        }


@dataclass(slots=True)
class Diagnostics:
    """An ordered collection of findings."""

    items: list[Diagnostic] = field(default_factory=list)

    def add(
        self,
        severity: Severity,
        rule_id: str,
        message: str,
        *,
        context: str | None = None,
        suggestion: str | None = None,
    ) -> Diagnostic:
        diag = Diagnostic(severity, rule_id, message, context, suggestion)
        self.items.append(diag)
        return diag

    def extend(self, other: Diagnostics | list[Diagnostic]) -> None:
        self.items.extend(other.items if isinstance(other, Diagnostics) else other)

    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.ERROR]

    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.items)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
