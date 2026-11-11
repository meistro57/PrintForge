"""End-to-end publishing engine: one book directory in, local print files out.

The pipeline is the one described in ``docs/ARCHITECTURE.md``:

    importer -> print settings -> provider rules -> document -> interior PDF
             -> cover spec/PDF -> metadata.json + build-report.json

Everything is generated in a temporary directory next to the target and moved
into place only after every stage succeeded, so a failed build never damages a
previous successful one. No network access is involved: the artifacts are for
manual upload to the print-on-demand provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from printforge.book import Book
from printforge.config import ResolvedPrintJob, resolve_print_job
from printforge.cover import CoverResult, build_cover
from printforge.diagnostics import Diagnostic, Severity
from printforge.document import parse_book
from printforge.errors import ConstraintError, InputError, OutputError, PreflightError
from printforge.fsutil import atomic_write_text
from printforge.importer import load_book
from printforge.log import get_logger
from printforge.preflight import (
    BUILD_ARTIFACTS,
    PREFLIGHT_ARTIFACTS,
    PreflightResult,
    inspect_build,
)
from printforge.providers import get_provider
from printforge.providers.base import ProviderProfile
from printforge.render import RenderResult, build_interior_pdf

log = get_logger("publish")

#: Files a build writes, and the only names a `--force` rebuild may replace.
ARTIFACTS = (*BUILD_ARTIFACTS, *PREFLIGHT_ARTIFACTS)

#: Default output root, used when neither --output nor print.json sets one.
DEFAULT_OUTPUT_ROOT = Path("printforge-output")

MANIFEST_SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class BuildResult:
    """A completed build: where it landed and what it contains."""

    output_dir: Path
    interior: RenderResult
    cover: CoverResult
    metadata: dict[str, Any]
    report: dict[str, Any]


def build_book(
    book_dir: Path,
    *,
    config_path: Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
    output_dir: Path | None = None,
    force: bool = False,
) -> BuildResult:
    """Build the interior, cover, metadata and report for one manuscript."""
    book = load_book(book_dir)
    job = resolve_print_job(book, config_path=config_path, cli_overrides=cli_overrides)
    provider = get_provider(job.provider)
    log.info("imported %s: %d chapter(s)", book.slug, len(book.chapters))
    log.info("print settings from: %s", ", ".join(job.layers))

    staged: list[tuple[str, Diagnostic]] = [("import", item) for item in book.diagnostics]
    provider_settings = provider.validate_settings(job.settings)
    staged.extend(("provider", item) for item in provider_settings)
    errors = [item for item in provider_settings if item.severity is Severity.ERROR]
    if errors:
        raise ConstraintError(_listing("print settings", errors), hint=_CONSTRAINT_HINT)

    document = parse_book(book)
    staged.extend(("document", item) for item in document.diagnostics)
    errors = [item for _stage, item in staged if item.severity is Severity.ERROR]
    if errors:
        raise InputError(_listing("manuscript", errors), hint="fix the reported chapter or asset")

    target = _output_path(output_dir, job, book)
    _check_target(target, force)
    temporary = _temporary_output(target)
    try:
        interior = build_interior_pdf(
            document,
            job.settings,
            provider,
            temporary / "interior.pdf",
            metadata=job.metadata,
        )
        staged.extend(("render", item) for item in interior.diagnostics)
        log.info(
            "interior: %d pages, %s x %s",
            interior.page_count,
            interior.size.width.to_str("in"),
            interior.size.height.to_str("in"),
        )

        finished = provider.validate_finished_book(
            interior.page_count,
            interior.size,
            settings=job.settings,
            inside_margin=interior.inside_margin,
        )
        staged.extend(("provider", item) for item in finished)
        errors = [item for item in finished if item.severity is Severity.ERROR]
        if errors:
            raise ConstraintError(_listing("finished book", errors), hint=_CONSTRAINT_HINT)

        cover = build_cover(
            job.settings,
            provider,
            interior.page_count,
            pdf_path=temporary / "cover.pdf",
            spec_path=temporary / "cover-spec.json",
            metadata=job.metadata,
            config_dir=job.config_dir,
        )
        staged.extend(("cover", item) for item in cover.diagnostics)
        log.info(
            "cover: %s x %s, spine %s",
            cover.spec["full_cover"]["width"],
            cover.spec["full_cover"]["height"],
            cover.spec["spine"]["width"],
        )

        metadata = _manifest(job, book, provider, interior, cover)
        atomic_write_text(temporary / "metadata.json", json.dumps(metadata, indent=2) + "\n")

        preflight = inspect_build(
            temporary,
            settings=job.settings,
            provider=provider,
            document=document,
            require_report=False,
        )
        staged.extend(("preflight", item) for item in preflight.diagnostics)
        if preflight.has_errors:
            errors = [item for item in preflight.diagnostics if item.severity is Severity.ERROR]
            raise PreflightError(
                _listing("preflight", errors),
                hint="preflight refuses to publish artifacts the provider may reject",
            )

        report = _report(book, provider, staged, interior, cover, preflight)
        atomic_write_text(temporary / "build-report.json", json.dumps(report, indent=2) + "\n")
        preflight.write()
        _log_diagnostics(staged)
        _commit(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    log.info("wrote %s", target)
    return BuildResult(
        output_dir=target,
        interior=interior,
        cover=cover,
        metadata=metadata,
        report=report,
    )


_CONSTRAINT_HINT = (
    "adjust print.json or the command-line print settings to a configuration the provider accepts"
)


# ---------------------------------------------------------------- output


def _output_path(output_dir: Path | None, job: ResolvedPrintJob, book: Book) -> Path:
    if output_dir is not None:
        return Path(output_dir)
    configured = job.settings.output.directory
    if configured:
        return Path(configured)
    return DEFAULT_OUTPUT_ROOT / book.slug


def _check_target(target: Path, force: bool) -> None:
    if not target.exists():
        return
    if not target.is_dir():
        raise OutputError(
            f"output path is not a directory: {target}",
            hint="choose a directory for --output",
        )
    entries = sorted(entry.name for entry in target.iterdir())
    if not entries:
        return
    unknown = [name for name in entries if name not in ARTIFACTS]
    if unknown:
        raise OutputError(
            f"output directory contains files PrintForge did not write: {', '.join(unknown)}",
            hint="choose an empty or new --output directory; PrintForge never deletes other files",
        )
    if not force:
        raise OutputError(
            f"output directory already contains a PrintForge build: {target}",
            hint="pass --force to replace it",
        )


def _temporary_output(target: Path) -> Path:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{target.name}.build.", dir=target.parent))
    except OSError as exc:
        raise OutputError(
            f"cannot create the output directory {target.parent}: {exc.strerror or exc}",
            hint="choose a writable --output directory",
        ) from exc


def _commit(temporary: Path, target: Path) -> None:
    """Move the finished build into place, replacing only a previous build."""
    try:
        if not target.exists():
            os.replace(temporary, target)
            return
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
            os.replace(temporary, target)
            return
        backup = Path(tempfile.mkdtemp(prefix=f".{target.name}.old.", dir=target.parent))
        backup.rmdir()
        os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except OSError:
            os.replace(backup, target)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    except OSError as exc:
        raise OutputError(
            f"cannot write the build to {target}: {exc.strerror or exc}",
            hint="check permissions and free space",
        ) from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


# ---------------------------------------------------------------- manifest


def _manifest(
    job: ResolvedPrintJob,
    book: Book,
    provider: ProviderProfile,
    interior: RenderResult,
    cover: CoverResult,
) -> dict[str, Any]:
    settings = job.settings
    metadata = job.metadata
    keys = (
        "title",
        "subtitle",
        "author",
        "description",
        "language",
        "isbn",
        "publisher",
        "copyright_year",
        "copyright_holder",
        "edition",
    )
    spec_hash = hashlib.sha256(cover.spec_path.read_bytes()).hexdigest()
    resolved = settings.to_dict()
    resolved.pop("output", None)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "provider": provider.name,
        "display_name": provider.display_name,
        "book": book.slug,
        "metadata": {key: metadata.get(key) for key in keys},
        "print": {
            "format": str(settings.format),
            "trim": {
                "width": settings.trim.width.to_str("in"),
                "height": settings.trim.height.to_str("in"),
            },
            "ink": str(settings.interior.ink),
            "paper": str(settings.interior.paper),
            "interior_bleed": settings.interior.bleed,
            "finish": str(settings.cover.finish),
            "page_count": interior.page_count,
            "spine": cover.spec["spine"]["width"],
            "cover": {
                "width": cover.spec["full_cover"]["width"],
                "height": cover.spec["full_cover"]["height"],
            },
        },
        "settings": {
            "layers": list(job.layers),
            "config": {"file": job.config_label, "sha256": job.config_sha256},
            "resolved": resolved,
        },
        "source": _source_hashes(book),
        "files": {
            "interior": "interior.pdf",
            "cover": "cover.pdf",
            "cover_spec": "cover-spec.json",
            "report": "build-report.json",
            "preflight": "preflight.json",
            "preflight_markdown": "preflight.md",
        },
        "hashes": {
            "interior.pdf": interior.sha256,
            "cover.pdf": cover.sha256,
            "cover-spec.json": spec_hash,
        },
    }


def _source_hashes(book: Book) -> dict[str, Any]:
    """Path-free provenance for the manuscript and settings that produced a build."""
    return {
        "book_json": {"file": "book.json", "sha256": book.metadata_sha256},
        "chapters": [
            {"file": chapter.relative_path, "sha256": chapter.sha256} for chapter in book.chapters
        ],
    }


def _report(
    book: Book,
    provider: ProviderProfile,
    staged: list[tuple[str, Diagnostic]],
    interior: RenderResult,
    cover: CoverResult,
    preflight: PreflightResult,
) -> dict[str, Any]:
    counts = {severity.value: 0 for severity in Severity}
    for _stage, item in staged:
        counts[item.severity.value] += 1
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "book": book.slug,
        "provider": provider.name,
        "artifacts": {
            "interior.pdf": {"bytes": _size(interior.path), "sha256": interior.sha256},
            "cover.pdf": {"bytes": _size(cover.pdf_path), "sha256": cover.sha256},
            "cover-spec.json": {
                "bytes": _size(cover.spec_path),
                "sha256": _hash(cover.spec_path),
            },
        },
        "preflight": {
            "ready": preflight.ready,
            "json": "preflight.json",
            "markdown": "preflight.md",
        },
        "diagnostics": [{"stage": stage, **item.to_dict()} for stage, item in staged],
        "summary": {
            "errors": counts[Severity.ERROR.value],
            "warnings": counts[Severity.WARNING.value],
            "infos": counts[Severity.INFO.value],
        },
    }


def _size(path: Path) -> int:
    return path.stat().st_size


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- logging


def _listing(stage: str, diagnostics: list[Diagnostic]) -> str:
    details = "\n".join(f"  - {item.format()}" for item in diagnostics)
    return f"{stage}: {len(diagnostics)} error(s)\n{details}"


def _log_diagnostics(staged: list[tuple[str, Diagnostic]]) -> None:
    for stage, item in staged:
        if item.severity is Severity.WARNING:
            log.warning("%s (%s): %s", item.rule_id, stage, item.message)
        else:
            log.debug("%s (%s): %s", item.rule_id, stage, item.message)


__all__ = [
    "ARTIFACTS",
    "DEFAULT_OUTPUT_ROOT",
    "MANIFEST_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "BuildResult",
    "build_book",
]
