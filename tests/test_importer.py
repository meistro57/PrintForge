import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from printforge.errors import InputError
from printforge.importer import (
    BookForgeImporter,
    UnsafePathError,
    discover_books,
    load_book,
    resolve_local_asset,
)
from printforge.interfaces import BookImporter

ROOT = Path(__file__).parent / "fixtures" / "bookforge-root"
SAMPLE = ROOT / "src/content/books/sample-book"


def snapshot(tree: Path) -> dict[str, tuple[str, int]]:
    """Content hash + mtime of every file (and dir mtimes) under ``tree``."""
    result = {}
    for path in sorted(tree.rglob("*")):
        st = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "dir"
        result[path.relative_to(tree).as_posix()] = (digest, st.st_mtime_ns)
    return result


def make_book(tmp_path: Path, chapters: dict[str, str | bytes], meta: dict | None = None) -> Path:
    book = tmp_path / "book"
    (book / "chapters").mkdir(parents=True)
    meta = {"slug": "book", "title": "T", "author": "A"} if meta is None else meta
    (book / "book.json").write_text(json.dumps(meta), encoding="utf-8")
    for name, text in chapters.items():
        target = book / "chapters" / name
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text, encoding="utf-8")
    return book


def chapter(title="C", order=1, extra="", body="Body.\n") -> str:
    return f'---\ntitle: "{title}"\norder: {order}\n{extra}---\n\n{body}'


# ------------------------------------------------------------------ happy path


def test_sample_book_metadata_and_order():
    book = load_book(SAMPLE)
    assert (book.slug, book.title, book.author) == (
        "sample-book",
        "The Sample Book",
        "A. N. Author",
    )
    assert book.subtitle == "A Synthetic Manuscript"
    assert book.web_cover == "images/web-cover.png"
    assert book.ignored_fields == ("theme", "audiobook")
    assert [c.slug for c in book.chapters] == [
        "title-page",
        "foreword",
        "ch-1",
        "ch-2",
        "ch-3",
        "ch-4",
        "appendix-a",
    ]
    assert [c.slug for c in book.front_matter] == ["title-page", "foreword"]
    assert book.root == SAMPLE.resolve()
    assert not [d for d in book.diagnostics if d.severity != "INFO"]


def test_parts_grouping_preserves_order():
    parts = load_book(SAMPLE).parts()
    assert [(p.number, p.title, [c.slug for c in p.chapters]) for p in parts] == [
        (None, None, ["title-page", "foreword"]),
        (1, "PART I: THE BEGINNING", ["ch-1", "ch-2"]),
        (2, "PART II: THE MIDDLE", ["ch-3", "ch-4"]),
        (None, None, ["appendix-a"]),
    ]


def test_chapter_fields_and_body():
    ch1 = next(c for c in load_book(SAMPLE).chapters if c.slug == "ch-1")
    assert ch1.title == "Chapter 1"
    assert ch1.chapter_number == 1 and ch1.part_number == 1
    assert ch1.relative_path == "chapters/ch-1.md"
    assert ch1.body.startswith("\nBody of chapter 1.")
    assert "---" not in ch1.body and "order:" not in ch1.body
    assert ch1.body_start_line == 10
    assert ch1.sha256 == hashlib.sha256((SAMPLE / "chapters/ch-1.md").read_bytes()).hexdigest()


def test_nullable_and_missing_optional_fields():
    foreword = next(c for c in load_book(SAMPLE).chapters if c.slug == "foreword")
    assert foreword.chapter_number is None and foreword.part_title is None
    second = load_book(ROOT / "src/content/books/second-book")
    only = second.chapters[0]
    assert only.slug == "ch-1"  # defaults to filename stem
    assert only.is_front_matter is False
    assert second.order == 999 and second.subtitle is None


def test_importer_protocol():
    assert isinstance(BookForgeImporter(), BookImporter)
    assert BookForgeImporter().load(SAMPLE).slug == "sample-book"


def test_discover_books_from_repo_root_and_books_dir():
    expected = [ROOT / "src/content/books/sample-book", ROOT / "src/content/books/second-book"]
    assert discover_books(ROOT) == expected
    assert discover_books(ROOT / "src/content/books") == expected


