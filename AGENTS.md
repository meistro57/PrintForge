# AGENTS.md

Guidance for agents working in PrintForge: a Python CLI that turns BookForge-style
Markdown manuscripts into print-on-demand book files (Amazon KDP paperback first).
It never uploads anything and never writes to the manuscript source.

## Commands

```sh
# setup (native libs are required for WeasyPrint; see docs/INSTALL.md)
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
# or, with uv (a local, untracked uv.lock exists)
uv sync --extra dev

# tests / lint (CI runs exactly these)
pytest
pytest -m "not pdf"                 # skip WeasyPrint-rendering tests
ruff check .
ruff format --check .               # formatting IS enforced, unlike most repos

# CLI
printforge --help
python -m printforge --version
printforge settings tests/fixtures/minimal-book --trim 6x9   # JSON to stdout
printforge inspect tests/fixtures/print-book                 # JSON, no rendering
printforge build tests/fixtures/print-book --output build/print-book
printforge build tests/fixtures/print-book --output build/print-book --force
printforge discover tests/fixtures/bookforge-root
```

- `pytest` needs the `pdf` native libs; `.venv` created without them fails
  `tests/test_stack.py` with `OSError: cannot load library 'pango-1.0-0'`.
- `ruff` is pinned exactly (`==0.17.2`), runtime deps use `~=` compatible pins.
- Regenerate the document golden snapshot after intended model changes:
  `PRINTFORGE_UPDATE_GOLDEN=1 pytest tests/test_document.py` (writes
  `tests/fixtures/markdown-book.document.json`).
- Optional real-checkout importer test:
  `PRINTFORGE_BOOKFORGE_ROOT=/path/to/BookForge pytest tests/test_bookforge_checkout.py`
  (skipped in CI when unset).

## Change workflow

Every change lands as a complete unit, not a partial patch:

1. Run `pytest` plus `ruff check .` and `ruff format --check .`; fix what fails.
2. Update the docs the change affects: `docs/*.md`, module docstrings, this file,
   `README.md`, `examples/print.json` when a setting changes.
3. Bump the version in **both** `pyproject.toml` (`[project] version`) and
   `printforge/__init__.py` (`__version__`); keep them identical. While v0.1 is in
   development use `0.1.0.devN` and increment `N`.
4. Commit with the repository's sentence-style message (issue number in parentheses
   when one applies) and push to the remote of the current branch.

There is no separate changelog file; the commit history plus the docs are the record.

## Architecture and data flow

```
book dir (read-only source)
  importer/  -> Book, Chapter (frozen models, book.json + chapters/*.md + YAML front matter)
  document/  -> Document of DocChapter/Block/Inline (content only; no geometry)
  config/    -> ResolvedPrintJob (layered print settings + provenance)
  providers/ -> ProviderProfile: vendor rules (trim, gutters, page counts, spine, cover)
  layout/    -> LayoutPlan + CSS Paged Media stylesheet
  render/    -> front matter, contents, interior PDF + page/heading map, fonts
  cover/     -> cover geometry, cover-spec.json, full-wrap cover PDF
  publish/   -> one-command build: artifacts, metadata.json, build-report.json
  (preflight, #11, not written yet) -> preflight report
```

| Package | Responsibility |
|---|---|
| `printforge/interfaces.py` | Stage protocols (`BookImporter`, `Renderer`) + provider re-export |
| `printforge/book.py` | `Book`, `Chapter`, `Part` models; `Book.parts()` grouping |
| `printforge/importer/` | BookForge convention reader, front matter split, safe asset paths |
| `printforge/document/` | markdown-it-py parse to immutable semantic tree; `to_data()` |
| `printforge/config/` | `print.json` schema, defaults, layered merge, validation |
| `printforge/providers/` | Registry + `base.py` contract + `kdp.py` rules |
| `printforge/layout/` | Page geometry, section policies, gutter convergence, CSS |
| `printforge/render/` | HTML contract, front matter/contents, WeasyPrint adapter, PDF facts |
| `printforge/cover/` | Full-wrap cover geometry, `cover-spec.json`, `cover.pdf` |
| `printforge/publish/` | Staged end-to-end build, artifact commit, manifest and report |
| `printforge/fsutil.py` | Atomic file writes (temp file + `os.replace`, creates parents) |
| `printforge/units.py` | `Length`: exact rational inches, unit-required parsing |
| `printforge/errors.py` | Exception hierarchy mapped to stable exit codes |
| `printforge/diagnostics.py` | Non-fatal `Diagnostic` findings with stable rule IDs |

