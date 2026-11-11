"""Final-image report rendering: deterministic JSON payload to Markdown.

``preflight.json`` is the machine-readable record and ``preflight.md`` is the
human-readable audit trail. Both are derived from the same payload, contain no
volatile timestamps and name artifacts by relative file name only.
"""

from __future__ import annotations

from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    """Render a human-readable preflight report from the JSON payload."""
    summary = report.get("summary", {})
    ready = bool(summary.get("ready"))
    lines = [
        f"# Print preflight: {report.get('book') or 'unknown book'}",
        "",
        f"**Status: {'READY' if ready else 'NOT READY'}** "
        f"({_count(summary, 'errors')} error(s), "
        f"{_count(summary, 'warnings')} warning(s), "
        f"{_count(summary, 'infos')} info)",
        "",
    ]

    provider = report.get("provider")
    if isinstance(provider, dict):
        lines.append(f"- provider: {provider.get('display_name')} ({provider.get('name')})")
    print_block = report.get("print")
    if isinstance(print_block, dict) and print_block:
        trim = print_block.get("trim") or {}
        lines.append(
            "- print: "
            f"{print_block.get('format')}, "
            f"{print_block.get('ink')} ink on {print_block.get('paper')} paper, "
            f"{print_block.get('finish')} finish, "
            f"{_format(trim.get('width'))} x {_format(trim.get('height'))} trim"
        )
        cover = print_block.get("cover") or {}
        lines.append(
            f"- finished book: {print_block.get('page_count')} pages, "
            f"spine {_format(print_block.get('spine'))}, "
            f"cover {_format(cover.get('width'))} x {_format(cover.get('height'))}"
        )
    artifacts = report.get("artifacts") or {}
    interior = artifacts.get("interior.pdf") or {}
    cover = artifacts.get("cover.pdf") or {}
    if interior:
        page_size = interior.get("page_size") or {}
        lines.append(
            f"- interior.pdf: {interior.get('pages')} pages, "
            f"{page_size.get('width')} x {page_size.get('height')}"
        )
    if cover:
        page_size = cover.get("page_size") or {}
        lines.append(
            f"- cover.pdf: {cover.get('pages')} page, "
            f"{page_size.get('width')} x {page_size.get('height')}"
        )
    lines.append("")

    checks = report.get("checks") or []
    lines.append("## Findings")
    lines.append("")
    if not checks:
        lines.append("No findings.")
    else:
        lines.append("| Severity | Rule | Finding | Context | Fix |")
        lines.append("|---|---|---|---|---|")
        for item in checks:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _cell(item.get("severity")),
                        _cell(item.get("rule_id")),
                        _cell(item.get("message")),
                        _cell(item.get("context") or ""),
                        _cell(item.get("suggestion") or ""),
                    )
                )
                + " |"
            )
    lines.append("")

    notes = report.get("notes") or []
    if notes:
        lines.append("## Before you upload")
        lines.append("")
        lines.extend(f"- {note}" for note in notes)
        lines.append("")

    lines.append("## Recorded provenance")
    lines.append("")
    tool = report.get("tool") or {}
    lines.append(f"- tool: {tool.get('name')} {tool.get('version')}")
    sources = (provider or {}).get("sources") if isinstance(provider, dict) else None
    if sources:
        lines.append("- provider rules:")
        for source in sources:
            lines.append(
                f"  - {source.get('title')} ({source.get('checked')}): {source.get('url')}"
            )
    source = report.get("source")
    if isinstance(source, dict) and source:
        lines.append(
            f"- manuscript: {source.get('book_json', {}).get('sha256', 'unknown')} (book.json)"
        )
    hashes = report.get("artifacts") or {}
    if hashes:
        lines.append("- output hashes:")
        for name in sorted(hashes):
            entry = hashes[name] or {}
            if entry.get("sha256"):
                lines.append(f"  - {name}: {entry['sha256']}")
    lines.append("")
    return "\n".join(lines)


def _count(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key, 0)
    return value if isinstance(value, int) else 0


def _format(value: Any) -> str:
    return str(value) if value not in (None, "") else "unknown"


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


__all__ = ["render_markdown"]
