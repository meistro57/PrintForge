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
from printforge.errors import ExitCode, NotImplementedYetError, PrintForgeError
from printforge.importer import load_book
from printforge.log import configure, get_logger

log = get_logger("cli")

DESCRIPTION = """\
PrintForge converts a Markdown manuscript (BookForge convention:
book.json + chapters/*.md) into local, manual-upload-ready print-on-demand
files. It never modifies the source manuscript and never uploads anything.
"""

EPILOG = """\
exit codes:
  0 ok            1 internal error   2 usage error      3 input error
  4 config error  5 provider constraint violated         6 render error
  7 preflight errors                 8 output error     9 not implemented yet
"""


def _cmd_build(args: argparse.Namespace) -> int:
    # Placeholder until the end-to-end pipeline lands (issue #10). It must not
    # produce any artifact that could be mistaken for a real build.
    raise NotImplementedYetError(
        f"'build' is not implemented yet; nothing was written for {args.book_dir}",
        hint="the end-to-end build pipeline is tracked in issue #10",
    )


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
        help="build print files for a book directory (placeholder; see #10)",
        description="Build print files for a book directory. NOT IMPLEMENTED YET (issue #10).",
    )
    build.add_argument("book_dir", type=Path, help="directory containing book.json")
    build.add_argument("--provider", default="kdp", choices=["kdp"], help="POD provider profile")
    build.set_defaults(func=_cmd_build)

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