Cross-cutting contract: `docs/ARCHITECTURE.md` is the overview; `docs/BUILD.md`,
`docs/RENDERING.md`, `docs/FRONT_MATTER.md` and `docs/COVER.md` are the stage
contracts. Trust the package tree above when they disagree.

## Conventions you must follow

**Errors and exit codes.** Expected failures raise a `PrintForgeError` subclass; the
CLI maps each to a fixed exit code (0-9, documented in the `--help` epilog and
`printforge/errors.py`). Never raise bare exceptions for user-facing problems, never
reuse a code for a new meaning, and add a new subclass when a category is missing.
Include `hint=` for anything a user can fix.

**Diagnostics, not silent drops.** Non-fatal problems are recorded in `Diagnostics`
with a `PREFIX-UPPER-HYPHEN` `rule_id` and a severity. Existing prefixes: `IMPORT-`,
`DOC-`, `KDP-`, `RENDER-`. Tests assert specific IDs, so reuse rather than rename.
Every stage takes/produces diagnostics instead of logging and continuing silently.

**Immutability and determinism.** Models are `@dataclass(frozen=True, slots=True)`
with tuples, not lists. The same input must produce equal output objects. Serialized
jobs/manifests must contain no absolute paths and no environment-specific values
(`ResolvedPrintJob.to_dict()` drops `output`, identifies `print.json` by name +
SHA-256). Do not add ordering or hashing that depends on `set` iteration or filesystem
order. The renderer extends this to PDF bytes: see the determinism notes below.

**Read-only source.** Never write into the manuscript, create `print.json`, or modify
`book.json`. Asset references that are remote, absolute, escaping the book root, or
symlinks pointing outside are rejected (`importer/paths.py`) — keep that policy.

**Units.** All physical lengths are `Length` (exact `Fraction` inches). Construct with
`Length.parse("0.125in")`, `Length.inches(...)`, `Length.mm(...)`, `Length.pt(...)`.
Bare numbers are rejected by design; serialization happens only at the edge via
`to_str()` (normalized decimals) or `css()` (inches, 4 dp). Never reintroduce floats
for geometry.

**Metadata honesty.** The title and copyright pages print only fields supplied by
`book.json` or `print.json`. Never add placeholder ISBNs, copyright years, holders,
publisher names or legal boilerplate; omitted metadata stays omitted.

**Provider isolation.** Core packages (`importer`, `document`) must not import
`printforge.providers`; `config` may only import the registry. A static AST test
enforces this (`tests/test_kdp.py::test_provider_code_does_not_leak_into_core`).
Receive a `ProviderProfile` as an argument instead of calling `get_provider()` deep in
the stack. Every provider rule cites its vendor source with a checked date.

**Settings layering.** Precedence is platform defaults < provider defaults <
`print.json` < explicit CLI flags, merged key by key in `config/resolve.py`. The
platform layer must stay complete: the validator reports
`missing (internal defaults incomplete)` if a new key has no default. Adding a setting
means touching `config/defaults.py`, `config/settings.py` (schema + dataclass), the CLI
flag if applicable, `docs/PRINT_JSON.md`, and `examples/print.json`.

**Logging.** Human output goes to stderr via `get_logger()` (`printforge.*` namespace);
stdout is reserved for machine-readable output. Modules must not use `print()` or a
root logger.

**Lazy heavy imports.** `printforge/render/__init__.py` deliberately does not import
`weasy` (and therefore WeasyPrint); the builder imports `WeasyPrintRenderer` on the
first real build, and `pypdf`/`fontTools`/`Pillow` are imported inside functions.
Keep `printforge.render` importable without the native rendering stack; the full
test suite needs it, minimal environments do not.

