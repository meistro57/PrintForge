# KDP paperback workflow

PrintForge produces local files for manual upload. It never contacts Amazon,
never stores credentials and never submits anything. "Ready" means the files
agree with KDP's documented rules; it does not mean KDP accepted them.

## 1. Build and preflight

```sh
printforge build path/to/book --output build/my-book
printforge check build/my-book
```

A build runs preflight automatically. ERROR findings abort before publishing;
WARNING and INFO findings stay in `build-report.json`, `preflight.json` and
`preflight.md`. `check` re-runs the same checks on the written files and exits
`7` on any ERROR.

## 2. Upload the files

| KDP field | File/value |
|---|---|
| Interior manuscript | `interior.pdf` |
| Book cover | `cover.pdf` (one full-wrap page: back, spine, front) |
| Trim size | `print.trim` in `metadata.json` |
| Ink and paper | `print.ink`, `print.paper` |
| Cover finish | `print.finish` |
| Page count | `print.page_count` |
| Title, subtitle, author, description, language | `metadata.*` when supplied |
| ISBN and publisher | `metadata.isbn`, `metadata.publisher` when supplied |
| Publication/copyright year and holder | `metadata.copyright_year`, `metadata.copyright_holder` when supplied |

PrintForge never invents an ISBN, barcode, copyright year, publisher or legal
boilerplate. If a field is `null`, leave it blank or enter your own value in the
KDP dashboard.

The barcode area on the back cover is reserved and intentionally not drawn. KDP
places its own barcode there.

## 3. Amazon Print Previewer checklist

Run the previewer before approving the book and check:

- [ ] Trim size and page count match `metadata.json`.
- [ ] No page is a two-page spread; each PDF page is one printed page.
- [ ] No text is clipped at the top, bottom, inside or outside edges.
- [ ] Running heads and folios are present on the expected pages and absent on
      display pages.
- [ ] Front matter uses roman folios; the first chapter restarts at `1`.
- [ ] Every image looks sharp at its printed size.
- [ ] The cover has no text or important artwork inside the barcode reserve or
      too close to the trim/fold lines.
- [ ] Spine text, if present, is centred between the folds and readable.
- [ ] The last page and any blank pages look intentional.

Items that need a human eye are listed in `preflight.md` under
`PREFLIGHT-MANUAL-INSPECTION`; PDF structure alone cannot prove them.

## 4. Physical proof

Order a physical proof before publishing. Check paper colour, ink darkness,
margin comfort, cover colour, spine alignment and how the book opens. Screens
and PDF viewers cannot show these reliably.

## Known limitations

- Only Amazon KDP paperback, 6 x 9 in, black ink, white or cream paper is
  implemented. Interior bleed, colour interiors and hardcover are rejected with
  a clear constraint error.
- The PDF is RGB; PrintForge does not convert to CMYK or colour-manage.
- Cover artwork is supplied by you (`cover.wrap_image`, or front/back images,
  or a typographic cover). No guided cover template PDF is produced.
- Artwork content is not inspected: PrintForge checks DPI and aspect, not
  whether baked-in text crosses a safe area.
- Raw HTML and remote images are not supported; see
  [BOOKFORGE_IMPORT.md](BOOKFORGE_IMPORT.md).
- A single volume cannot exceed KDP's page limit (828 pages for 6 x 9 black ink
  on white paper). Split large works into volumes.
- Widow/orphan handling and heading keep-with-next are best effort; WeasyPrint
  cannot always report when a rule had to be relaxed, so inspect the pages.

## Troubleshooting

Native-library, font, permission and preflight failures are covered in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).
