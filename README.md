# PrintForge

![PrintForge](docs/img/printforge-logo.png)

**PrintForge** converts Markdown manuscripts into professionally formatted
print-on-demand books. A standalone, open-source CLI that takes the same
book structure BookForge uses and produces POD-ready output — interior PDF,
cover spec, and provider metadata — starting with **Amazon KDP**.

PrintForge only produces **local, manual-upload-ready files**. It never
uploads to or submits anything to Amazon, and it never modifies the source
manuscript.

## What it does

- **Import** manuscripts from the BookForge convention (`book.json` + `chapters/*.md`) without modifying the originals
- **Format** them for print: trim size, bleed, margins, typography, page geometry
- **Generate** title/copyright pages, a table of contents with real page numbers and a full-wrap cover
- **Publish** via pluggable provider profiles (KDP first), producing local upload-ready files

## Quick start (offline, no BookForge checkout needed)

Linux native prerequisites for WeasyPrint are listed in
[docs/INSTALL.md](docs/INSTALL.md) (Debian/Ubuntu:
`sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`).

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
printforge --help
printforge discover tests/fixtures/bookforge-root        # list books in a checkout
printforge inspect tests/fixtures/print-book             # JSON report, no rendering
printforge settings tests/fixtures/print-book --trim 6x9 # resolved print settings
printforge build tests/fixtures/print-book --output build/print-book
pytest && ruff check . && ruff format --check .
```

The build writes `interior.pdf`, `cover.pdf`, `cover-spec.json`, `metadata.json`
and `build-report.json`. A rebuild needs `--force`; a failed build leaves the
previous output untouched. See [docs/BUILD.md](docs/BUILD.md).

`tests/fixtures/minimal-book` is a small synthetic manuscript in BookForge layout:
it is below KDP's 24-page minimum, so use it for `settings`/`inspect`, and
`tests/fixtures/print-book` for a full build. Print settings live in an optional
`print.json` next to `book.json`; see [docs/PRINT_JSON.md](docs/PRINT_JSON.md) and
[examples/print.json](examples/print.json).

## Status

Early development — see the [v0.1 roadmap (#14)](https://github.com/meistro57/PrintForge/issues/14)
and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The full pipeline is wired:
interior PDF, generated front matter, a table of contents with real page numbers,
full-wrap cover, metadata and build report ([docs/BUILD.md](docs/BUILD.md),
[docs/RENDERING.md](docs/RENDERING.md), [docs/FRONT_MATTER.md](docs/FRONT_MATTER.md),
[docs/COVER.md](docs/COVER.md)). Preflight reporting and the end-to-end regression
suite are next (#11, #12).

## License

MIT
