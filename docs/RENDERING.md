# Rendering the interior PDF

`printforge/render/` turns the semantic document (#4) plus a layout plan (#6)
into one print-ready, single-page PDF.

```python
builder = InteriorPdfBuilder(job.settings, metadata=job.metadata)
result = builder.render(document, plan, output_path)
result.page_count  # measured, not estimated
result.size  # measured page box, e.g. PageSize(6in, 9in)
result.headings  # (id, text, level, kind, page, folio) in document order
result.toc  # resolved contents rows with real folios
result.fonts  # embedded families
result.diagnostics  # (Diagnostic, ...) warnings raised while rendering
result.sha256  # hash of the deterministic PDF bytes
```

`build_interior_pdf` (in `render/build.py`) is the usual entry point: it
generates front matter and the contents, resolves page numbers with a bounded
multipass loop, and only then publishes the file. See
[docs/FRONT_MATTER.md](FRONT_MATTER.md).

`paginate_until_stable` from #6 is the intended caller: pass a function that
renders and returns `(result.page_count, result)` so the gutter is chosen for
the page count the book actually produced.

## Stages

| Module | Job |
|---|---|
| `render/base.py` | Provider-neutral contracts: `RenderedPage`, `LaidOutDocument`, `InteriorRenderer` |
| `render/html.py` | `Document` + `LayoutSettings` -> contract HTML, plus the assets it may load |
| `render/weasy.py` | WeasyPrint adapter: lay out HTML + CSS, expose pages/fonts, draw bytes |
| `render/frontmatter.py` | Half title, title, copyright and contents HTML; TOC row filtering |
| `render/interior.py` | Orchestration: checks, heading map, metadata, atomic write, `RenderResult` |
| `render/build.py` | Front matter + contents multipass assembly and atomic publication |
| `render/pdf.py` | Metadata normalization, reproducible fonts, `read_pdf` inspection |

The pipeline is: build front matter + contents + manuscript HTML, take the
stylesheet from `layout.stylesheet(plan)`, lay out with the adapter,
`write_pdf()`, normalize the bytes, read them back with pypdf, then write the
file atomically (`printforge.fsutil.atomic_write_bytes`, which also creates the
output directory). Multi-pass builds render to a staging file and publish with
`os.replace` only after convergence.

The HTML carries no stylesheet of its own; the CSS is passed to the adapter
separately, as a provider-neutral seam. `WeasyPrintRenderer` is only imported
when a build actually runs, so `printforge.render` imports without the native
stack.

## Security: only declared local assets

`build_html` returns the exact set of image paths the document resolved inside
the book root. The WeasyPrint adapter installs a `LocalOnlyFetcher` that
snapshots those paths and turns any other request (a stylesheet `@import`, a
remote image, a file outside the book) into a fatal error instead of loading it.
Nothing is ever fetched over the network.

## Layout mapping

- Every source chapter becomes one `<section>`: `pf-chapter` for chapters,
  appendices and back matter, `pf-front` for front matter, with `id="sec-<id>"`.
- `layout.part_pages` inserts a `pf-part` divider before the first chapter of
  each new `(part_number, part_title)` run, only for `chapter`-kind chapters. It
  prints `Part N` (when a number exists) and the part title, with a stable
  `part-<number>-<slug>` anchor for the table of contents.
- The first main-matter unit (part divider or chapter) gets `pf-start`, which
  restarts page numbering at 1.
- Chapter openers are `header.pf-opener` with an optional `pf-chapter-label`
  (`layout.chapter_label` + `chapterNumber`, `chapter` kind only) and the title
  as `h1.pf-chapter-title`.
- Markdown headings shift down one level (`#` becomes `h2`, clamped at `h6`) so
  the chapter title stays the top heading.
- `build_html` also accepts pre-rendered `front_units` (title page, contents,
  ...) that are inserted before the manuscript's own front matter; their rows
  and folios are described in [docs/FRONT_MATTER.md](FRONT_MATTER.md).

## Determinism

Rendering is byte-for-byte reproducible for the same document, plan and font
files:

- WeasyPrint records the wall-clock time in the `head.modified` field of every
  embedded font. `render/pdf.py` rewrites each embedded font program with a
  fixed timestamp (`FIXED_FONT_TIMESTAMP`, the sfnt epoch) and recomputes the
  table checksums. This is the only reason raw WeasyPrint output differs between
  two builds of the same input; `write_pdf(pdf_identifier=False)` removes the
  random file identifier.
- The information dictionary is written explicitly: `/Title`, `/Author`,
  `/Subject`, plus `/Producer` and `/Creator` set to `PrintForge <version>`.
  No dates are written and WeasyPrint's `/Producer` is replaced.
- The output is written atomically (temporary file in the target directory,
  then `os.replace`). A failure leaves no file, partial or zero-byte, behind.

If a font program cannot be normalized the build fails with `RenderError`
rather than producing a file that changes on every run.

## Fonts

The stylesheet names exactly one family per role with no fallback list. After
`write_pdf()` the adapter reports the families it actually embedded
(`LaidOutDocument.font_families`); the builder compares them with
`typography.body_font`, `heading_font` and (only when the manuscript contains
code) `mono_font`:

- a configured family missing from the PDF is a `RenderError` naming the font;
- glyphs pulled from any other family (for example CJK characters in a Latin
  font) produce a `RENDER-FONT-FALLBACK` warning and stay in the PDF.

## Images

Effective resolution is estimated the way CSS lays the image out: natural size
at 96 px per inch, shrunk to the text block (`max-width: 100%`,
`max-height: 85%`). The builder then reports:

- `RENDER-IMAGE-DPI` (warning) when the estimate is below `images.min_dpi`;
- `RENDER-IMAGE-LARGE` (warning) when it is above 600 DPI (KDP's guideline),
  which only bloats the file;
- `RENDER-IMAGE-UNREADABLE` (error) when a non-SVG file cannot be decoded, since
  WeasyPrint would otherwise drop it from the PDF without saying so;
- nothing for SVG, whose resolution is vector-defined.

Missing and unsafe images never reach this stage: they are ERROR diagnostics in
the document model and abort the render with the chapter and file named.

## Limits (later issues)

- Interior bleed is rejected by the KDP profile, so no bleed geometry is drawn.
- Front matter and the table of contents are generated by `build_interior_pdf`;
  the low-level builder prints whatever units it is given and reports their
  locations.
- The full-wrap cover is a separate stage; see [docs/COVER.md](COVER.md).
- Links keep `http`, `https`, `mailto` and `#` targets; any other target is
  printed as plain text. Page numbers and cross-references are not rewritten.
- WeasyPrint honours widows/orphans "when possible" and stays silent when a
  page break makes it impossible; this is a human inspection item in [preflight](PREFLIGHT.md).

## Testing

- `tests/test_render_html.py` checks the HTML contract, anchors and asset
  allow-list without touching the PDF stack.
- `tests/test_interior.py` renders a real 45-page manuscript (49 pages with
  the generated front matter and contents) and inspects it with pypdf: 6 x 9 in
  page boxes, extractable text, embedded subset fonts, normalized metadata,
  contents folios matching the destination pages, byte-identical repeat builds,
  and failure behaviour for missing images, undecodable images, missing fonts,
  output directories and TOC nonconvergence.
- The fixture `tests/fixtures/print-book/` is generated from a fixed vocabulary
  and seed by `python tools/generate_print_fixture.py`; it has front matter, two
  parts, six chapters, an appendix, a table, a code block, a blockquote, a list
  and a 1500 px wide diagram. No BookForge checkout or copyrighted content is
  needed.
- Both files are marked `pdf`, so `pytest -m "not pdf"` skips them where Pango
  is unavailable.
