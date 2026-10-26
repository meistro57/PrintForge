"""Safe resolution of manuscript-relative asset paths (images, cover art).

Only *local, relative* paths that stay inside the book root are accepted. URLs
(``http:``, ``data:``, ``file:``, protocol-relative ``//``), absolute paths and
anything that escapes the root (``..``, symlinks pointing outside) are refused.
Resolution never touches the filesystem beyond ``stat``/``realpath``.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from printforge.errors import InputError

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


class UnsafePathError(InputError):
    """A referenced path is remote, absolute, or escapes the book root."""


def _check_reference(ref: str) -> None:
    if not ref or not ref.strip():
        raise UnsafePathError("empty asset path")
    if ref.startswith("//") or (_SCHEME.match(ref) and not PureWindowsPath(ref).drive):
        raise UnsafePathError(
            f"remote or non-file asset reference is not allowed: {ref!r}",
            hint="download the asset into the book directory and reference it relatively",
        )
    if (
        PurePosixPath(ref).is_absolute()
        or PureWindowsPath(ref).is_absolute()
        or (PureWindowsPath(ref).drive)
    ):
        raise UnsafePathError(
            f"absolute asset path is not allowed: {ref!r}",
            hint="use a path relative to the chapter or book directory",
        )
    if "\x00" in ref:
        raise UnsafePathError(f"invalid asset path: {ref!r}")


def resolve_local_asset(ref: str, *, root: Path, bases: tuple[Path, ...] = ()) -> Path:
    """Resolve ``ref`` against each of ``bases`` (default: ``root``) in turn.

    Returns the first candidate that exists and lies inside ``root``. Raises
    :class:`UnsafePathError` for unsafe references (even if a file exists) and
    :class:`InputError` if no candidate exists.
    """
    _check_reference(ref)
    real_root = root.resolve()
    search = bases or (root,)
    tried: list[str] = []
    for base in search:
        candidate = (base / ref).resolve()
        if not candidate.is_relative_to(real_root):
            raise UnsafePathError(
                f"asset path escapes the book directory: {ref!r}",
                hint=f"keep assets inside {root}",
            )
        tried.append(candidate.relative_to(real_root).as_posix())
        if candidate.is_file():
            return candidate
    raise InputError(
        f"asset not found: {ref!r} (looked for: {', '.join(tried)})",
        hint="check the file name and that the file is inside the book directory",
    )
