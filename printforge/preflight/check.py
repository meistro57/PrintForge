"""Preflight: prove that a build's artifacts match the provider's rules.

Preflight inspects the files that were actually written (PDFs, cover spec and
manifest), never the in-memory plan, so it catches stale, corrupt or
inconsistent artifacts. Findings use stable ``PREFLIGHT-*`` rule IDs and the
shared :class:`~printforge.diagnostics.Diagnostic` model; ERROR findings stop a
build and make ``printforge check`` exit 7.

The same function runs in two places:

* inside :func:`printforge.publish.build_book`, before the staged build is
  published (with the parsed document available for image source paths);
* from ``printforge check DIR`` on an existing output directory, using only the
  files in that directory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from printforge import __version__
from printforge.config.settings import PrintSettings, validate
from printforge.cover.geometry import CoverGeometry, cover_geometry
from printforge.diagnostics import Diagnostic, Diagnostics, Severity
from printforge.document.model import Document, Image
from printforge.errors import ConfigError
from printforge.fsutil import atomic_write_text
from printforge.preflight.images import placed_images
from printforge.preflight.report import render_markdown
from printforge.providers import get_provider
from printforge.providers.base import ProviderProfile
from printforge.render.pdf import PdfFacts, read_pdf
from printforge.units import Length, UnitError

PREFLIGHT_SCHEMA_VERSION = 1
PREFLIGHT_FILENAME = "preflight.json"
PREFLIGHT_MARKDOWN_FILENAME = "preflight.md"

#: Files a build writes before preflight runs. Preflight checks these names and
#: :mod:`printforge.publish` uses them to decide what a rebuild may replace.
BUILD_ARTIFACTS = (
    "interior.pdf",
    "cover.pdf",
    "cover-spec.json",
    "metadata.json",
    "build-report.json",
)

#: Files preflight itself writes.
PREFLIGHT_ARTIFACTS = (PREFLIGHT_FILENAME, PREFLIGHT_MARKDOWN_FILENAME)

#: Output artifacts whose hashes are recorded in ``metadata.json``.
HASHED_ARTIFACTS = ("interior.pdf", "cover.pdf", "cover-spec.json")

#: Agreed manifest file names.
MANIFEST_FILES = {
    "interior": "interior.pdf",
    "cover": "cover.pdf",
    "cover_spec": "cover-spec.json",
    "report": "build-report.json",
    "preflight": PREFLIGHT_FILENAME,
    "preflight_markdown": PREFLIGHT_MARKDOWN_FILENAME,
}

#: Geometry comparison tolerance (rounding differences between PDF units and CSS).
SIZE_TOLERANCE = Length.pt("0.5")
SPREAD_TOLERANCE = Length.pt("1")

MANUAL_NOTE = (
    "Text overflow, clipping and spine-text clearance cannot be proven from PDF "
    "structure; inspect every page edge and the spine area in a PDF viewer."
)
PREVIEW_NOTE = (
    "Upload-ready means these files match the provider's documented rules, not that "
    "the provider has accepted them. Run Amazon's Print Previewer and order a "
    "physical proof before publishing."
)


@dataclass(frozen=True, slots=True)
class _PdfArtifact:
    name: str
    data: bytes
    sha256: str
    facts: PdfFacts | None


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Findings and the deterministic report for one output directory."""

    output_dir: Path
    report: dict[str, Any]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def ready(self) -> bool:
        return not self.has_errors

    def write(self) -> tuple[Path, Path]:
        """Write ``preflight.json`` and ``preflight.md`` atomically."""
        json_path = self.output_dir / PREFLIGHT_FILENAME
        markdown_path = self.output_dir / PREFLIGHT_MARKDOWN_FILENAME
        atomic_write_text(json_path, json.dumps(self.report, indent=2) + "\n")
        atomic_write_text(markdown_path, render_markdown(self.report))
        return json_path, markdown_path


