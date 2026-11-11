"""Command-line interface: ``printforge`` / ``python -m printforge``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from printforge import __version__
from printforge.config import resolve_print_job
from printforge.config.cli_overrides import add_settings_arguments, overrides_from_args
from printforge.diagnostics import Severity
from printforge.document import parse_book
from printforge.errors import ExitCode, InputError, PrintForgeError
from printforge.importer import discover_books, load_book
from printforge.log import configure, get_logger
from printforge.preflight import inspect_build
from printforge.providers import get_provider
from printforge.publish import build_book

log = get_logger("cli")

DESCRIPTION = """\
PrintForge converts a Markdown manuscript (BookForge convention:
book.json + chapters/*.md) into local, manual-upload-ready print-on-demand
files. It never modifies the source manuscript and never uploads anything.
"""

EPILOG = """\
PrintForge only writes local files for manual upload. It does not talk to
Amazon or any other print-on-demand service.

examples:
  printforge settings tests/fixtures/print-book --trim 6x9
  printforge inspect tests/fixtures/print-book
  printforge build tests/fixtures/print-book --output build/print-book
  printforge check build/print-book
  printforge discover /path/to/BookForge

exit codes:
  0 ok            1 internal error   2 usage error      3 input error
  4 config error  5 provider constraint violated         6 render error
  7 preflight errors                 8 output error     9 not implemented yet
"""


def _cmd_build(args: argparse.Namespace) -> int:
    build_book(
        args.book_dir,
        config_path=args.config,
        cli_overrides=overrides_from_args(args),
        force=args.force,
    )
    return int(ExitCode.OK)


def _cmd_check(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        raise InputError(
            f"not a build output directory: {output_dir}",
            hint="pass the directory 'printforge build --output' wrote to",
        )
    result = inspect_build(output_dir)
    json_path, markdown_path = result.write()
    for item in result.diagnostics:
        if item.severity is Severity.ERROR:
            log.error("%s", item.format())
        elif item.severity is Severity.WARNING:
            log.warning("%s", item.format())
        else:
            log.debug("%s", item.format())
    summary = result.report["summary"]
    if result.has_errors:
        log.error(
            "preflight: %d error(s), %d warning(s); see %s",
            summary["errors"],
            summary["warnings"],
            markdown_path,
        )
        return int(ExitCode.PREFLIGHT)
    log.info(
        "preflight: ready (%d warning(s), %d info); see %s and %s",
        summary["warnings"],
        summary["infos"],
        json_path,
        markdown_path,
    )
    return int(ExitCode.OK)


def _cmd_inspect(args: argparse.Namespace) -> int:
    book = load_book(args.book_dir)
    job = resolve_print_job(book, config_path=args.config, cli_overrides=overrides_from_args(args))
    document = parse_book(book)
    provider = get_provider(job.provider)
    staged = (
        [("import", item) for item in book.diagnostics]
        + [("document", item) for item in document.diagnostics]
        + [("provider", item) for item in provider.validate_settings(job.settings)]
    )
    payload = {
        "book": {
            "slug": book.slug,
            "title": book.title,
            "author": book.author,
            "subtitle": book.subtitle,
            "order": book.order,
            "chapters": len(book.chapters),
        },
        "chapters": [
            {
                "id": chapter.id,
                "title": chapter.title,
                "kind": str(chapter.kind),
                "source": chapter.source,
                "number": chapter.number,
                "part_number": chapter.part_number,
                "part_title": chapter.part_title,
                "headings": len(chapter.headings),
                "blocks": len(chapter.blocks),
            }
            for chapter in document.chapters
        ],
        "document": {
            "chapters": len(document.chapters),
            "headings": sum(len(chapter.headings) for chapter in document.chapters),
            "images": len(document.images),
        },
        "provider": {
            "name": provider.name,
            "display_name": provider.display_name,
            "sources": [source.to_dict() for source in provider.sources],
        },
        "settings": job.to_dict(),
        "diagnostics": [{"stage": stage, **item.to_dict()} for stage, item in staged],
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    has_errors = any(item.severity is Severity.ERROR for _stage, item in staged)
    return int(ExitCode.PREFLIGHT if has_errors else ExitCode.OK)


def _cmd_discover(args: argparse.Namespace) -> int:
    root = Path(args.root)
    base = root.expanduser().resolve()
    for path in discover_books(root):
        try:
            shown = path.resolve().relative_to(base)
        except ValueError:  # pragma: no cover - a book outside the search root
            shown = path
        sys.stdout.write(shown.as_posix() + "\n")
    return int(ExitCode.OK)


def _cmd_settings(args: argparse.Namespace) -> int:
    book = load_book(args.book_dir)
    job = resolve_print_job(book, config_path=args.config, cli_overrides=overrides_from_args(args))
    json.dump(job.to_dict(), sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return int(ExitCode.OK)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printforge",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"printforge {__version__}")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    build = sub.add_parser(
        "build",
        help="build the PDFs, cover spec, manifest, report and preflight report",
        description=(
            "Build print-ready files for a book directory. The output directory "
            "receives interior.pdf, cover.pdf, cover-spec.json, metadata.json, "
            "build-report.json, preflight.json and preflight.md. Existing builds "
            "are only replaced with --force."
        ),
    )
    build.add_argument("book_dir", type=Path, help="directory containing book.json")
    add_settings_arguments(build)
    build.add_argument(
        "--force",
        action="store_true",
        help="replace a previous PrintForge build in the output directory",
    )
    build.set_defaults(func=_cmd_build)

    check = sub.add_parser(
        "check",
        help="preflight an existing build output directory",
        description=(
            "Inspect a directory produced by 'printforge build': verify the PDFs, cover "
            "geometry, manifest and hashes, then write preflight.json and preflight.md. "
            "Exits 7 when an ERROR-level finding would make the files unsafe to upload."
        ),
    )
    check.add_argument("output_dir", type=Path, help="directory written by 'printforge build'")
    check.set_defaults(func=_cmd_check)

    inspect = sub.add_parser(
        "inspect",
        help="report book, chapters, settings and diagnostics as JSON (no rendering)",
        description=(
            "Validate a manuscript and print a JSON report of the book, its chapters, "
            "the resolved print settings and any diagnostics. Nothing is rendered."
        ),
    )
    inspect.add_argument("book_dir", type=Path, help="directory containing book.json")
    add_settings_arguments(inspect)
    inspect.set_defaults(func=_cmd_inspect)

    discover = sub.add_parser(
        "discover",
        help="list book directories under a BookForge checkout",
        description=(
            "Find book directories by the BookForge convention "
            "(src/content/books/**/book.json) and print each path relative to ROOT."
        ),
    )
    discover.add_argument("root", type=Path, help="BookForge checkout (or a books directory)")
    discover.set_defaults(func=_cmd_discover)

    settings = sub.add_parser(
        "settings",
        help="print the resolved print settings for a book as JSON",
        description=(
            "Resolve print settings (platform defaults < provider defaults < print.json "
            "< command-line flags), validate them, and print the result as JSON."
        ),
    )
    settings.add_argument("book_dir", type=Path, help="directory containing book.json")
    add_settings_arguments(settings)
    settings.set_defaults(func=_cmd_settings)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: --help/--version exit 0, errors exit 2
        return int(exc.code or 0)

    configure(-1 if args.quiet else (1 if args.verbose else 0))
    try:
        return int(args.func(args))
    except PrintForgeError as exc:
        log.error("%s", exc)
        return int(exc.exit_code)
    except KeyboardInterrupt:
        log.error("interrupted")
        return int(ExitCode.INTERNAL)
    except Exception:  # pragma: no cover - defensive
        log.exception("internal error (this is a bug; please report it)")
        return int(ExitCode.INTERNAL)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
