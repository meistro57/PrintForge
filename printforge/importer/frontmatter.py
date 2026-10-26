"""Split and validate YAML front matter in BookForge chapter files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from printforge.errors import InputError


@dataclass(frozen=True, slots=True)
class SplitSource:
    front_matter: dict[str, Any]
    key_lines: dict[str, int]  # front-matter key -> 1-based line in the source file
    body: str
    body_start_line: int


def decode_source(data: bytes, label: str) -> str:
    """Decode UTF-8 (optional BOM) and normalize CRLF/CR newlines to LF."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(
            f"{label}: not valid UTF-8 (byte offset {exc.start})",
            hint="re-save the file as UTF-8",
        ) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_front_matter(text: str, label: str) -> SplitSource:
    """Separate a leading ``---`` YAML block from the Markdown body."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise InputError(
            f"{label}:1: missing YAML front matter (file must start with '---')",
            hint="BookForge chapters need at least 'title' and 'order' front matter",
        )
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            closing = index
            break
    else:
        raise InputError(f"{label}:1: front matter is not closed with '---'")

    yaml_text = "\n".join(lines[1:closing])
    try:
        node = yaml.compose(yaml_text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else 1  # +1 delimiter, +1 for 1-based
        problem = getattr(exc, "problem", None) or str(exc)
        raise InputError(f"{label}:{line}: invalid YAML front matter: {problem}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise InputError(f"{label}:2: front matter must be a YAML mapping of key: value pairs")

    key_lines: dict[str, int] = {}
    if isinstance(node, yaml.MappingNode):
        for key_node, _value in node.value:
            key_lines[str(key_node.value)] = key_node.start_mark.line + 2

    body = "\n".join(lines[closing + 1 :])
    return SplitSource(
        front_matter={str(k): v for k, v in data.items()},
        key_lines=key_lines,
        body=body,
        body_start_line=closing + 2,
    )
