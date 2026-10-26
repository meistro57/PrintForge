"""CSS Paged Media stylesheet generated from a :class:`LayoutPlan`.

HTML contract (produced by the renderer, #7). Every top-level unit is a
``<section>`` with exactly one of these classes:

==========================  ================================================
``pf-display``              half title / title / copyright pages (no folio)
``pf-front``                contents, foreword, ... (front-matter folios)
``pf-part``                 part divider page
``pf-chapter``              chapter, appendix or back-matter chapter
==========================  ================================================

Add ``pf-start`` to the first main-matter unit (part or chapter): folio 1 starts
there. Within ``pf-display``, pages are ``<div class="pf-page pf-recto|pf-verso">``.
Chapter titles are ``h1.pf-chapter-title`` (feeds the recto running head), an
optional ``.pf-chapter-label`` precedes it; body headings are ``h2``-``h6``.

Geometry (page size, mirrored margins) comes only from the plan; nothing here
depends on Markdown parsing or on a specific provider.
"""

from __future__ import annotations

from printforge.layout.plan import (
    CHAPTER,
    DISPLAY,
    FRONT,
    PART,
    START_SUFFIX,
    ChapterStart,
    FolioPosition,
    FolioStyle,
    LayoutPlan,
    PageSide,
    SectionPolicy,
)

SECTION_CLASSES = {DISPLAY: "pf-display", FRONT: "pf-front", PART: "pf-part", CHAPTER: "pf-chapter"}