def inspect_build(
    output_dir: Path,
    *,
    settings: PrintSettings | None = None,
    provider: ProviderProfile | None = None,
    document: Document | None = None,
    require_report: bool = True,
) -> PreflightResult:
    """Inspect an output directory and return findings plus a report payload.

    ``settings``, ``provider`` and ``document`` are optional: the build pipeline
    passes them for exact checks and richer image contexts; the ``check`` command
    omits them and everything is recovered from ``metadata.json``.
    ``require_report`` is False inside the build, where the report is written after
    preflight has collected its findings.
    """
    output_dir = Path(output_dir)
    diagnostics = Diagnostics()
    names = (
        BUILD_ARTIFACTS
        if require_report
        else tuple(name for name in BUILD_ARTIFACTS if name != "build-report.json")
    )
    raw = {name: _read_bytes(output_dir / name, name, diagnostics) for name in names}
    metadata = _parse_json(raw["metadata.json"], "metadata.json", diagnostics)
    spec = _parse_json(raw["cover-spec.json"], "cover-spec.json", diagnostics)
    provider = provider or _provider_from(metadata, diagnostics)
    settings = settings or _settings_from(metadata, diagnostics)

    interior = _pdf_artifact("interior.pdf", raw["interior.pdf"], diagnostics)
    cover = _pdf_artifact("cover.pdf", raw["cover.pdf"], diagnostics)

    geometry = None
    if (
        settings is not None
        and provider is not None
        and interior is not None
        and interior.facts is not None
    ):
        geometry = cover_geometry(settings, provider, interior.facts.page_count)
        _check_interior(interior, settings, provider, diagnostics)
        _check_cover(cover, geometry, diagnostics)
    if geometry is not None:
        _check_cover_spec(spec, geometry, diagnostics)
    _check_manifest(metadata, settings, provider, interior, cover, spec, geometry, raw, diagnostics)
    _check_fonts(interior, cover, diagnostics)
    _check_images(interior, settings, document, diagnostics)
    _check_images(cover, settings, document, diagnostics, provider=provider)
    _notes(diagnostics)
    report = _report(metadata, settings, provider, interior, cover, raw, diagnostics)
    return PreflightResult(output_dir, report, tuple(diagnostics))


# ---------------------------------------------------------------- reading


def _read_bytes(path: Path, name: str, diagnostics: Diagnostics) -> bytes | None:
    if not path.is_file():
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-FILE-MISSING",
            f"{name} is missing",
            context=name,
            suggestion="rebuild with 'printforge build' and check the output directory",
        )
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-FILE-UNREADABLE",
            f"{name} cannot be read: {exc.strerror or exc}",
            context=name,
            suggestion="check file permissions and rebuild",
        )
        return None
    if not data:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-FILE-UNREADABLE",
            f"{name} is empty",
            context=name,
            suggestion="rebuild with 'printforge build'",
        )
        return None
    return data


def _parse_json(data: bytes | None, name: str, diagnostics: Diagnostics) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-FILE-INVALID",
            f"{name} is not readable JSON: {exc}",
            context=name,
            suggestion="rebuild with 'printforge build'",
        )
        return None
    if not isinstance(parsed, dict):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-FILE-INVALID",
            f"{name} must contain a JSON object",
            context=name,
            suggestion="rebuild with 'printforge build'",
        )
        return None
    return parsed


def _pdf_artifact(name: str, data: bytes | None, diagnostics: Diagnostics) -> _PdfArtifact | None:
    if data is None:
        return None
    sha256 = hashlib.sha256(data).hexdigest()
    if not data.startswith(b"%PDF-"):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-PDF-INVALID",
            f"{name} is not a PDF file",
            context=name,
            suggestion="replace the file by rebuilding the book",
        )
        return _PdfArtifact(name, data, sha256, None)
    try:
        facts = read_pdf(data, extract_text=False)
    except Exception as exc:  # pypdf raises several unrelated exception types
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-PDF-INVALID",
            f"{name} cannot be parsed: {exc}",
            context=name,
            suggestion="replace the file by rebuilding the book",
        )
        return _PdfArtifact(name, data, sha256, None)
    if facts.encrypted:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-PDF-ENCRYPTED",
            f"{name} is encrypted; print uploads must not be",
            context=name,
            suggestion="rebuild without PDF encryption or password protection",
        )
    return _PdfArtifact(name, data, sha256, facts)


def _provider_from(
    metadata: Mapping[str, Any] | None, diagnostics: Diagnostics
) -> ProviderProfile | None:
    if metadata is None:
        return None
    name = metadata.get("provider")
    if not isinstance(name, str) or not name:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-PROVIDER",
            "metadata.json does not name a provider",
            context="metadata.json",
            suggestion="rebuild with 'printforge build'",
        )
        return None
    try:
        return get_provider(name)
    except ConfigError as exc:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-PROVIDER",
            str(exc),
            context="metadata.json",
            suggestion="rebuild with a supported provider",
        )
        return None


