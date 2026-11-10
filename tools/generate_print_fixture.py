"""Regenerate tests/fixtures/print-book (synthetic, public-domain-safe manuscript).

The text is produced from a fixed vocabulary with a seeded PRNG, so the fixture is
reproducible and contains no copyrighted material:

    python tools/generate_print_fixture.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "print-book"
WORDS = (
    "the a an of to in and for with on by from as at into over under between through "
    "press paper ink margin page folio gutter spine chapter part volume edition proof "
    "reader writer printer binding signature leaf quire type letter line column measure "
    "careful quiet steady patient simple honest plain clear exact modest durable "
    "makes keeps holds carries turns follows shapes guides measures builds checks sets "
    "history workshop craft method habit question answer reason detail pattern rhythm"
).split()


def sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(8, 22))]
    text = " ".join(words)
    return text[0].upper() + text[1:] + rng.choice([".", ".", ".", "?", ";"]).replace(";", ".")


def paragraph(rng: random.Random) -> str:
    return " ".join(sentence(rng) for _ in range(rng.randint(3, 7)))


def chapter_body(rng: random.Random, sections: int, extra: str = "") -> str:
    out = []
    for s in range(sections):
        out.append(f"## Section {s + 1}\n")
        out.extend(paragraph(rng) + "\n" for _ in range(rng.randint(5, 8)))
    return "\n".join(out) + extra


def front(title, order, slug, extra=""):
    return f'---\ntitle: "{title}"\norder: {order}\nisFrontMatter: true\nslug: "{slug}"\n{extra}---\n\n'


def main_fm(title, order, slug, number=None, part=None, part_title=None):
    lines = [f'title: "{title}"', f"order: {order}", f'slug: "{slug}"']
    if number is not None:
        lines.append(f"chapterNumber: {number}")
    if part is not None:
        lines += [f"partNumber: {part}", f'partTitle: "{part_title}"']
    return "---\n" + "\n".join(lines) + "\n---\n\n"


def main() -> None:
    rng = random.Random(20261026)
    chapters = ROOT / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    (ROOT / "images").mkdir(exist_ok=True)
    book = {
        "slug": "print-book",
        "title": "The Printer's Field Guide",
        "author": "PrintForge Fixtures",
        "subtitle": "A Synthetic Manuscript for Print Testing",
        "description": "A generated, copyright-free manuscript used to test PrintForge builds.",
        "order": 1,
        "theme": {"mood": "ignored for print"},
    }
    (ROOT / "book.json").write_text(json.dumps(book, indent=2) + "\n", encoding="utf-8")
    files = {
        "foreword.md": front("Foreword", 1, "foreword") + paragraph(rng) + "\n\n" + paragraph(rng) + "\n",
    }
    parts = {1: "PART I: THE PAGE", 2: "PART II: THE BOOK"}
    order = 2
    for n in range(1, 7):
        part = 1 if n <= 3 else 2
        extra = ""
        if n == 2:
            extra = (
                "\n## Figures and Tables\n\n![A diagram of a page spread](../images/spread.png)\n\n"
                "| Element | Purpose | Typical size |\n|:--|:--|--:|\n"
                "| Gutter | binding allowance | 0.5 in |\n| Folio | page number | 9 pt |\n"
                "| Running head | orientation | 8 pt |\n\n"
                "```text\npage = trim + bleed\nspine = pages x thickness\n```\n\n"
                "> A quotation, set apart from the text, with *emphasis*.\n\n"
                "- one list item\n- another list item\n  - a nested item\n"
            )
        files[f"ch-{n}.md"] = main_fm(
            f"Chapter Title {n}", order, f"ch-{n}", n, part, parts[part]
        ) + chapter_body(rng, 3, extra)
        order += 1
    files["appendix-a.md"] = main_fm("Appendix A: Reference Tables", order, "appendix-a") + chapter_body(rng, 1)
    files["afterword.md"] = main_fm("Afterword", order + 1, "afterword") + paragraph(rng) + "\n"
    for name, text in files.items():
        (chapters / name).write_text(text, encoding="utf-8")

    from PIL import Image, ImageDraw

    img = Image.new("L", (1500, 750), 255)
    draw = ImageDraw.Draw(img)
    for x0 in (60, 780):
        draw.rectangle([x0, 60, x0 + 660, 690], outline=0, width=6)
        for y in range(140, 640, 40):
            draw.line([x0 + 60, y, x0 + 600, y], fill=120, width=4)
    draw.line([750, 40, 750, 710], fill=0, width=8)
    img.save(ROOT / "images" / "spread.png", optimize=True)


if __name__ == "__main__":
    main()