# ------------------------------------------------------------------ encodings


def test_bom_and_crlf(tmp_path):
    raw = chapter(title="Café ‘quotes’ — dash", body="Line one.\nLine two.\n")
    data = "\ufeff".encode() + raw.replace("\n", "\r\n").encode("utf-8")
    book = load_book(make_book(tmp_path, {"ch-1.md": data}))
    ch = book.chapters[0]
    assert ch.title == "Café ‘quotes’ — dash"
    assert "\r" not in ch.body and "Line one.\nLine two." in ch.body


def test_invalid_utf8_names_file(tmp_path):
    book = make_book(tmp_path, {"bad.md": b"---\ntitle: x\norder: 1\n---\n\xff\xfe"})
    with pytest.raises(InputError, match=r"chapters/bad.md: not valid UTF-8"):
        load_book(book)


# ------------------------------------------------------------------ ordering


def test_numeric_order_and_natural_filename_tiebreak(tmp_path):
    book = make_book(
        tmp_path,
        {
            "ch-10.md": chapter("Ten", order=5),
            "ch-2.md": chapter("Two", order=5),
            "ch-1.md": chapter("One", order=1.5),
            "z.md": chapter("Zero", order=0),
        },
    )
    result = load_book(book)
    assert [c.title for c in result.chapters] == ["Zero", "One", "Two", "Ten"]
    dup = [d for d in result.diagnostics if d.rule_id == "IMPORT-DUP-ORDER"]
    assert len(dup) == 1 and "ch-2.md, chapters/ch-10.md" in dup[0].message


def test_duplicate_chapter_number_is_warning(tmp_path):
    book = make_book(
        tmp_path,
        {
            "a.md": chapter("A", 1, "chapterNumber: 3\n"),
            "b.md": chapter("B", 2, "chapterNumber: 3\n"),
        },
    )
    rules = [d.rule_id for d in load_book(book).diagnostics]
    assert "IMPORT-DUP-CHAPTER-NUMBER" in rules


def test_duplicate_slug_is_error(tmp_path):
    book = make_book(
        tmp_path,
        {"a.md": chapter("A", 1, 'slug: "same"\n'), "b.md": chapter("B", 2, 'slug: "same"\n')},
    )
    with pytest.raises(InputError, match="duplicate chapter slugs.*'same'"):
        load_book(book)


def test_empty_chapter_and_unknown_fields_are_reported(tmp_path):
    book = make_book(tmp_path, {"a.md": chapter("A", 1, "mood: dark\n", body="")})
    rules = {d.rule_id: d for d in load_book(book).diagnostics}
    assert rules["IMPORT-EMPTY-CHAPTER"].severity == "WARNING"
    assert "mood" in rules["IMPORT-UNKNOWN-FIELD"].message


# ------------------------------------------------------------------ errors


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        ("no front matter\n", r"a.md:1: missing YAML front matter"),
        ("---\ntitle: x\norder: 1\n", r"a.md:1: front matter is not closed"),
        ("---\ntitle: x\norder: [1\n---\n", r"a.md:\d+: invalid YAML front matter"),
        ("---\n- a\n- b\n---\n", r"a.md:2: front matter must be a YAML mapping"),
        ("---\norder: 1\n---\n", r"missing required 'title'"),
        ('---\ntitle: ""\norder: 1\n---\n', r"a.md:2: front matter 'title' must be a non-empty"),
        ("---\ntitle: x\n---\n", r"missing required 'order'"),
        ('---\ntitle: x\norder: "3"\n---\n', r"a.md:3: front matter 'order' must be a number"),
        ("---\ntitle: x\norder: true\n---\n", r"'order' must be a number"),
        ("---\ntitle: x\norder: 1\nchapterNumber: two\n---\n", r"a.md:4: .*'chapterNumber'"),
        ("---\ntitle: x\norder: 1\nisFrontMatter: yes please\n---\n", r"'isFrontMatter'"),
        ("---\ntitle: x\norder: 1\npartTitle: 3\n---\n", r"'partTitle' must be a string"),
    ],
)
def test_malformed_chapter_errors_have_file_and_line(tmp_path, text, pattern):
    with pytest.raises(InputError, match=pattern):
        load_book(make_book(tmp_path, {"a.md": text}))


