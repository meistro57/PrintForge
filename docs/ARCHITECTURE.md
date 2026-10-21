# PrintForge — Architecture

A standalone, open-source application that converts Markdown manuscripts into
professionally formatted print-on-demand (POD) books. Separate from BookForge.

## Purpose

BookForge is the *reader/press* (web shelf, themes, audiobook lane). PrintForge is
the *print engine*: it takes a Markdown manuscript and produces POD-ready output
(interior PDF, cover spec, provider submission metadata) for Amazon KDP first,
with more providers to follow.

## Source of truth (shared convention, not shared code)

PrintForge **imports from BookForge without modifying originals**. It reads the
same on-disk convention BookForge already uses:

    src/content/books/<slug>/book.json      # book metadata (discovery anchor)
    src/content/books/<slug>/chapters/*.md  # chapter markdown (front matter + body)

BookForge discovers books by globbing **/book.json and **/chapters/*.md (see its
src/content.config.ts). PrintForge mirrors that discovery but adds its own
print-specific schema as a sibling file, never editing BookForge's files.

## Import mapping (BookForge -> PrintForge)

BookForge book.json fields imported:
  slug, title, author, subtitle, description, cover, order

Chapter markdown front matter imported:
  title, chapterNumber, partNumber, partTitle, order, isFrontMatter, slug

Ignored (web-reader-only, no print meaning):
  theme, audiobook

Print-specific concerns live in a separate print.json (or provider profile) so
BookForge stays untouched:
  trim size, bleed, margins, ISBN, paper color, spine width, fonts, TOC depth

## Directory layout (proposed)

    PrintForge/
      cli/                    # entrypoint: python -m printforge ...
      printforge/
        book.py               # Book model: load book.json + ordered chapters
        chapter.py            # front-matter parsing + body
        importer/             # reads BookForge source (import-only, never mutates)
        layout/               # pagination, typography, page geometry
        render/               # markdown -> interior pages
        publisher/            # publishing engine (interior pdf, cover spec, manifest)
        providers/            # provider profiles: kdp.py (first), bookvault.py (later)
      docs/ARCHITECTURE.md    # this file
      tests/

## Modules

1. **CLI** — printforge build <book_dir> --provider kdp (and --provider bookvault).
   Discovers books by the same glob convention as BookForge.

2. **Publishing engine** (publisher/) — orchestrates: load book, resolve print
   profile, paginate, typeset, render interior, render cover, emit provider
   manifest. Provider-agnostic core.

3. **Provider profiles** (providers/) — pluggable. Each provider contributes its
   trim/bleed/margin constraints, cover template, and metadata schema. Start with
   Amazon KDP (kdp.py); Bookvault, IngramSpark, Lulu as later providers.

## Data flow

    BookForge source (read-only)
         |
         v
    importer (extract book.json + chapters)
         |
         v
    Book model (slug, title, author, ordered/grouped chapters)
         |
         v
    provider profile (trim, bleed, margins, fonts)
         |
         v
    layout + render (interior PDF, page geometry, typesetting)
         |
         v
    publisher manifest (KDP-compatible: interior.pdf, cover.pdf, metadata.json)

## Design principles

- **Import-only from BookForge.** Never modify originals; keep both repos independent.
- **Modular.** CLI / engine / providers are separate concerns behind small interfaces.
- **Provider-first.** Each POD vendor's constraints are a profile, not scattered logic.
- **Deterministic.** Same manuscript + same profile -> same output.

## Status

- [x] Repo created (README, MIT, .gitignore)
- [x] Architecture documented
- [ ] Importer (read BookForge convention)
- [ ] Layout/typography engine
- [ ] KDP publisher profile
- [ ] Interior PDF + cover spec output

