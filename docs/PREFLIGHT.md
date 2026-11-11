# Preflight

Preflight proves that a finished build is internally consistent before anyone
uploads it. It inspects the files PrintForge actually wrote, not the plan that
produced them, so a corrupt PDF, a stale manifest or a cover rendered for a
different page count is caught instead of being advertised as ready.

Preflight never talks to a print provider and cannot guarantee acceptance.
"Ready" means the local artifacts match the provider's documented rules and
agree with each other. Always run the provider's own previewer and order a
physical proof before publishing.

## Running it

`printforge build` runs preflight automatically in the staging directory. ERROR
findings abort the build before anything is published, so a previous successful
build is left untouched. WARNING and INFO findings are logged and recorded in
the build report.

`printforge check` re-runs the same checks on an existing output directory:

```sh
printforge check build/print-book
```

It writes `preflight.json` (machine-readable) and `preflight.md` (human-readable)
next to the artifacts and exits `7` when any ERROR-level finding is present.
`printforge build` also writes both files, so `check` is a second opinion (and a
useful audit step before upload), not a mandatory extra pass.

## What is checked

| Check | Rule ID | Severity |
|---|---|---|
| Every agreed artifact exists and is readable | `PREFLIGHT-FILE-MISSING`, `PREFLIGHT-FILE-UNREADABLE` | ERROR |
| JSON artifacts parse and contain objects | `PREFLIGHT-FILE-INVALID` | ERROR |
| PDFs start with a PDF header and parse | `PREFLIGHT-PDF-INVALID` | ERROR |
| PDFs are not encrypted | `PREFLIGHT-PDF-ENCRYPTED` | ERROR |
| Interior pages are single pages at the provider's trim/bleed size | `PREFLIGHT-INTERIOR-SPREAD`, `PREFLIGHT-INTERIOR-PAGE-SIZE` | ERROR |
| Finished page count is inside the provider range | `PREFLIGHT-PAGES-RANGE` | ERROR |
| Odd page count (the provider pads the book) | `PREFLIGHT-PAGES-ODD` | INFO |
| Cover PDF is one full-wrap page at the computed size | `PREFLIGHT-COVER-PAGES`, `PREFLIGHT-COVER-PAGE-SIZE` | ERROR |
| Cover spec trim, bleed, folds and full-cover size match | `PREFLIGHT-COVER-SPEC` | ERROR |
| Spine width and page count follow the provider formula | `PREFLIGHT-COVER-SPINE` | ERROR |
| Manifest names, print details and artifact hashes match the files | `PREFLIGHT-MANIFEST-FILES`, `PREFLIGHT-MANIFEST-PRINT`, `PREFLIGHT-MANIFEST-HASH` | ERROR |
| Manifest records provider and resolved settings | `PREFLIGHT-MANIFEST-PROVIDER`, `PREFLIGHT-MANIFEST-SETTINGS` | ERROR |
| Every font referenced by a PDF is embedded | `PREFLIGHT-FONT-NOT-EMBEDDED` | ERROR |
| Interior actually uses text fonts | `PREFLIGHT-FONT-NONE` | WARNING |
| Printed raster images meet the provider's DPI minimum, with source path and printed size | `PREFLIGHT-IMAGE-DPI` | WARNING |
| Source hashes are recorded | `PREFLIGHT-SOURCE-MISSING` | INFO |
| Overflow, clipping and spine-text clearance need a human eye | `PREFLIGHT-MANUAL-INSPECTION` | INFO |
| The provider's previewer and a physical proof are still required | `PREFLIGHT-PROVIDER-PREVIEW` | INFO |

Image placement is measured from the PDF content stream (`q`/`Q`/`cm`/`Do`), not
from the resource dictionary: WeasyPrint lists every image on every page, but
only paints it where the document places it. Builds with the parsed manuscript
available resolve the source file and chapter, for example
`interior.pdf page 19 (...), chapters/ch-2.md (images/diagram.png)`; `check`
reports the PDF page and resource name when the source is not available.

## `preflight.json`

```json
{
  "schema_version": 1,
  "tool": {"name": "printforge", "version": "0.1.0.dev6"},
  "book": "print-book",
  "provider": {
    "name": "kdp",
    "display_name": "Amazon KDP paperback",
    "sources": [{"title": "...", "url": "...", "checked": "2026-10-26"}]
  },
  "print": {"format": "paperback", "trim": {"width": "6in", "height": "9in"},
            "page_count": 49, "spine": "0.110348in", "cover": {...}},
  "settings": {"provider": "kdp", "trim": {...}, "...": "..."},
  "source": {"book_json": {"file": "book.json", "sha256": "..."},
             "chapters": [{"file": "chapters/ch-1.md", "sha256": "..."}]},
  "artifacts": {
    "interior.pdf": {"bytes": 122043, "sha256": "...", "pages": 49,
                     "page_size": {"width": "6in", "height": "9in"},
                     "encrypted": false},
    "cover.pdf": {"bytes": 10502, "sha256": "...", "pages": 1, "page_size": {...}},
    "cover-spec.json": {"bytes": 2079, "sha256": "..."},
    "metadata.json": {"bytes": 5123, "sha256": "..."}
  },
  "checks": [{"severity": "INFO", "rule_id": "PREFLIGHT-PAGES-ODD",
              "message": "...", "context": "interior.pdf", "suggestion": "..."}],
  "summary": {"errors": 0, "warnings": 0, "infos": 3,
              "ready": true, "requires_human_inspection": true},
  "notes": ["...", "..."]
}
```

The payload is deterministic: no timestamps, absolute paths or environment
details. The source hashes are recorded at build time in `metadata.json` and
copied into the report, so `check` can still show provenance for an output
directory whose manuscript is not available.

## `preflight.md`

A short human-readable rendering of the same payload: status, provider and
print summary, page/cover measurements, a findings table with suggested fixes,
the manual-inspection and preview reminders, and the recorded tool version,
provider source URLs and output hashes.