@pytest.mark.parametrize(
    ("meta", "pattern"),
    [
        ({"title": "T", "author": "A"}, "'slug' must be a non-empty string \\(missing\\)"),
        ({"slug": "s", "title": 3, "author": "A"}, "'title' must be a non-empty string"),
        ({"slug": "s", "title": "T", "author": "A", "order": "1"}, "'order' must be a number"),
        ({"slug": "s", "title": "T", "author": "A", "subtitle": 1}, "'subtitle' must be a str"),
        (["not", "object"], "must contain a JSON object"),
    ],
)
def test_invalid_book_json_fields(tmp_path, meta, pattern):
    with pytest.raises(InputError, match=pattern):
        load_book(make_book(tmp_path, {"a.md": chapter()}, meta=meta))


def test_invalid_json_reports_line(tmp_path):
    book = make_book(tmp_path, {"a.md": chapter()})
    (book / "book.json").write_text('{\n  "slug": "x",\n  "title": \n}', encoding="utf-8")
    with pytest.raises(InputError, match=r"book.json:4:1: invalid JSON"):
        load_book(book)


def test_missing_directories(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        load_book(tmp_path / "nope")
    with pytest.raises(InputError, match="no book.json"):
        load_book(tmp_path)
    (tmp_path / "book.json").write_text('{"slug":"s","title":"t","author":"a"}')
    with pytest.raises(InputError, match="no chapters/ directory"):
        load_book(tmp_path)
    (tmp_path / "chapters").mkdir()
    with pytest.raises(InputError, match="no chapter files"):
        load_book(tmp_path)
    with pytest.raises(InputError, match="not a directory"):
        discover_books(tmp_path / "book.json")


# ------------------------------------------------------------------ read-only


def test_import_does_not_modify_source():
    before = snapshot(SAMPLE)
    load_book(SAMPLE)
    load_book(SAMPLE)
    assert snapshot(SAMPLE) == before


def test_import_works_on_read_only_tree_and_failures_leave_it_untouched(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    copy = tmp_path / "ro"
    shutil.copytree(SAMPLE, copy)
    (copy / "chapters" / "broken.md").write_text("---\ntitle: [\n---\n", encoding="utf-8")
    paths = [copy, *copy.rglob("*")]
    for p in paths:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        before = snapshot(copy)
        with pytest.raises(InputError, match="broken.md"):
            load_book(copy)
        assert snapshot(copy) == before
    finally:
        for p in paths:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)


# ------------------------------------------------------------------ asset paths


def test_resolve_image_relative_to_chapter_then_root():
    book = load_book(SAMPLE)
    ch1 = next(c for c in book.chapters if c.slug == "ch-1")
    bases = (ch1.directory, book.root)
    expected = (SAMPLE / "images/diagram.png").resolve()
    assert resolve_local_asset("../images/diagram.png", root=book.root, bases=bases) == expected
    assert resolve_local_asset("images/diagram.png", root=book.root, bases=bases) == expected


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.com/x.png",
        "http://example.com/x.png",
        "//example.com/x.png",
        "data:image/png;base64,AAAA",
        "file:///etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\x.png",
        "../../../../etc/passwd",
        "../../second-book/book.json",
        "",
    ],
)
def test_unsafe_asset_references_rejected(ref):
    root = SAMPLE.resolve()
    with pytest.raises(UnsafePathError):
        resolve_local_asset(ref, root=root, bases=(root / "chapters", root))


def test_symlink_escape_rejected(tmp_path):
    book = make_book(tmp_path, {"a.md": chapter()})
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    (book / "link.png").symlink_to(outside)
    with pytest.raises(UnsafePathError, match="escapes"):
        resolve_local_asset("link.png", root=book.resolve())


def test_missing_asset_lists_candidates():
    root = SAMPLE.resolve()
    with pytest.raises(InputError, match="asset not found.*chapters/missing.png.*missing.png"):
        resolve_local_asset("missing.png", root=root, bases=(root / "chapters", root))
