"""Interior PDF rendering: semantic document + layout plan -> print-ready PDF.

The WeasyPrint adapter (``printforge.render.weasy``) is not imported here so
``printforge.render`` stays importable without the native rendering stack.
"""

from printforge.render.base import LaidOutDocument, RenderedPage
from printforge.render.build import TocConvergenceError, build_interior_pdf
from printforge.render.frontmatter import build_front_units, toc_entries
from printforge.render.html import HeadingAnchor, HtmlBuild, build_html
from printforge.render.interior import InteriorPdfBuilder
from printforge.render.pdf import EmbeddedFont, PdfFacts, normalize_pdf, read_pdf
from printforge.render.result import HeadingLocation, RenderResult, TocEntry

__all__ = [
    "EmbeddedFont",
    "HeadingAnchor",
    "HeadingLocation",
    "HtmlBuild",
    "InteriorPdfBuilder",
    "LaidOutDocument",
    "PdfFacts",
    "RenderResult",
    "RenderedPage",
    "TocConvergenceError",
    "TocEntry",
    "build_front_units",
    "build_html",
    "build_interior_pdf",
    "normalize_pdf",
    "read_pdf",
    "toc_entries",
]
