# `print.json` — print settings (schema version 1)

Physical-book settings live **outside** BookForge's `book.json`, in an optional
`print.json` next to it (`src/content/books/<slug>/print.json`) or in any file passed
with `--config FILE`. PrintForge only reads this file; it never creates or edits it,
and it never edits `book.json`.

A complete sample is in [`examples/print.json`](../examples/print.json). Every key is
optional. Unknown keys are **errors** (typos are reported with a "did you mean" hint),
so a misspelled setting is never silently ignored.

## Precedence

Settings are resolved in layers, lowest to highest precedence:

1. **platform defaults** (`printforge/config/defaults.py`). This layer is complete: every setting has a value.
2. **provider defaults**. For `kdp`: paperback, 6 x 9 in, black ink, white paper, no interior bleed.
3. **print.json**: either `<book_dir>/print.json` or the `--config` file.
4. **command-line flags**: `--provider`, `--trim`, `--ink`, `--paper`, `--bleed`/`--no-bleed`, `--toc-depth`, `--output`.

Objects merge key by key; scalars replace. `printforge settings <book_dir> [flags]`
prints the resolved result as JSON. It shows the layers that were applied and, for every
setting, which layer supplied it (`provenance`).

## Units

Lengths **must** carry units: `"6in"`, `"0.125 in"`, `"3.2mm"`, `"0.32cm"`, `"10.5pt"`.
Bare numbers are rejected. Internally, lengths are exact rationals, so converting between
mm/pt/in never drifts. They are serialized as normalized decimals in the unit they were
given (up to 6 decimal places).

## Settings

| Key | Type / allowed values | Default |
|---|---|---|
| `version` | `1` | `1` |
| `provider` | `kdp` | `kdp` |
| `format` | `paperback` | `paperback` |
| `trim.width`, `trim.height` | length, 1in–20in. Provider rules decide which sizes are supported. | `6in` x `9in` |
| `interior.bleed` | boolean. **Interior** bleed only; cover bleed is always applied by the provider. | `false` |
| `interior.ink` | `black`, `standard-color`, `premium-color` | `black` |
| `interior.paper` | `white`, `cream`, `groundwood` | `white` |
| `margins.top`, `.bottom`, `.outside` | length, 0–3in. The provider may enforce a minimum. | `0.75in`, `0.75in`, `0.625in` |
| `margins.inside` | length or `"auto"`. `auto` means the provider's minimum gutter for the **final** page count, plus `gutter_extra`. | `auto` |
| `margins.gutter_extra` | length, 0–1in | `0.125in` |
| `typography.body_font`, `.heading_font`, `.mono_font` | font family names (installed fonts) | `DejaVu Serif` / `DejaVu Serif` / `DejaVu Sans Mono` |
| `typography.font_size` | length, 6pt–18pt | `10.5pt` |
| `typography.line_height` | number, 1.0–2.5 (multiple of the font size) | `1.4` |
| `typography.paragraph_indent` | length, 0–1in | `0.25in` |
| `typography.justify`, `.hyphenate` | boolean | `true`, `true` |
| `typography.language` | BCP 47 tag (hyphenation) | `en` |
| `images.min_dpi` | integer, 72–2400. Images below this effective resolution are reported. | `300` |
| `toc.enabled` | boolean | `true` |
| `toc.depth` | 1 = chapters, 2 = + `##` headings, 3 = + `###` headings | `1` |
| `toc.title` | string | `Contents` |
| `toc.include_front_matter`, `toc.include_parts` | boolean | `false`, `true` |
| `front_matter.half_title`, `.title_page`, `.copyright_page` | boolean | `false`, `true`, `true` |
| `metadata.title`, `.subtitle`, `.author`, `.description` | string or null. Overrides `book.json` for print only. | `null` (use book.json) |
| `metadata.language` | BCP 47 tag or null | `null` |
| `metadata.isbn` | ISBN-10/13 string, checksum-validated, stored digits-only; or null | `null` |
| `metadata.publisher`, `.copyright_holder`, `.edition` | string or null | `null` |
| `metadata.copyright_year` | integer or null | `null` |
| `cover.finish` | `matte`, `glossy` | `matte` |
| `cover.front_image`, `.back_image`, `.wrap_image` | relative file path (relative to the directory containing print.json) or null. No URLs, no absolute paths, no `..`. | `null` |
| `cover.spine_text` | `auto` (only when the provider allows it), `never`, `always` (fail if not allowed) | `auto` |
| `cover.background_color`, `.text_color` | `#RRGGBB` | `#1F2A44`, `#FFFFFF` |
| `cover.back_text` | string or null (defaults to the description) | `null` |
| `layout.chapter_start` | `recto` (chapters open on a right-hand page; a blank verso is inserted when needed) or `any` | `recto` |
| `layout.part_pages` | boolean: a divider page (always recto) before each part | `true` |
| `layout.running_heads` | boolean: verso = book title, recto = chapter title; never on openers, blank or front-matter pages | `true` |
| `layout.folio_position` | `bottom-center`, `bottom-outside` | `bottom-center` |
| `layout.front_matter_folios` | `lower-roman` (i, ii, ...) or `none` | `lower-roman` |
| `layout.chapter_label` | string or null: label above numbered chapter titles ("Chapter 3") | `Chapter` |
| `layout.widows`, `layout.orphans` | integer, 1–5: minimum lines kept together at page breaks | `2`, `2` |
| `output.directory` | output directory, relative to the current working directory | `null` |

PrintForge never invents legal or identifying metadata. If ISBN, copyright year,
copyright holder or publisher are `null`, they are left out; they are never guessed.

## Validation

All problems are reported together. Each one shows the layer it came from and its
dotted path, for example:

    invalid print settings:
      - print.json: interior.paper: must be one of: white, cream, groundwood (got 'pink')
      - command line: toc.depth: must be between 1 and 3, got 9

Cross-field checks:
- The margins must leave at least half the page width and height for text.
- `wrap_image` cannot be combined with `front_image`/`back_image`.
- `back_image` requires `front_image`.
- `toc.include_front_matter` requires `toc.enabled`.

Provider-specific limits (supported trims, minimum gutters, page counts) are checked by
the provider profile; for KDP that is `printforge/providers/kdp.py` (issue #5).

## Reproducibility

The resolved job (`ResolvedPrintJob.to_dict()`) is deterministic. It contains no
absolute paths and no output directory: the config file is identified by its file name
and SHA-256. Paths in `cover.*` stay exactly as written, relative to the config directory.
