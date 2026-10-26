"""Optional: import every book from a real BookForge checkout, read-only.

Set ``PRINTFORGE_BOOKFORGE_ROOT=/path/to/BookForge`` to enable. Skipped in CI.
"""

import os
from pathlib import Path

import pytest

from printforge.importer import discover_books, load_book
from tests.test_importer import snapshot

ROOT = os.environ.get("PRINTFORGE_BOOKFORGE_ROOT")

pytestmark = pytest.mark.skipif(not ROOT, reason="PRINTFORGE_BOOKFORGE_ROOT not set")


def test_real_bookforge_books_import_read_only():
    books_dir = Path(ROOT) / "src/content/books"
    before = snapshot(books_dir)
    found = discover_books(Path(ROOT))
    assert found
    for book_dir in found:
        book = load_book(book_dir)
        assert book.chapters, book_dir
    assert snapshot(books_dir) == before