def css_string(text: str) -> str:
    """Quote ``text`` as a CSS string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\A ")
    return f'"{escaped}"'


def _pt(length) -> str:
    return length.to_str("pt", 3)


def font_family(name: str) -> str:
    # Exactly one family and no generic fallback: substitution must not happen
    # silently. The renderer verifies the embedded fonts after rendering.
    return css_string(name)


def _margin_decl(plan: LayoutPlan, side: PageSide) -> str:
    m = plan.geometry.margins(side)
    return f"margin: {m.top.css()} {m.right.css()} {m.bottom.css()} {m.left.css()};"


def _folio_boxes(plan: LayoutPlan, policy: SectionPolicy, side: PageSide) -> list[str]:
    boxes = ["@bottom-left", "@bottom-center", "@bottom-right"]
    if policy.folio is FolioStyle.NONE:
        return [f"{box} {{ content: none; }}" for box in boxes]
    if plan.layout.folio_position is FolioPosition.BOTTOM_CENTER:
        target = "@bottom-center"
    else:  # outside edge: left on versos, right on rectos
        target = "@bottom-right" if side is PageSide.RECTO else "@bottom-left"
    rules = []
    for box in boxes:
        if box == target:
            rules.append(
                f"{box} {{ content: counter(page, {policy.folio.value}); "
                "vertical-align: top; padding-top: 0.15in; font-size: 0.85em; }"
            )
        else:
            rules.append(f"{box} {{ content: none; }}")
    return rules


def _head_box(plan: LayoutPlan, policy: SectionPolicy, side: PageSide) -> str:
    if not policy.running_heads:
        return "@top-center { content: none; }"
    content = css_string(plan.book_title) if side is PageSide.VERSO else "string(pf-chapter)"
    return (
        f"@top-center {{ content: {content}; vertical-align: bottom; padding-bottom: 0.2in; "
        "font-size: 0.8em; letter-spacing: 0.05em; text-transform: uppercase; }"
    )


def _page_rules(plan: LayoutPlan) -> list[str]:
    g = plan.geometry
    pseudo = {PageSide.RECTO: ":right", PageSide.VERSO: ":left"}
    body_font = font_family(plan.typography.body_font)
    rules = [
        f"@page {{ size: {g.page.width.css()} {g.page.height.css()}; "
        f"font-family: {body_font}; font-size: {_pt(plan.typography.font_size)}; }}"
    ]
    for side in (PageSide.RECTO, PageSide.VERSO):
        default = plan.section(CHAPTER)
        inner = [_margin_decl(plan, side), _head_box(plan, default, side)]
        inner += _folio_boxes(plan, default, side)
        rules.append(f"@page {pseudo[side]} {{ {' '.join(inner)} }}")
    for name, policy in plan.sections.items():
        for side in (PageSide.RECTO, PageSide.VERSO):
            inner = [_head_box(plan, policy, side), *_folio_boxes(plan, policy, side)]
            rules.append(f"@page {name}{pseudo[side]} {{ {' '.join(inner)} }}")
        if name in (PART, CHAPTER, PART + START_SUFFIX, CHAPTER + START_SUFFIX):
            # No running head on the opening page of each part/chapter.
            reset = " counter-reset: page 1;" if policy.restart_numbering else ""
            rules.append(
                f"@page {name}:nth(1 of {name}) {{{reset} @top-center {{ content: none; }} }}"
            )
    # Intentionally blank pages (inserted before recto starts): no heads, no folio.
    rules.append(
        "@page :blank { @top-center { content: none; } @bottom-left { content: none; } "
        "@bottom-center { content: none; } @bottom-right { content: none; } }"
    )
    return rules


def _break(start: ChapterStart) -> str:
    return "recto" if start is ChapterStart.RECTO else "page"


def _section_rules(plan: LayoutPlan) -> list[str]:
    rules = []
    for name in (DISPLAY, FRONT, PART, CHAPTER):
        cls = SECTION_CLASSES[name]
        policy = plan.section(name)
        rules.append(f"section.{cls} {{ page: {name}; break-before: {_break(policy.start)}; }}")
        if name in (PART, CHAPTER):
            start = plan.section(name + START_SUFFIX)
            rules.append(
                f"section.{cls}.pf-start {{ page: {name}{START_SUFFIX}; "
                f"break-before: {_break(start.start)}; }}"
            )
    rules += [
        "section:first-child { break-before: auto; }",
        ".pf-page.pf-recto { break-before: recto; }",
        ".pf-page.pf-verso { break-before: verso; }",
        ".pf-page:first-child { break-before: auto; }",
    ]
    return rules


def _typography_rules(plan: LayoutPlan) -> list[str]:
    t = plan.typography
    lay = plan.layout
    lead = format(t.line_height.normalize(), "f")
    max_image_height = (plan.geometry.text_height * 85 / 100).css()
    align = "justify" if t.justify else "left"
    hyphens = "auto" if t.hyphenate else "manual"
    heading = font_family(t.heading_font)
    return [
        f"html {{ font-family: {font_family(t.body_font)}; font-size: {_pt(t.font_size)}; }}",
        f"body {{ margin: 0; line-height: {lead}; widows: {lay.widows}; orphans: {lay.orphans}; }}",
        f"p {{ margin: 0; text-align: {align}; hyphens: {hyphens}; }}",
        f"p + p {{ text-indent: {t.paragraph_indent.css()}; }}",
        f"h1, h2, h3, h4, h5, h6 {{ font-family: {heading}; font-weight: bold; line-height: 1.25; "
        "break-after: avoid; break-inside: avoid; hyphens: manual; text-align: left; }",
        "h2 { font-size: 1.3em; margin: 1.4em 0 0.6em; }",
        "h3 { font-size: 1.12em; margin: 1.2em 0 0.5em; }",
        "h4, h5, h6 { font-size: 1em; margin: 1em 0 0.4em; }",
        "h4 { font-style: italic; }",
        # Chapter openers
        "header.pf-opener { padding-top: 1.25in; margin-bottom: 0.45in; break-after: avoid; }",
        ".pf-chapter-label { font-size: 0.9em; letter-spacing: 0.12em; text-transform: uppercase; "
        "margin: 0 0 0.6em; text-align: left; }",
        "h1.pf-chapter-title { string-set: pf-chapter content(); font-size: 1.75em; "
        "margin: 0; text-align: left; }",
        "section.pf-part { text-align: center; padding-top: 2.6in; }",
        ".pf-part-label { font-size: 0.95em; letter-spacing: 0.15em; text-transform: uppercase; "
        "text-align: center; margin-bottom: 0.6em; }",
        "h1.pf-part-title { font-size: 1.8em; text-align: center; margin: 0; }",
        # Body blocks
        "blockquote { margin: 0.8em 0.3in; font-size: 0.95em; }",
        "blockquote p { text-indent: 0 !important; }",
        "ul, ol { margin: 0.6em 0 0.6em 0.3in; padding: 0; }",
        "li { margin: 0.15em 0; }",
        "li > p { text-indent: 0 !important; }",
        f"pre, code {{ font-family: {font_family(t.mono_font)}; }}",
        "code { font-size: 0.88em; }",
        "pre { font-size: 0.82em; line-height: 1.35; margin: 0.8em 0; padding: 0.4em 0.15in; "
        "white-space: pre-wrap; overflow-wrap: anywhere; border-left: 0.75pt solid #000000; }",
        "pre code { font-size: 1em; }",
        "hr.pf-break { border: 0; margin: 1em 0; text-align: center; height: 1.2em; }",
        'hr.pf-break::after { content: "* * *"; letter-spacing: 0.3em; }',
        "table { width: 100%; border-collapse: collapse; margin: 0.8em 0; font-size: 0.88em; }",
        "thead { display: table-header-group; }",
        "th, td { border-bottom: 0.5pt solid #000000; padding: 0.25em 0.4em; "
        "text-align: left; vertical-align: top; hyphens: auto; }",
        "th { font-weight: bold; border-bottom-width: 1pt; }",
        "tr { break-inside: avoid; }",
        "figure { margin: 1em 0; text-align: center; break-inside: avoid; }",
        f"figure img, p img {{ max-width: 100%; max-height: {max_image_height}; }}",
        "figcaption { font-size: 0.85em; font-style: italic; margin-top: 0.4em; "
        "text-align: center; }",
        "a { color: inherit; text-decoration: none; }",
        ".pf-display p { text-indent: 0; text-align: center; }",
    ]


def stylesheet(plan: LayoutPlan) -> str:
    """Complete, deterministic stylesheet for ``plan``."""
    parts = [
        f"/* PrintForge layout: page {plan.geometry.page.width} x {plan.geometry.page.height}, "
        f"gutter {plan.geometry.inside} ({plan.gutter_rule}) */",
        *_page_rules(plan),
        *_section_rules(plan),
        *_typography_rules(plan),
    ]
    return "\n".join(parts) + "\n"


def describe(plan: LayoutPlan) -> dict[str, object]:
    """Serializable summary of the plan (for build reports)."""
    g = plan.geometry

    def margins(side: PageSide) -> dict[str, str]:
        m = g.margins(side)
        return {k: getattr(m, k).to_str("in") for k in ("top", "bottom", "left", "right")}

    return {
        "page": g.page.to_dict(),
        "trim": g.trim.to_dict(),
        "inside_margin": g.inside.to_str("in"),
        "outside_margin": g.outside.to_str("in"),
        "gutter_rule": plan.gutter_rule,
        "page_count_basis": plan.page_count_basis,
        "recto_margins": margins(PageSide.RECTO),
        "verso_margins": margins(PageSide.VERSO),
        "text_block": {"width": g.text_width.to_str("in"), "height": g.text_height.to_str("in")},
        "sections": {
            name: {
                "folio": str(p.folio),
                "running_heads": p.running_heads,
                "start": str(p.start),
                "restart_numbering": p.restart_numbering,
            }
            for name, p in sorted(plan.sections.items())
        },
    }


__all__ = ["SECTION_CLASSES", "css_string", "describe", "font_family", "stylesheet"]
