"""Translate explicit command-line flags into the highest-precedence settings layer."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from printforge.config.settings import Ink, Paper
from printforge.errors import ConfigError

_TRIM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(in|mm|cm)?\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(in|mm|cm)?\s*$")


def parse_trim(value: str) -> dict[str, str]:
    """``"6x9"`` / ``"6x9in"`` / ``"152.4x228.6mm"`` -> {"width": ..., "height": ...}."""
    match = _TRIM.match(value)
    if not match:
        raise ConfigError(
            f"--trim: expected WIDTHxHEIGHT such as 6x9 or 152.4x228.6mm, got {value!r}"
        )
    width, unit_w, height, unit_h = match.groups()
    unit = unit_h or unit_w or "in"
    return {"width": f"{width}{unit_w or unit}", "height": f"{height}{unit}"}


def add_settings_arguments(parser: argparse.ArgumentParser) -> None:
    """Flags shared by every command that resolves print settings."""
    group = parser.add_argument_group("print settings (override print.json)")
    group.add_argument(
        "--config", type=Path, metavar="FILE", help="use FILE instead of <book_dir>/print.json"
    )
    group.add_argument("--provider", help="POD provider profile (default: kdp)")
    group.add_argument(
        "--trim", metavar="WxH", help="trim size, e.g. 6x9 (inches) or 152.4x228.6mm"
    )
    group.add_argument("--ink", choices=[i.value for i in Ink], help="interior ink")
    group.add_argument("--paper", choices=[p.value for p in Paper], help="interior paper")
    bleed = group.add_mutually_exclusive_group()
    bleed.add_argument("--bleed", dest="bleed", action="store_true", default=None)
    bleed.add_argument("--no-bleed", dest="bleed", action="store_false")
    group.add_argument("--toc-depth", type=int, metavar="N", help="table of contents depth (1-3)")
    group.add_argument("--output", "-o", metavar="DIR", help="output directory")


def overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Only flags the user actually passed become overrides."""
    out: dict[str, Any] = {}
    if getattr(args, "provider", None):
        out["provider"] = args.provider
    if getattr(args, "trim", None):
        out["trim"] = parse_trim(args.trim)
    interior = {}
    if getattr(args, "ink", None):
        interior["ink"] = args.ink
    if getattr(args, "paper", None):
        interior["paper"] = args.paper
    if getattr(args, "bleed", None) is not None:
        interior["bleed"] = args.bleed
    if interior:
        out["interior"] = interior
    if getattr(args, "toc_depth", None) is not None:
        out["toc"] = {"depth": args.toc_depth}
    if getattr(args, "output", None):
        out["output"] = {"directory": args.output}
    return out
