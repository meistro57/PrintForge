"""Smoke-test the pinned working stack, including WeasyPrint's native libraries."""

import io

import pytest


def test_parsing_stack_imports():
    import markdown_it
    import yaml

    assert markdown_it.MarkdownIt().render("*x*").strip() == "<p><em>x</em></p>"
    assert yaml.safe_load("a: 1") == {"a": 1}


@pytest.mark.pdf
def test_weasyprint_renders_and_pypdf_reads():
    import pypdf
    import weasyprint

    pdf = weasyprint.HTML(string="<p>PrintForge</p>").write_pdf()
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert "PrintForge" in reader.pages[0].extract_text()