def _settings_from(
    metadata: Mapping[str, Any] | None, diagnostics: Diagnostics
) -> PrintSettings | None:
    """Recover the resolved settings a build recorded in ``metadata.json``."""
    if metadata is None:
        return None
    settings = metadata.get("settings")
    resolved = settings.get("resolved") if isinstance(settings, Mapping) else None
    if not isinstance(resolved, Mapping):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-SETTINGS",
            "metadata.json does not contain the resolved print settings",
            context="metadata.json",
            suggestion="rebuild with the current PrintForge so preflight can verify geometry",
        )
        return None
    data = dict(resolved)
    data["output"] = {"directory": None}
    try:
        return validate(data, lambda path: "metadata.json")
    except ConfigError as exc:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-SETTINGS",
            f"metadata.json settings are invalid: {exc}",
            context="metadata.json",
            suggestion="rebuild with 'printforge build'",
        )
        return None


# ---------------------------------------------------------------- geometry


def _check_interior(
    interior: _PdfArtifact,
    settings: PrintSettings,
    provider: ProviderProfile,
    diagnostics: Diagnostics,
) -> None:
    facts = interior.facts
    assert facts is not None
    expected = provider.interior_page_size(settings)
    spreads: list[int] = []
    wrong: list[tuple[int, Length, Length]] = []
    for index, size in enumerate(facts.page_sizes, start=1):
        if _close(size.width, expected.width) and _close(size.height, expected.height):
            continue
        if _close(size.width, expected.width * 2, SPREAD_TOLERANCE) and _close(
            size.height, expected.height
        ):
            spreads.append(index)
        else:
            wrong.append((index, size.width, size.height))

    if spreads:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-INTERIOR-SPREAD",
            f"{len(spreads)} page(s) are two-page spreads, not single pages ({_pages(spreads)})",
            context="interior.pdf",
            suggestion="render one page per PDF page; KDP does not accept spreads",
        )
    if wrong:
        page, width, height = wrong[0]
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-INTERIOR-PAGE-SIZE",
            f"{len(wrong)} page(s) do not match the {expected.width} x {expected.height} "
            f"trim (page {page} is {width} x {height})",
            context="interior.pdf",
            suggestion="re-render with the resolved trim and bleed settings",
        )

    limits = provider.page_count_range(settings)
    if not (limits.minimum <= facts.page_count <= limits.maximum):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-PAGES-RANGE",
            f"{facts.page_count} pages is outside the provider's {limits.minimum}-"
            f"{limits.maximum} range for {settings.interior.ink!s} ink on "
            f"{settings.interior.paper!s} paper",
            context="interior.pdf",
            suggestion="add or remove content, or change ink/paper/trim",
        )
    elif facts.page_count % 2:
        diagnostics.add(
            Severity.INFO,
            "PREFLIGHT-PAGES-ODD",
            f"{facts.page_count} pages is odd; the provider inserts a blank page at the end",
            context="interior.pdf",
            suggestion="add a deliberate blank page if you want to control the final spread",
        )


def _check_cover(
    cover: _PdfArtifact | None,
    geometry: CoverGeometry,
    diagnostics: Diagnostics,
) -> None:
    if cover is None or cover.facts is None:
        return
    if cover.facts.page_count != 1:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-COVER-PAGES",
            f"cover.pdf has {cover.facts.page_count} pages; a full-wrap cover is one page",
            context="cover.pdf",
            suggestion="re-render the cover from a single full-wrap template",
        )
    size = cover.facts.size
    if not (_close(size.width, geometry.width) and _close(size.height, geometry.height)):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-COVER-PAGE-SIZE",
            f"cover.pdf is {size.width} x {size.height}, expected "
            f"{geometry.width} x {geometry.height} for {geometry.page_count} pages",
            context="cover.pdf",
            suggestion="rebuild the cover from the finished interior page count",
        )


