"""Assemble and render a whole interior: front matter, contents, then the book.

The table of contents shows real page numbers, and its own length affects the
pagination, so the renderer runs a bounded multipass loop:

1. render with the contents rows from the previous pass (empty on the first),
2. page numbers are measured from that render,
3. rebuild the contents with the measured numbers and render again,
4. stop when the rows used and the rows measured are identical.

Gutter convergence (page-count-dependent margins) runs inside each pass. If the
rows never settle, :class:`TocConvergenceError` reports every pass instead of
writing a PDF with wrong page references.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from printforge.config.settings import PrintSettings
from printforge.document.model import Document
from printforge.errors import OutputError, RenderError
from printforge.layout.plan import LayoutPlan, paginate_until_stable
from printforge.log import get_logger
from printforge.providers.base import ProviderProfile
from printforge.render.frontmatter import build_front_units, toc_entries
from printforge.render.interior import InteriorPdfBuilder
from printforge.render.result import RenderResult, TocEntry

log = get_logger("render")

MAX_TOC_PASSES = 5


class TocConvergenceError(RenderError):
    """The printed contents kept changing page numbers between passes."""


def build_interior_pdf(
    document: Document,
    settings: PrintSettings,
    provider: ProviderProfile,
    output_path: Path,
    *,
    metadata: Mapping[str, Any] | None = None,
    max_toc_passes: int = MAX_TOC_PASSES,
) -> RenderResult:
    """Render the interior PDF with generated front matter and contents.

    Passes render to a staging file in the output directory; the target path is
    only replaced once the contents have settled, so a failed build leaves no
    PDF with stale page references behind.
    """
    output_path = Path(output_path)
    builder = InteriorPdfBuilder(settings, metadata=metadata)
    staging = _staging_path(output_path)
    used: tuple[TocEntry, ...] = ()
    basis: int | None = None
    history: list[tuple[int, tuple[TocEntry, ...]]] = []

    try:
        for _attempt in range(max_toc_passes):
            units, unit_ids = build_front_units(settings, builder.metadata, used)
            render = _render_with(builder, document, units, unit_ids, staging)
            converged = paginate_until_stable(
                settings,
                provider,
                render,
                book_title=document.title,
                initial_page_count=basis,
            )
            result = converged.result
            entries = toc_entries(result.headings, settings.toc) if settings.toc.enabled else ()
            history.append((result.page_count, entries))
            log.debug(
                "contents pass %d: %d pages, %d entries (%s)",
                len(history),
                result.page_count,
                len(entries),
                "changed" if entries != used else "stable",
            )
            if entries == used:
                _publish(staging, output_path)
                return replace(result, toc=entries, path=output_path)
            used = entries
            basis = result.page_count
    finally:
        staging.unlink(missing_ok=True)

    raise TocConvergenceError(_describe(history, max_toc_passes))


def _publish(staging: Path, output_path: Path) -> None:
    try:
        os.replace(staging, output_path)
    except OSError as exc:
        raise OutputError(
            f"cannot write {output_path}: {exc.strerror or exc}",
            hint="choose a writable output directory",
        ) from exc


def _staging_path(output_path: Path) -> Path:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            prefix=f".{output_path.name}.", suffix=".pass", dir=output_path.parent
        )
    except OSError as exc:
        raise OutputError(
            f"cannot write to {output_path.parent}: {exc.strerror or exc}",
            hint="choose a writable output directory",
        ) from exc
    os.close(handle)
    return Path(name)


def _render_with(
    builder: InteriorPdfBuilder,
    document: Document,
    units: tuple[str, ...],
    unit_ids: tuple[str, ...],
    output_path: Path,
):
    def render(plan: LayoutPlan) -> tuple[int, RenderResult]:
        result = builder.render(
            document,
            plan,
            output_path,
            front_units=units,
            front_unit_ids=unit_ids,
        )
        return result.page_count, result

    return render


def _describe(history: list[tuple[int, tuple[TocEntry, ...]]], attempts: int) -> str:
    steps = "; ".join(
        f"pass {index + 1}: {pages} pages, {len(entries)} "
        f"{'entry' if len(entries) == 1 else 'entries'}"
        for index, (pages, entries) in enumerate(history)
    )
    return (
        f"table of contents did not settle after {attempts} passes: {steps}. "
        "The contents changed the pagination on every pass; disable toc.enabled, "
        "reduce toc.depth, or adjust typography so a page of headings stops moving"
    )


__all__ = ["MAX_TOC_PASSES", "TocConvergenceError", "build_interior_pdf"]
