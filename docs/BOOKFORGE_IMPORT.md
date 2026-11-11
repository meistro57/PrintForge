# Importing a BookForge manuscript

PrintForge reads the same on-disk convention BookForge uses. It is a reader:
nothing in the manuscript directory is ever created, renamed or modified, and
`print.json` is the only file PrintForge expects you to add (next to
`book.json`, never inside BookForge's tracked files).

```
<book>/
  book.json
  chapters/
    ch-1.md
    ch-2.md
  images/            # referenced by chapters; any path inside <book>
  print.json         # optional PrintForge settings (sibling of book.json)
```

Discovery mirrors BookForge: `src/content/books/**/book.json`.

## `book.json`

| Field | Use |
|---|---|
| `slug` | Required. Must match the directory name. Used for the book id and default output directory. |
| `title`, `author` | Required. Printed on the title page and used in the PDF metadata. |
| `subtitle`, `description` | Optional. Printed only when supplied. |
| `order` | Discovery ordering; default `999`. |
| `badge` | Imported for provenance, not printed. |
| `cover`, `ogImage` | Web asset URLs; kept for provenance, never used for print cover artwork. Configure print artwork in `print.json` instead. |
| `theme`, `audiobook` | Web-reader-only; ignored for print and reported as INFO. |

Unknown fields are reported as a warning and ignored. Nothing is invented:
missing metadata is omitted from the title and copyright pages.

## Chapter front matter

| Field | Use |
|---|---|
| `title` | Required, non-empty. Chapter opener and TOC text. |
| `order` | Required number. Chapters sort ascending; ties use a natural filename sort and produce `IMPORT-DUP-ORDER`. |
| `chapterNumber`, `partNumber` | Optional numbers. Drive "Chapter N" labels and part grouping/dividers. |
| `partTitle` | Optional string. Printed on the part divider and used to group consecutive chapters. |
| `isFrontMatter` | Optional boolean, default `false`. Front matter gets roman folios and is excluded from chapter numbering. |
| `slug` | Optional. Defaults to the filename stem. Chapter IDs, anchors and appendix detection use it. |
| `description` | Imported for provenance; not printed. |

## Asset safety

Images must be local files under the book directory. Remote URLs, absolute paths,
`..` escapes and symlinks pointing outside the book root are rejected with an
ERROR (`DOC-IMAGE-UNSAFE`); missing files produce `DOC-IMAGE-MISSING`. Allowed
formats are PNG, JPEG, GIF, WebP and SVG. Raw HTML is never interpreted: it is
printed literally and reported as `DOC-RAW-HTML`.

## Inspect before building

```sh
printforge discover /path/to/BookForge
printforge inspect /path/to/BookForge/src/content/books/my-book
printforge settings /path/to/BookForge/src/content/books/my-book --trim 6x9
```

`inspect` prints chapters, document counts, resolved settings, provenance and
diagnostics without rendering; it exits `7` when an ERROR would stop a build.

## Real-world smoke test

A real BookForge checkout (for example `the-meistro-manual`) is an optional,
local-only smoke test. It is not required by CI and is never bundled.

```sh
printforge discover /path/to/BookForge
printforge build /path/to/BookForge/src/content/books/the-meistro-manual \
  --output build/the-meistro-manual
printforge check build/the-meistro-manual
```

The optional importer test against a checkout is:

```sh
PRINTFORGE_BOOKFORGE_ROOT=/path/to/BookForge pytest tests/test_bookforge_checkout.py
```

Large works can exceed a single KDP paperback volume (for 6 x 9 in black ink on
white paper the maximum is 828 pages). When that happens, split the manuscript
into volumes or adjust typography; PrintForge reports `KDP-PAGES-MAX` rather
than producing an unsupported file.

## Known limitations

- BookForge web presentation fields (`theme`, `audiobook`, web cover URLs) have
  no print meaning and are ignored.
- Raw HTML is not rendered.
- Only the book's own local images are loaded; nothing is fetched.
- Print settings are separate from BookForge: use `print.json`; see
  [PRINT_JSON.md](PRINT_JSON.md).
