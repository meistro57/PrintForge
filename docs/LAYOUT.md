# Layout, typography and pagination

`printforge/layout/` turns resolved settings plus a provider profile into a
`LayoutPlan`, and the plan into a CSS Paged Media stylesheet
(`layout.stylesheet(plan)`). Geometry never depends on Markdown parsing. The only
provider-specific inputs are the page size and the minimum gutter, both read through
the `ProviderProfile` protocol.

## Geometry (single pages, mirrored)

- The page box is the provider's interior page size: the trim, or trim + interior bleed.
- **Recto** (right-hand, odd) pages have the inside margin (gutter) on their **left**
  edge. **Verso** (left-hand, even) pages have it on their **right** edge.
  WeasyPrint's `@page :right` / `:left` apply the swap. The PDF is single pages, not
  spreads.
- **Inside margin:** with `margins.inside: "auto"` it is the provider's minimum gutter
  for the page count, plus `margins.gutter_extra` (default 0.125 in). For KDP 6x9 that
  gives 0.5 / 0.625 / 0.75 / 0.875 / 1.0 in across the tiers. An explicit
  `margins.inside` is used verbatim, and the provider checks it against the final page
  count.
- Running heads and folios are in the top/bottom margin boxes. Those boxes span only the
  text column between the inside and outside margins, so they never enter the gutter.
  Their text sits about 0.2 in from the text block, well inside KDP's 0.25 in
  outside-margin minimum when the default 0.75 in top/bottom margins are used.

## Gutter convergence

KDP's gutter depends on the **final** page count, and the page count depends on the
gutter. `paginate_until_stable(settings, provider, render)` resolves this with a bounded
loop:

1. Compute the gutter for a basis page count. The first pass uses the provider minimum,
   24 for KDP.
2. Render the whole book and count the pages.
3. If the gutter required for that page count equals the gutter used, stop: the
   result is consistent with its own page count.
4. Otherwise re-plan for the produced page count and render again.

A gutter that was already tried coming back means oscillation, which raises
`LayoutConvergenceError`. So does exceeding `max_passes` (default 5). The error message
lists every pass. A guessed page count is never accepted as final.

## Sections and page runs

Named pages (CSS `page:`) define each run:

| Run | HTML (`section.` …) | Folio | Running heads | Starts |
|---|---|---|---|---|
| `front-display` | `pf-display` (half title, title, copyright) | none | no | recto |
| `front` | `pf-front` (contents, foreword, …) | lower-roman, or none via `layout.front_matter_folios` | no | recto |
| `part` | `pf-part` (divider page) | none | no | recto |
| `chapter` | `pf-chapter` (chapters, appendices, back matter) | arabic | yes (verso: book title, recto: chapter title) | `layout.chapter_start` (`recto`/`any`) |
| `*-start` | `pf-start` on the first main-matter unit | arabic, **restarts at 1** | as above | always recto |

- The first page of every part/chapter has no running head (`:nth(1 of chapter)`).
- **Intentionally blank pages** (inserted before a recto start) carry no folio and no
  running head (`@page :blank`).
- Roman front-matter folios count from the first page of the book (title page = i),
  as is conventional.

## Typography

- Body, heading and mono fonts are each set as **one family with no fallback list**,
  so a missing font can't silently swap. The renderer checks which fonts were actually
  embedded.
- Other settings: size and leading from `typography`; first-line indent between
  consecutive paragraphs; justified, hyphenated text in the book's language.
- `widows`/`orphans` come from `layout` (default 2). Headings use `break-after: avoid`
  and `break-inside: avoid`.

**Limitation:** WeasyPrint honours widows/orphans and keep-with-next whenever possible.
When that is impossible (for example a heading followed by an image taller than the
remaining space), it breaks anyway without telling the caller. PrintForge cannot detect
this reliably, so preflight lists it as a human inspection item.

## HTML contract for renderers

See the module docstring of `printforge/layout/styles.py`. Chapter titles are
`h1.pf-chapter-title`, which feeds the recto running head through `string-set`.
Markdown body headings shift down one level (`#` → `h2`), so the chapter title stays
the top heading.
