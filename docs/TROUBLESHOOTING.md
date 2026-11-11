# Troubleshooting

## Native PDF libraries

Symptom: `OSError: cannot load library 'pango-1.0-0'` or a WeasyPrint import
failure.

WeasyPrint needs Pango, HarfBuzz and fonts in addition to its Python wheels:

```sh
# Debian / Ubuntu / WSL2 Ubuntu
sudo apt-get update
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core

# Fedora
sudo dnf install pango harfbuzz dejavu-serif-fonts dejavu-sans-mono-fonts
```

`libharfbuzz-subset0` avoids WeasyPrint's fontTools fallback and its
`DeprecationWarning`. WeasyPrint does not need a display server: headless Linux
and CI work once the libraries are installed.

## Fonts are missing or substituted

PrintForge embeds the fonts named by `print.json` (`typography.body_font`,
`heading_font`, `mono_font`) and fails the build if a required family cannot be
embedded. Install `fonts-dejavu-core` (the default presets), or choose a family
that is installed, then rebuild.

## Build refuses to write

- `output directory already contains a PrintForge build` — pass `--force` to
  replace a previous build.
- `output directory contains files PrintForge did not write` — PrintForge never
  deletes unrelated files. Choose an empty/new directory or remove the extra
  files yourself.
- `output path is not a directory` / `cannot create the output directory` —
  check permissions and free space.

A failed build leaves the previous output byte-for-byte intact.

## `printforge check` exits 7

Open `preflight.md`. Each row has a rule ID, context and suggested fix. Common
cases:

| Rule | Meaning |
|---|---|
| `PREFLIGHT-FILE-MISSING` | An artifact was deleted or moved; rebuild. |
| `PREFLIGHT-PDF-INVALID` | The PDF is truncated or not a PDF; rebuild. |
| `PREFLIGHT-PDF-ENCRYPTED` | Remove PDF encryption/password protection. |
| `PREFLIGHT-INTERIOR-SPREAD` | The interior was rendered as two-page spreads; rebuild one page per PDF page. |
| `PREFLIGHT-INTERIOR-PAGE-SIZE` | Page size does not match the resolved trim/bleed. |
| `PREFLIGHT-PAGES-RANGE` | The finished page count is outside the provider limit. |
| `PREFLIGHT-COVER-SPEC` / `PREFLIGHT-COVER-SPINE` | The cover and the interior page count disagree; rebuild the cover. |
| `PREFLIGHT-MANIFEST-HASH` / `PREFLIGHT-MANIFEST-PRINT` | `metadata.json` is stale or inconsistent with the files; rebuild. |
| `PREFLIGHT-FONT-NOT-EMBEDDED` | Install the font family or change `print.json`, then rebuild. |
| `PREFLIGHT-IMAGE-DPI` | Replace a low-resolution image or print it smaller. |

WARNING and INFO findings do not fail the build. They are still recorded, so do
not ignore them: `PREFLIGHT-MANUAL-INSPECTION` and `PREFLIGHT-PROVIDER-PREVIEW`
mean a human must inspect the PDFs and run Amazon's previewer.

## Manuscript import errors

- `book.json slug ... differs from directory name` — the directory must be named
  after the slug.
- `front matter is missing required 'title'/'order'` — add the field to the
  chapter's YAML front matter.
- `DOC-IMAGE-MISSING` / `DOC-IMAGE-UNSAFE` — images must be local files inside
  the book directory; remote URLs, `..` escapes and outside symlinks are
  rejected.
- `DOC-RAW-HTML` — raw HTML is printed literally by design. Use Markdown.
- `IMPORT-DUP-ORDER` — give chapters distinct `order` values; ties fall back to a
  natural filename sort.

## `inspect` exits 7

`inspect` returns exit `7` when an ERROR diagnostic would stop a build. Read the
`diagnostics` array in its JSON output; nothing was rendered or written.

## Where the files went

The default output is `printforge-output/<book-slug>` relative to the current
directory. `--output DIR` and `print.json` `output.directory` take precedence.
The build log on stderr ends with `wrote <path>`.