def _check_cover_spec(
    spec: Mapping[str, Any] | None,
    geometry: CoverGeometry,
    diagnostics: Diagnostics,
) -> None:
    if spec is None:
        return
    problems: list[str] = []
    trim = spec.get("trim")
    if not isinstance(trim, Mapping):
        problems.append("trim is missing")
    else:
        problems.extend(
            (
                _field_problem("trim.width", trim.get("width"), geometry.trim[0]),
                _field_problem("trim.height", trim.get("height"), geometry.trim[1]),
            )
        )
    problems.append(_field_problem("bleed", spec.get("bleed"), geometry.bleed))
    full = spec.get("full_cover")
    if isinstance(full, Mapping):
        problems.extend(
            (
                _field_problem("full_cover.width", full.get("width"), geometry.width),
                _field_problem("full_cover.height", full.get("height"), geometry.height),
            )
        )
    else:
        problems.append("full_cover is missing")
    folds = spec.get("fold_lines")
    if not isinstance(folds, list) or len(folds) != len(geometry.folds):
        problems.append("fold_lines do not match the cover geometry")
    else:
        for index, (value, fold) in enumerate(zip(folds, geometry.folds, strict=True), start=1):
            problems.append(_field_problem(f"fold_lines[{index}]", value, fold))

    spine = spec.get("spine")
    spine_problems: list[str] = []
    if isinstance(spine, Mapping):
        spine_problems.append(_field_problem("spine.width", spine.get("width"), geometry.spine))
        page_count = spine.get("page_count")
        if page_count != geometry.page_count:
            spine_problems.append(
                f"spine.page_count is {page_count!r}, expected {geometry.page_count}"
            )
    else:
        spine_problems.append("spine is missing")

    if any(spine_problems):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-COVER-SPINE",
            "cover-spec.json spine does not match the provider formula: "
            + "; ".join(spine_problems),
            context="cover-spec.json",
            suggestion="rebuild the cover from the finished interior page count",
        )
    if any(problems):
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-COVER-SPEC",
            "cover-spec.json does not match the expected full-wrap geometry: "
            + "; ".join(problems),
            context="cover-spec.json",
            suggestion="rebuild the cover from the finished interior page count",
        )


def _check_manifest(
    metadata: Mapping[str, Any] | None,
    settings: PrintSettings | None,
    provider: ProviderProfile | None,
    interior: _PdfArtifact | None,
    cover: _PdfArtifact | None,
    spec: Mapping[str, Any] | None,
    geometry: CoverGeometry | None,
    raw: Mapping[str, bytes | None],
    diagnostics: Diagnostics,
) -> None:
    if metadata is None:
        return

    if metadata.get("files") != MANIFEST_FILES:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-FILES",
            "metadata.json does not list the agreed artifact file names",
            context="metadata.json",
            suggestion="rebuild with the current PrintForge",
        )

    hashes = metadata.get("hashes")
    hashes = hashes if isinstance(hashes, Mapping) else {}
    for name in HASHED_ARTIFACTS:
        data = raw.get(name)
        expected_hash = hashes.get(name)
        if data is None:
            continue
        if not isinstance(expected_hash, str):
            diagnostics.add(
                Severity.ERROR,
                "PREFLIGHT-MANIFEST-HASH",
                f"metadata.json does not record a hash for {name}",
                context="metadata.json",
                suggestion="rebuild with 'printforge build'",
            )
            continue
        if expected_hash != hashlib.sha256(data).hexdigest():
            diagnostics.add(
                Severity.ERROR,
                "PREFLIGHT-MANIFEST-HASH",
                f"metadata.json records a different {name} hash than the file in this directory",
                context="metadata.json",
                suggestion="rebuild the book so the manifest matches the artifacts",
            )

    print_block = metadata.get("print")
    print_block = print_block if isinstance(print_block, Mapping) else {}
    problems: list[str] = []
    if provider is not None and metadata.get("provider") != provider.name:
        problems.append(f"provider is {metadata.get('provider')!r}, expected {provider.name!r}")
    if settings is not None:
        problems.extend(_manifest_settings_problems(print_block, settings))
    facts = interior.facts if interior is not None else None
    if facts is not None and print_block.get("page_count") != facts.page_count:
        problems.append(
            f"page_count is {print_block.get('page_count')!r}, expected {facts.page_count}"
        )
    if geometry is not None:
        problems.append(_field_problem("spine", print_block.get("spine"), geometry.spine))
        cover_block = print_block.get("cover")
        cover_block = cover_block if isinstance(cover_block, Mapping) else {}
        problems.extend(
            (
                _field_problem("cover.width", cover_block.get("width"), geometry.width),
                _field_problem("cover.height", cover_block.get("height"), geometry.height),
            )
        )
    problems = [problem for problem in problems if problem]
    if problems:
        diagnostics.add(
            Severity.ERROR,
            "PREFLIGHT-MANIFEST-PRINT",
            "metadata.json print details do not match the finished artifacts: "
            + "; ".join(problems),
            context="metadata.json",
            suggestion="rebuild the book so the manifest matches the artifacts",
        )

    source = metadata.get("source")
    chapters = source.get("chapters") if isinstance(source, Mapping) else None
    if not isinstance(chapters, list) or not chapters:
        diagnostics.add(
            Severity.INFO,
            "PREFLIGHT-SOURCE-MISSING",
            "metadata.json does not record manuscript source hashes",
            context="metadata.json",
            suggestion="rebuild with the current PrintForge to record provenance",
        )