**Renderer determinism and asset isolation.** `render/pdf.py` rewrites embedded font
programs with a fixed `head.modified` because WeasyPrint records the wall clock
there; that is what makes repeat builds byte-identical. Never remove that
normalization, add a timestamp to the PDF info dictionary, or write the output
before the render succeeds (the write must stay atomic). `render/weasy.py` only
loads files listed in the asset set returned by `build_html`; keep every image
`file:` URI produced from a resolved `Image.path` so the allow-list stays exact.
Rendered ERROR diagnostics from the document stage must abort the build before any
file is created.

**CI style.** `ruff check .` selects `E,F,W,I,B,UP,SIM,RUF` at line length 100,
target py311. Typographic punctuation rules `RUF001-RUF003` are ignored on purpose:
straight vs curly quotes are legitimate book content. `ruff format` is separate from
`ruff check`, so run both.

## Current implementation state (important)

Every stage is implemented and wired: `printforge build` imports, resolves, renders
the interior with front matter and contents, checks the provider's finished-book
rules, renders the cover, writes `metadata.json` + `build-report.json`, and swaps the
result into place. `inspect` reports input/settings/diagnostics without rendering and
exits 7 on ERROR diagnostics; `discover` lists books under a BookForge checkout.

Pipeline slices: #1 bootstrap, #2 importer, #3 settings, #4 document model, #5 KDP
profile, #6 layout, #7 interior renderer, #8 front matter + TOC, #9 cover, #10 build
CLI, #11 preflight, #12 regression suite. Remaining work is #11/#12. Match that
structure: new capability = new module + tests + docs, not edits that blur stage
boundaries.

Build one book from Python (same engine as the CLI):

```python
result = build_book(book_dir, output_dir=Path("build/my-book"), force=False)
result.interior.page_count, result.cover.spec["spine"]["width"], result.report
```

`build_book` is the only place that assembles artifacts: it stages in a hidden
directory, validates provider constraints for the finished book, and publishes with
an atomic directory swap. Do not re-implement that flow in the CLI or in tests;
`build_interior_pdf` (interior) and `build_cover` (cover) are the lower-level
primitives.

Build output rules: never overwrite a previous build without `force`, never delete
files PrintForge did not write, and never write into the manuscript. A failing build
must leave the previous output byte-for-byte intact.

## Testing

- Tests are per-stage: `test_importer`, `test_settings`, `test_document`, `test_kdp`,
  `test_layout`, `test_units`, `test_render_html`, `test_frontmatter`,
  `test_interior`, `test_cover`, `test_publish`, `test_cli`, plus contract tests in
  `test_conventions.py`.
- Fixtures in `tests/fixtures/`: `minimal-book` (quick start), `markdown-book` (parser
  coverage + golden snapshot), `bookforge-root` (multi-book checkout layout),
  `print-book` (generated 45-page manuscript plus `print.json` metadata and cover
  artwork for real PDF renders). Tests that mutate a book copy it to `tmp_path`
  first (`shutil.copytree`).
- `conftest.py` exposes `fixtures_dir`, `minimal_book`, `print_book` and
  `bookforge_root`; tests frequently build settings with
  `resolve_print_job(load_book(path), cli_overrides={...}).settings`. Use
  `print_book` for anything that renders; `minimal-book` is below KDP's 24-page
  minimum.
- Test rule IDs and exact user-facing messages rather than tracebacks; assert exit
  codes by enum (`ExitCode.CONSTRAINT`, `ExitCode.OUTPUT`, ...), not integers.
- The `pdf` marker is registered in `pyproject.toml`; use it for anything that renders
  a real PDF. There is no coverage threshold or typechecker in CI.

## Reference docs

- `docs/PRINT_JSON.md` — every setting, allowed values, precedence, units.
- `docs/LAYOUT.md` — recto/verso margins, gutter convergence, named page runs, the
  HTML contract renderers must emit.
- `docs/DOCUMENT_MODEL.md` — Markdown-to-model mapping, HTML/image/link safety policy.
- `docs/providers/KDP.md` — KDP numbers and their official sources.
- `docs/INSTALL.md` — native prerequisites per distro.
