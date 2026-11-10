"""Interior PDF rendering: semantic document + layout plan -> print-ready PDF.

The WeasyPrint adapter (``printforge.render.weasy``) is not imported here so
``printforge.render`` stays importable without the native rendering stack.
"""

from printforge.render.base import LaidOutDocument, RenderedPage
from printforge.render.html import HeadingAnchor, HtmlBuild, build_html
from printforge.render.interior import HeadingLocation, InteriorPdfBuilder, RenderResult
from printforge.render.pdf import EmbeddedFont, PdfFacts, normalize_pdf, read_pdf

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
    "build_html",
    "normalize_pdf",
    "read_pdf",
]
