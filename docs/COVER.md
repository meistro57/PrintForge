# Full-wrap cover

`printforge/cover/` produces the two files a paperback upload needs: one
full-wrap `cover.pdf` (back cover, spine and front cover left to right) and a
machine-readable `cover-spec.json` describing every zone on it.

```python
result = build_cover(
    job.settings,
    provider,
    interior.page_count,  # from RenderResult, never an estimate
    pdf_path=out / "cover.pdf",
    spec_path=out / "cover-spec.json",
    metadata=job.metadata,
    config_dir=job.config_dir,
)
result.spec  # the same data written to cover-spec.json
result.size  # measured page box
result.diagnostics
```

The caller passes the **finished interior page count**. The spine, the full
width and the page-count-dependent safe areas all follow from it.

## Geometry

All numbers come from the provider profile (`CoverRules`, `spine_width`,
`spine_text_allowed`); nothing vendor-specific is hardcoded here. For a trim of
`W x H`, bleed `b` and spine `s`:

```
full width  = 2b + 2W + s
full height = 2b + H
fold lines  = b + W            (back | spine)
              b + W + s        (spine | front)
```

For the KDP fixture (6 x 9 in, black ink on white paper, 49 pages):

| Value | Formula | Result |
|---|---|---|
| spine | 49 x 0.002252 in | `0.110348in` |
| full cover | 2x0.125 + 2x6 + 0.110348 | `12.360348in` x `9.25in` |
| folds | 0.125 + 6 and + spine | `6.125in`, `6.235348in` |
| barcode reserve | 2 x 1.2 in, 0.25 in from the back trim edges | `x=3.875in y=7.675in` |

Coordinates in the spec are inches from the **top-left corner of the full
cover** (the CSS origin). Safe areas are the trim areas inset by the provider's
text-safe margin; the spine text area is inset by the spine clearance on each
fold and by the text-safe margin top and bottom, clamped at zero (a thin spine
can have no usable area).

## `cover-spec.json`

```json
{
  "schema_version": 1,
  "provider": "kdp",
  "trim": {"width": "6in", "height": "9in"},
  "bleed": "0.125in",
  "spine": {"width": "0.110348in", "page_count": 49},
  "full_cover": {"width": "12.360348in", "height": "9.25in"},
  "fold_lines": ["6.125in", "6.235348in"],
  "areas": {"back": {...}, "spine": {...}, "front": {...}},
  "safe_areas": {"back": {...}, "front": {...}, "spine_text": {...}},
  "barcode_reserve": {...},
  "spine_text": {"allowed": false, "min_pages": 80, "clearance": "0.0625in",
                 "mode": "auto"},
  "interior": {"page_count": 49, "paper": "white", "ink": "black"},
  "cover": {"finish": "matte", "background_color": "#1F2A44",
            "text_color": "#FFFFFF"},
  "sources": [{"title": "...", "url": "https://kdp.amazon.com/...",
               "checked": "2026-10-26"}]
}
```

It is deterministic (no timestamps, no paths) and uses the same length
serialization as `print.json`. `sources` records where the provider rules came
from and when they were last verified.

There is no generated guide/template PDF; every guide coordinate is in the spec
so a designer tool can draw it. The production cover has no crop, fold or safe
area marks.

## Artwork

`cover.wrap_image` is a complete back+spine+front image scaled to *cover* the
page: the aspect ratio is preserved and the overflow is cropped, centered.
Separate `cover.front_image` and `cover.back_image` fill their own side of the
cover (including the outer, top and bottom bleed) and leave the spine as the
background color. Images are resolved relative to the configuration directory
and must stay inside it; remote or absolute paths are rejected.

Artwork suppresses the generated text it would sit under: a wrap image replaces
the whole cover design, a front image replaces the front typography, a back
image replaces the back text. `cover.finish` (`matte`/`glossy`) is recorded in
the spec only; the PDF is RGB and does not simulate a lamination.

Every raster image is checked at its printed size against the provider's
`min_image_dpi` (300 for KDP): low resolution is `COVER-IMAGE-DPI`, an aspect
mismatch that will be cropped is `COVER-IMAGE-ASPECT`. Missing, unsafe,
undecodable or unsupported-format artwork fails with a message naming the file
and the reference; no output is written.

## Typography fallback

With no artwork, the front cover prints the title and optional subtitle
(heading font, sized from the trim height), the author, and the publisher;
the back prints `cover.back_text`, else `metadata.description`, inside the top
65% of the back safe area so the barcode reserve stays clear.

Spine text follows `cover.spine_text`:

| Mode | Behaviour |
|---|---|
| `auto` (default) | print only when the provider allows spine text *and* it fits legibly |
| `never` | never print |
| `always` | fail if the provider disallows it or it cannot be set legibly |

Spine text needs at least `spine_text.min_pages` pages (80 for KDP). It is
rotated 90 degrees clockwise so it reads top to bottom, fitted to the spine
thickness, and omitted with `COVER-SPINE-TEXT-TIGHT` when it would be smaller
than 6pt. A wrap image owns the spine, so no generated spine text is added.

The barcode reserve is never drawn and nothing is printed inside it: PrintForge
does not fabricate an ISBN, a barcode or a barcode image.

## Determinism and failure

The cover goes through the same PDF normalization as the interior: embedded font
timestamps are rewritten, the information dictionary is written explicitly
(`/Title`, `/Author`, `/Producer`/`/Creator` = `PrintForge <version>`), and no
dates are emitted. Repeat builds of the same cover are byte-identical.

All checks run before anything is written. The PDF is written first, then the
spec; a failure after the PDF write can leave the PDF without a spec, but never
a cover built from a guessed page count.

## Limitations

- Finish (matte/glossy) and paper stock are declared, not simulated.
- The PDF is RGB; no CMYK conversion or colour-managed proofing.
- Artwork content is not inspected: the spec tells a designer where the barcode
  reserve and safe areas are, but baked-in text that overlaps them cannot be
  detected.
- No guide/template PDF is produced (see above).

## Testing

- `tests/test_cover.py` checks the geometry formulas (49 and 200 pages, white
  and cream paper), fold lines, safe areas, barcode placement, the spec payload,
  and that a non-positive page count is rejected.
- PDF tests inspect the single cover page with pypdf: computed page box, no
  crop/trim/bleed boxes beyond the media box, front/back text, spine text below
  and above the threshold, `always`/`never` modes, artwork suppression, DPI and
  aspect warnings, actionable artwork errors, byte-identical repeat builds, and
  an end-to-end check that the cover uses `build_interior_pdf`'s page count.
