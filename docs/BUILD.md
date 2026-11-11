# Building a book

One command turns a manuscript into local, upload-ready print files:

```sh
printforge build tests/fixtures/print-book --output build/print-book
```

`printforge build` reads `book.json` and `chapters/*.md` (and an optional
`print.json`), renders the interior and cover, writes the manifest and report,
and stops there. It never uploads anything and never modifies the manuscript.

## Output

The output directory receives exactly these files:

| File | Contents |
|---|---|
| `interior.pdf` | single-page-width interior, 6 x 9 in by default, with generated front matter and contents |
| `cover.pdf` | one full-wrap page: back cover, spine, front cover |
| `cover-spec.json` | cover geometry: trim, bleed, spine, folds, safe areas, barcode reserve, sources |
| `metadata.json` | submission metadata and print geometry for the provider |
| `build-report.json` | artifact sizes/hashes and every diagnostic collected by the build |

Output location, in order of precedence:

1. `--output DIR` (also `-o DIR`);
2. `output.directory` from `print.json`;
3. `printforge-output/<book-slug>` relative to the current working directory.

File names are fixed so scripts can rely on them.

### `metadata.json`

Deterministic, path-free submission data:

```json
{
  "schema_version": 1,
  "provider": "kdp",
  "display_name": "Amazon KDP paperback",
  "book": "print-book",
  "metadata": {"title": "...", "subtitle": "...", "author": "...", "isbn": "...",
               "publisher": "...", "copyright_year": 2026, "...": "..."},
  "print": {"format": "paperback", "trim": {"width": "6in", "height": "9in"},
            "ink": "black", "paper": "white", "interior_bleed": false,
            "finish": "matte", "page_count": 49, "spine": "0.110348in",
            "cover": {"width": "12.360348in", "height": "9.25in"}},
  "settings": {"layers": ["platform defaults", "provider defaults (kdp)",
                          "print.json"], "config": {"file": "print.json", "sha256": "..."}},
  "files": {"interior": "interior.pdf", "cover": "cover.pdf",
            "cover_spec": "cover-spec.json", "report": "build-report.json"},
  "hashes": {"interior.pdf": "...", "cover.pdf": "...", "cover-spec.json": "..."}
}
```

Fields that were not supplied stay `null`; nothing is invented.

### `build-report.json`

```json
{
  "schema_version": 1,
  "book": "print-book",
  "provider": "kdp",
  "artifacts": {"interior.pdf": {"bytes": 122043, "sha256": "..."},
                "cover.pdf": {"bytes": 10502, "sha256": "..."},
                "cover-spec.json": {"bytes": 2079, "sha256": "..."}},
  "diagnostics": [{"stage": "cover", "severity": "WARNING",
                   "rule_id": "COVER-IMAGE-DPI", "message": "...",
                   "context": "...", "suggestion": "..."}],
  "summary": {"errors": 0, "warnings": 1, "infos": 0}
}
```

Stages are `import`, `document`, `provider`, `render` and `cover`. The same
diagnostics are also logged: warnings to stderr, infos only with `-v`.

## Pipeline and exit codes

```
importer -> print settings -> provider settings check -> document
         -> interior (front matter, contents, gutter convergence)
         -> provider finished-book check
         -> cover -> metadata.json + build-report.json -> publish
```

Failures map to the documented exit codes:

| Failure | Exit |
|---|---|
| manuscript cannot be read/parsed, or has ERROR diagnostics (for example a missing image) | 3 input |
| invalid `print.json` or command-line setting | 4 config |
| provider rule violated, at settings time or for the finished page count/gutter/page size | 5 constraint |
| PDF rendering failed | 6 render |
| output directory is not writable or already contains another build | 8 output |

## Rebuilds and safety

- A build **refuses to overwrite** an existing PrintForge output unless
  `--force` is given (`exit 8`, with a hint).
- `--force` only replaces a directory that consists exclusively of the five
  artifact names. If it contains anything else, PrintForge refuses and leaves
  it alone — unrelated files are never deleted.
- Every stage runs in a hidden staging directory next to the target. The target
  is replaced only after `metadata.json` and `build-report.json` are written, so
  a failed build leaves the previous successful output byte-for-byte intact and
  no partial files behind.
- Manuscript inputs are opened read-only; the build never writes into the book
  directory.

## `printforge inspect`

```sh
printforge inspect tests/fixtures/print-book [--config FILE] [print settings flags]
```

Prints a JSON report to stdout and renders nothing: book summary, chapter list
(id, title, kind, source, number, part, heading/block counts), document counts
(chapters, headings, images), resolved settings with provenance, provider
sources, and diagnostics. It exits `7` when any diagnostic is an ERROR, so it
works as an input check in scripts.

## `printforge discover`

```sh
printforge discover /path/to/BookForge
```

Finds `src/content/books/**/book.json` (or searches the directory itself) and
prints each book directory relative to the root, one per line. `bookforge`
does not need to be installed: the convention is just files on disk.

## Determinism

Two builds of the same manuscript, settings and fonts produce byte-identical
artifacts, even in different output directories: no absolute paths, timestamps
or environment details are written. PDFs are normalized (font timestamps and
the information dictionary), and JSON is serialized with a stable key order.

## Manual upload only

`metadata.json` and `cover-spec.json` describe what to enter in the provider's
dashboard; `interior.pdf` and `cover.pdf` are the files to upload there. There
is no Amazon API call, no credentials and no network access anywhere in the
build.
