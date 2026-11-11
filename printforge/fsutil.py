"""Filesystem helpers: atomic writes so failures never leave partial files."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from printforge.errors import OutputError


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temporary file + ``os.replace``.

    On any failure the temporary file is removed and ``path`` is left untouched.
    Empty payloads are refused (a zero-byte "success" would be misleading).
    """
    if not data:
        raise OutputError(f"refusing to write empty file {path}")
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"cannot create directory {path.parent}: {exc.strerror or exc}") from exc
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _apply_default_permissions(tmp)
        os.replace(tmp, path)
    except BaseException as exc:
        tmp.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise OutputError(f"cannot write {path}: {exc.strerror or exc}") from exc
        raise


def _apply_default_permissions(path: Path) -> None:
    """Give the finished file normal umask-based permissions.

    ``mkstemp`` creates 0600 files; build artifacts should be readable like any
    other output. Failures here must not fail the write itself.
    """
    umask = os.umask(0)
    os.umask(umask)
    with contextlib.suppress(OSError):  # pragma: no cover - unusual filesystem
        os.chmod(path, 0o666 & ~umask)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
