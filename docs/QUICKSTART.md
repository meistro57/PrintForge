# Quick start

A fresh clone can build a print-ready KDP paperback offline, with no private
dataset and no network access at build time. This page is the short version; the
stage contracts are in [BUILD.md](BUILD.md) and [PREFLIGHT.md](PREFLIGHT.md).

## 1. Install

Linux native libraries are required by WeasyPrint:

```sh
sudo apt-get update
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
```

Other distributions, WSL and missing-library errors are covered in
[INSTALL.md](INSTALL.md) and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

```sh
git clone https://github.com/meistro57/PrintForge.git
cd PrintForge
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
printforge --help
```

## 2. Build the checked-in fixture

```sh
printforge inspect tests/fixtures/print-book      # JSON report, no rendering
printforge build tests/fixtures/print-book --output build/print-book
printforge check build/print-book
```

`build` writes:

```
build/print-book/
  interior.pdf
  cover.pdf
  cover-spec.json
  metadata.json
  build-report.json
  preflight.json
  preflight.md
```

`check` re-runs preflight against the written files and exits `7` if any
ERROR-level finding is present. A successful build is already preflighted; the
separate command is for an audit later (or on another machine).

## 3. Read the result

- `metadata.json` is what to type into the provider's dashboard. Fields that
  were not supplied stay `null`.
- `preflight.md` is the human-readable audit: findings, fixes, provider sources
  and output hashes.
- `preflight.json` is the same record for scripts.
- `cover-spec.json` describes the full-wrap cover geometry: trim, bleed, spine,
  folds, safe areas and barcode reserve.

## 4. Use your own manuscript

A book directory needs `book.json` and `chapters/*.md`, the same convention
BookForge uses (see [BOOKFORGE_IMPORT.md](BOOKFORGE_IMPORT.md)). Put optional
print settings in a `print.json` next to `book.json`; every setting is listed in
[PRINT_JSON.md](PRINT_JSON.md).

```sh
printforge discover /path/to/BookForge
printforge build /path/to/BookForge/src/content/books/my-book --output build/my-book
```

`tests/fixtures/minimal-book` is a tiny manuscript for `settings`/`inspect`; it
is below KDP's 24-page minimum, so it cannot build. Use a real manuscript (or the
`print-book` fixture) for a full build.

## 5. Before uploading

PrintForge does not upload anything. Follow [KDP_WORKFLOW.md](KDP_WORKFLOW.md):
run Amazon's Print Previewer, inspect every page and the spine, and order a
physical proof before publishing.

## Determinism

Two builds of the same manuscript, settings and fonts produce byte-identical
artifacts. Generated PDFs are never committed to the repository; CI rebuilds
them from the checked-in fixture.
