# Front matter and the printed table of contents

`printforge/render/frontmatter.py` generates the pages that precede the
manuscript: half title, title page, copyright page and contents. They are plain
HTML units in the layout contract, inserted by
`printforge.render.html.build_html` before the manuscript's own front matter
(so a foreword chapter still follows them).

```python
result = build_interior_pdf(document, job.settings, provider, "interior.pdf", metadata=job.metadata)
result.toc  # ((TocEntry(id, text, level, folio, kind), ...)
```

`build_interior_pdf` (in `printforge/render/build.py`) is the entry point that
assembles front matter + contents + manuscript and resolves the page numbers;
`printforge build` / `build_book` call it for you.

## Pages

| Setting | Page | Contents |
|---|---|---|
| `front_matter.half_title` (default `false`) | half title | the book title |
| `front_matter.title_page` (default `true`) | title page | title, subtitle, author, publisher |
| `front_matter.copyright_page` (default `true`) | copyright page | copyright notice, edition, ISBN, publisher |

Details:

- All display pages live in one `pf-display` section; each is a
  `<div class="pf-page pf-recto|pf-verso">` as the stylesheet contract requires.
  The copyright page is the verso of the title page when both are enabled.
- Every field comes from resolved metadata (`book.json` plus `print.json`
  overrides). **Nothing is invented**: no placeholder ISBN, no assumed copyright
  holder, no "All rights reserved", no printing location, no publisher identity.
  A field that is absent is simply not printed; a copyright page with no data at
  all is still reserved because the setting selected it.
- `metadata.isbn` is printed in normalized digits because the checksum-validated
  form is what the settings layer stores. The copyright notice is
  `© YEAR HOLDER`, with whichever part exists.
- `toc.enabled` (default `true`) adds the contents section, titled
  `toc.title` (`Contents` by default), in the `front` page run (lower-roman
  folios, no running heads). TOC pages can overflow onto further pages; the run
  continues.

There are no placeholders to select yet: if an ISBN or copyright year is
missing, it stays missing.

## Contents rows

`toc_entries(headings, toc)` turns the renderer's heading map into rows:

| Entry | Level | Included when |
|---|---|---|
| part divider | 1 | `toc.include_parts` (default `true`) |
| chapter, appendix, back matter | 1 | always |
| front-matter chapter | 1 | `toc.include_front_matter` (default `false`) |
| `##` heading | 2 | `toc.depth >= 2` |
| `###` heading | 3 | `toc.depth >= 3` |

`toc.depth` is capped at 3 by the settings schema. Body headings inherit their
chapter's kind, so a foreword's subheadings are also omitted unless front matter
is included. Headings whose text is empty or whitespace are dropped, and long
titles wrap inside the row instead of pushing the page number off the page.

Rows are `<div class="pf-toc-entry pf-toc-level-N">` (plus `pf-toc-part` for
part dividers) containing the link, a `pf-toc-dots` span whose `::after`
content is `leader('.')`, and the folio. Dot leaders and right-aligned numbers
are produced by the stylesheet, not by padding characters in the HTML.

## Page numbers (folios)

The printed page label is computed from the physical page layout, not guessed:

- pages before the main matter are lower roman (`i`, `ii`, ...);
- the first page of the main matter resets the decimal counter to 1, so later
  folios are `page_index - first_main_index + 1`;
- blank versos inserted before a recto start still advance the counter;
- part dividers and display pages print no folio, but they occupy a number in
  the sequence, which is what the contents shows for a part.

`docs/LAYOUT.md` describes the matching CSS counters.

## Multipass resolution

The contents' own length changes pagination, so page numbers are resolved in a
bounded loop (`MAX_TOC_PASSES = 5`):

1. build front matter and contents from the rows of the previous pass (none on
   the first pass);
2. render, converging the gutter for that page count (`paginate_until_stable`);
3. read the heading map from the rendered PDF and rebuild the rows;
4. stop when the rows that were rendered and the rows that were measured are
   identical; otherwise repeat with the new rows.

If the rows never settle, `TocConvergenceError` (a `RenderError`) lists every
pass and suggests disabling the TOC or reducing its depth. No PDF is published
in that case: passes render to a staging file in the output directory, and the
target path is replaced only after convergence, so a failed build cannot leave
stale page references behind.

## Fixture and tests

`tests/fixtures/print-book/` has `book.json`, a `print.json` with
ISBN/publisher/copyright/edition metadata, front matter (foreword), two parts,
six chapters, an appendix and an afterword. `tests/test_frontmatter.py` covers
the generated HTML and row filtering without rendering;
`tests/test_interior.py` renders the assembled PDF and checks that every
contents folio equals the folio printed on the destination page, that the
contents text matches `result.toc`, and that repeat builds are byte-identical.