def _manifest_settings_problems(
    print_block: Mapping[str, Any], settings: PrintSettings
) -> list[str]:
    problems: list[str] = []
    expected = {
        "format": str(settings.format),
        "ink": str(settings.interior.ink),
        "paper": str(settings.interior.paper),
        "interior_bleed": settings.interior.bleed,
        "finish": str(settings.cover.finish),
    }
    for key, value in expected.items():
        if print_block.get(key) != value:
            problems.append(f"{key} is {print_block.get(key)!r}, expected {value!r}")
    trim = print_block.get("trim")
    trim = trim if isinstance(trim, Mapping) else {}
    problems.extend(
        (
            _field_problem("trim.width", trim.get("width"), settings.trim.width),
            _field_problem("trim.height", trim.get("height"), settings.trim.height),
        )
    )
    return [problem for problem in problems if problem]


# ---------------------------------------------------------------- fonts/images


def _check_fonts(
    interior: _PdfArtifact | None,
    cover: _PdfArtifact | None,
    diagnostics: Diagnostics,
) -> None:
    for artifact in (interior, cover):
        if artifact is None or artifact.facts is None:
            continue
        if artifact is interior and not artifact.facts.fonts:
            diagnostics.add(
                Severity.WARNING,
                "PREFLIGHT-FONT-NONE",
                "interior.pdf uses no fonts; the book may be blank or text was converted to paths",
                context="interior.pdf",
                suggestion="open the PDF and confirm every page has visible text",
            )
        for font in artifact.facts.fonts:
            if font.embedded:
                continue
            diagnostics.add(
                Severity.ERROR,
                "PREFLIGHT-FONT-NOT-EMBEDDED",
                f"font {font.base_name} is not embedded; the provider may substitute it",
                context=f"{artifact.name} ({font.name})",
                suggestion="use an embeddable font in print.json and rebuild",
            )


def _check_images(
    artifact: _PdfArtifact | None,
    settings: PrintSettings | None,
    document: Document | None,
    diagnostics: Diagnostics,
    *,
    provider: ProviderProfile | None = None,
) -> None:
    if artifact is None or artifact.facts is None:
        return
    if provider is not None:
        minimum = provider.cover_rules().min_image_dpi
    elif settings is not None:
        minimum = settings.images.min_dpi
    else:
        return
    try:
        images = placed_images(artifact.data)
    except Exception:  # pragma: no cover - the PDF already passed structural checks
        return
    sources = _image_sources(document)
    for image in images:
        if image.dpi >= minimum:
            continue
        source = sources.get((image.width_px, image.height_px))
        context = f"{artifact.name} page {image.page} ({image.name})"
        if source:
            context += f", {source}"
        diagnostics.add(
            Severity.WARNING,
            "PREFLIGHT-IMAGE-DPI",
            f"{image.width_px} x {image.height_px} px image is printed at "
            f"{image.size_text()} (about {image.dpi:.0f} DPI), below the {minimum} DPI minimum",
            context=context,
            suggestion="replace it with a higher-resolution file or print it smaller",
        )


def _image_sources(document: Document | None) -> dict[tuple[int, int], str]:
    """Map pixel dimensions to a source path when exactly one image matches."""
    if document is None:
        return {}
    candidates: dict[tuple[int, int], list[str]] = {}
    for chapter, image in document.images:
        size = _pixel_size(image)
        if size is None:
            continue
        context = f"{chapter.source} ({image.relative_path or image.source})"
        candidates.setdefault(size, []).append(context)
    return {size: paths[0] for size, paths in candidates.items() if len(paths) == 1}


