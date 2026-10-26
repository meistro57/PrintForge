"""Filesystem helpers: atomic writes so failures never leave partial files."""

from __future__ import annotations

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
        os.replace(tmp, path)
    except BaseException as exc:
        tmp.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise OutputError(f"cannot write {path}: {exc.strerror or exc}") from exc
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
