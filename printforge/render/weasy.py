"""WeasyPrint implementation of :class:`~printforge.render.base.InteriorRenderer`.

Network and filesystem access are locked down: the URL fetcher serves only the
exact local files the document declared (resolved images) and turns every other
request into a fatal error, so remote content can never load.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

import pypdf
import weasyprint
from weasyprint.urls import URLFetcher, URLFetcherResponse

from printforge.errors import RenderError
from printforge.render.base import RenderedPage

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


class LocalOnlyFetcher(URLFetcher):
    """Serves only allow-listed local files; everything else is fatal."""

    def __init__(self, allowed: frozenset[Path]) -> None:
        super().__init__(fail_on_errors=True, allowed_protocols=["file"])
        self._allowed = {p.resolve() for p in allowed}
        self.blocked: list[str] = []

    def fetch(self, url: str, headers=None):  # noqa: ARG002 - signature from URLFetcher
        parsed = urlparse(url)
        path = Path(unquote(parsed.path)).resolve() if parsed.scheme == "file" else None
        if path is None or path not in self._allowed:
            self.blocked.append(url)
            raise ValueError(f"resource not allowed: {url}")
        content_type = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return URLFetcherResponse(url, path.read_bytes(), {"Content-Type": content_type})


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class WeasyDocument:
    def __init__(self, document: weasyprint.Document, warnings: tuple[str, ...] = ()) -> None:
        self._document = document
        self.warnings = warnings
        self._pages = tuple(_page_info(i, page) for i, page in enumerate(document.pages))

    @property
    def pages(self) -> tuple[RenderedPage, ...]:
        return self._pages

    def write_pdf(self) -> bytes:
        # No timestamps are emitted (no dcterms dates in the HTML) and no random
        # file identifier, so identical input gives identical bytes.
        return self._document.write_pdf(pdf_identifier=False)


def _page_info(index: int, page) -> RenderedPage:
    # page_type is WeasyPrint-internal (pinned ~=70.0); used for side/name/blank only.
    page_type = page._page_box.page_type
    return RenderedPage(
        index=index,
        side="recto" if page_type.side == "right" else "verso",
        name=page_type.name or "",
        blank=bool(page_type.blank),
        anchors=tuple(page.anchors),
    )


class WeasyPrintRenderer:
    name = "weasyprint"
    version = weasyprint.__version__

    def lay_out(self, html: str, css: str, assets: frozenset[Path]) -> WeasyDocument:
        fetcher = LocalOnlyFetcher(assets)
        capture = _Warnings()
        logger = logging.getLogger("weasyprint")
        logger.addHandler(capture)
        try:
            document = weasyprint.HTML(string=html, url_fetcher=fetcher, base_url=None).render(
                stylesheets=[weasyprint.CSS(string=css, url_fetcher=fetcher)]
            )
        except weasyprint.urls.FatalURLFetchingError as exc:
            blocked = ", ".join(fetcher.blocked) or str(exc)
            raise RenderError(
                f"renderer tried to load a resource that is not an allowed local file: {blocked}",
                hint="only local images inside the book directory can be used",
            ) from exc
        except Exception as exc:
            raise RenderError(f"WeasyPrint failed to lay out the interior: {exc}") from exc
        finally:
            logger.removeHandler(capture)
        css_problems = [m for m in capture.messages if m.lower().startswith("ignored")]
        if css_problems:
            raise RenderError("stylesheet not understood by WeasyPrint: " + "; ".join(css_problems))
        return WeasyDocument(document, tuple(capture.messages))

    def embedded_fonts(self, pdf: bytes) -> list[tuple[str, bool]]:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        found: dict[str, bool] = {}
        for page in reader.pages:
            resources = page.get("/Resources")
            fonts = resources.get_object().get("/Font") if resources else None
            if not fonts:
                continue
            for ref in fonts.get_object().values():
                font = ref.get_object()
                name = str(font.get("/BaseFont", "?")).lstrip("/")
                descriptor = font.get("/FontDescriptor")
                if descriptor is None and "/DescendantFonts" in font:
                    descendant = font["/DescendantFonts"][0].get_object()
                    descriptor = descendant.get("/FontDescriptor")
                embedded = False
                if descriptor is not None:
                    d = descriptor.get_object()
                    embedded = any(k in d for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                elif font.get("/Subtype") == "/Type3":
                    embedded = True  # glyphs are drawn inline
                found[name] = found.get(name, False) or embedded
        return sorted(found.items())
