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
- **Publish** via pluggable provider profiles (KDP first)

## Quick start (offline, no BookForge checkout needed)

Linux native prerequisites for WeasyPrint are listed in
[docs/INSTALL.md](docs/INSTALL.md) (Debian/Ubuntu:
`sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core`).

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
printforge --help
printforge settings tests/fixtures/minimal-book --trim 6x9   # resolved print settings (JSON)
printforge build tests/fixtures/minimal-book --provider kdp
pytest && ruff check .
```

`tests/fixtures/minimal-book` is a small synthetic manuscript in BookForge layout.
Print settings live in an optional `print.json` next to `book.json`; see
[docs/PRINT_JSON.md](docs/PRINT_JSON.md) and [examples/print.json](examples/print.json).

## Status

Early development — see the [v0.1 roadmap (#14)](https://github.com/meistro57/PrintForge/issues/14)
and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The `build` command is currently a
placeholder that exits with code 9 and writes nothing.

## License

MIT