def _pixel_size(image: Image) -> tuple[int, int] | None:
    if image.path is None:
        return None
    from PIL import Image as PILImage

    try:
        with PILImage.open(image.path) as handle:
            return handle.size
    except Exception:
        return None


# ---------------------------------------------------------------- helpers


def _notes(diagnostics: Diagnostics) -> None:
    diagnostics.add(
        Severity.INFO,
        "PREFLIGHT-MANUAL-INSPECTION",
        MANUAL_NOTE,
        suggestion="check crop edges, the barcode reserve and the spine area by eye",
    )
    diagnostics.add(
        Severity.INFO,
        "PREFLIGHT-PROVIDER-PREVIEW",
        PREVIEW_NOTE,
    )


def _report(
    metadata: Mapping[str, Any] | None,
    settings: PrintSettings | None,
    provider: ProviderProfile | None,
    interior: _PdfArtifact | None,
    cover: _PdfArtifact | None,
    raw: Mapping[str, bytes | None],
    diagnostics: Diagnostics,
) -> dict[str, Any]:
    counts = {severity.value: 0 for severity in Severity}
    for item in diagnostics:
        counts[item.severity.value] += 1
    artifacts: dict[str, Any] = {}
    for artifact in (interior, cover):
        if artifact is not None:
            artifacts[artifact.name] = _artifact_entry(artifact)
    for name in ("cover-spec.json", "metadata.json"):
        data = raw.get(name)
        if data is not None:
            artifacts[name] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    resolved = settings.to_dict() if settings is not None else None
    if resolved is not None:
        resolved.pop("output", None)
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "tool": {"name": "printforge", "version": __version__},
        "book": metadata.get("book") if metadata is not None else None,
        "provider": (
            {
                "name": provider.name,
                "display_name": provider.display_name,
                "sources": [source.to_dict() for source in provider.sources],
            }
            if provider is not None
            else None
        ),
        "print": dict(metadata.get("print") or {}) if metadata is not None else None,
        "settings": resolved,
        "source": dict(metadata.get("source") or {}) if metadata is not None else None,
        "artifacts": artifacts,
        "checks": [item.to_dict() for item in diagnostics],
        "summary": {
            "errors": counts[Severity.ERROR.value],
            "warnings": counts[Severity.WARNING.value],
            "infos": counts[Severity.INFO.value],
            "ready": not diagnostics.has_errors,
            "requires_human_inspection": True,
        },
        "notes": [MANUAL_NOTE, PREVIEW_NOTE],
    }


def _artifact_entry(artifact: _PdfArtifact) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "bytes": len(artifact.data),
        "sha256": artifact.sha256,
    }
    facts = artifact.facts
    if facts is not None:
        entry.update(
            {
                "pages": facts.page_count,
                "page_size": {
                    "width": facts.size.width.to_str("in", 4),
                    "height": facts.size.height.to_str("in", 4),
                },
                "encrypted": facts.encrypted,
            }
        )
    return entry


def _field_problem(path: str, value: Any, expected: Length) -> str:
    if value is None:
        return f"{path} is missing"
    try:
        actual = Length.parse(value)
    except UnitError:
        return f"{path} is {value!r}, expected {expected}"
    if _close(actual, expected):
        return ""
    return f"{path} is {value!r}, expected {expected}"


def _close(actual: Length, expected: Length, tolerance: Length = SIZE_TOLERANCE) -> bool:
    return abs((actual - expected).exact_inches) <= tolerance.exact_inches


def _pages(numbers: list[int]) -> str:
    shown = ", ".join(str(number) for number in numbers[:5])
    return shown + (", ..." if len(numbers) > 5 else "")


__all__ = [
    "BUILD_ARTIFACTS",
    "HASHED_ARTIFACTS",
    "MANIFEST_FILES",
    "PREFLIGHT_ARTIFACTS",
    "PREFLIGHT_FILENAME",
    "PREFLIGHT_MARKDOWN_FILENAME",
    "PREFLIGHT_SCHEMA_VERSION",
    "PreflightResult",
    "inspect_build",
]
