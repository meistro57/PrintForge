# Amazon KDP paperback profile (`--provider kdp`)

Implementation: [`printforge/providers/kdp.py`](../../printforge/providers/kdp.py).
Every number comes from Amazon's official KDP help pages, **last checked 2026-10-26**.
KDP changes these rules from time to time. Re-verify them before a production run, and
when you change a value, update `CHECKED` in the module.

| Source | URL |
|---|---|
| Paperback trim size, bleed, margins, page counts | https://kdp.amazon.com/en_US/help/topic/G201857950 |
| Create a Paperback Cover (bleed, spine, safe zones) | https://kdp.amazon.com/en_US/help/topic/G201953020 |
| Barcode reserve (2 x 1.2 in white box, lower right of back cover) | https://kdp.amazon.com/help/topic/GGE5T76TWKA85DJM |

## Implemented scope

- **Supported:** paperback, **6 x 9 in** trim, **black** ink, **white or cream** paper,
  **no interior bleed**.
- **Rejected:** everything else, with an `ERROR` and a suggested fix.
  - Other trims: `KDP-TRIM-UNSUPPORTED`
  - Colour inks: `KDP-INK-UNSUPPORTED`
  - Groundwood paper: `KDP-PAPER-UNSUPPORTED`
  - Interior bleed: `KDP-BLEED-UNSUPPORTED`
  - Ink/paper combinations KDP doesn't offer: `KDP-PAPER-INVALID`

  The bleed geometry and the colour/groundwood tables are still encoded, so the rules
  are complete and tested before the renderer supports those modes.

## Interior rules (G201857950)

| Rule | Value |
|---|---|
| Page count, 6x9, black ink + white paper | 24 – 828 |
| Page count, 6x9, black ink + cream paper | 24 – 776 |
| Page count, 6x9, black ink + groundwood | 24 – 812 (not yet supported) |
| Page count, 6x9, standard colour + white | 72 – 600 (not yet supported) |
| Page count, 6x9, premium colour + white | 24 – 828 (not yet supported) |
| Inside (gutter) margin, 24–150 pages | 0.375 in |
| 151–300 pages | 0.5 in |
| 301–500 pages | 0.625 in |
| 501–700 pages | 0.75 in |
| 701–828 pages | 0.875 in |
| Outside margins (top, bottom, outer edge), no bleed | ≥ 0.25 in |
| Outside margins, with bleed | ≥ 0.375 in |
| Interior bleed (optional) | 0.125 in on top, bottom, outer edge → 6x9 page becomes 6.125 x 9.25 in |
| Image resolution | ≥ 300 DPI (600 DPI recommended max) |

Page-count-dependent rules (gutter, page limits, spine) are always evaluated against
the **final rendered PDF page count** (`validate_finished_book`), never an estimate.

## Cover rules (G201953020)

| Rule | Value |
|---|---|
| Cover bleed (**mandatory**, separate from interior bleed) | 0.125 in on top, bottom and outside edges |
| Full cover width | bleed + back trim + spine + front trim + bleed |
| Full cover height | bleed + trim height + bleed |
| Spine per page, black ink + white paper | 0.002252 in |
| Spine per page, black ink + cream paper | 0.0025 in |
| Spine per page, premium colour | 0.002347 in |
| Spine per page, standard colour | 0.002252 in |
| Spine text | only for books with ≥ 80 pages (see note) |
| Spine text clearance | ≥ 0.0625 in from each spine edge |
| Front/back text safe margin | ≥ 0.125 in inside the trim |
| Barcode reserve | 2 in x 1.2 in, lower right of the back cover |
| Cover image resolution | ≥ 300 DPI |

**Note on the spine-text threshold.** G201857950 says spine text is printed only on books
with "more than 79 pages". G201953020 says "at least 79 pages". PrintForge uses the
stricter reading (**≥ 80 pages**), which satisfies both.

**PrintForge policies (not KDP rules):**
- The barcode reserve is placed 0.25 in from the back-cover bottom trim and from the
  spine fold. KDP doesn't give a paperback distance; its hardcover page asks for 0.25 in
  from the spine hinge.
- Finished page sizes are compared with a 0.5 pt tolerance, to allow for PDF
  point rounding.

## Not claimed

PrintForge produces **local files for manual upload**. It does not talk to KDP, and
passing these checks does not mean KDP will accept the files. Always review the files in
KDP's Print Previewer and order a physical proof before publishing.
