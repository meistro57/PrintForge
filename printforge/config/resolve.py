"""Load ``print.json`` and resolve the layered settings into a ``ResolvedPrintJob``."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from printforge.book import Book
from printforge.config.defaults import PLATFORM_DEFAULTS
from printforge.config.settings import SCHEMA_VERSION, PrintSettings, validate
from printforge.errors import ConfigError

CONFIG_FILENAME = "print.json"
_META_KEYS = ("$schema", "$comment")

LAYER_PLATFORM = "platform defaults"
LAYER_CLI = "command line"


@dataclass(frozen=True, slots=True)
class ResolvedPrintJob:
    """Normalized, validated settings for one book build."""

    settings: PrintSettings
    book_slug: str
    layers: tuple[str, ...]  # applied layers, lowest precedence first
    provenance: dict[str, str]  # dotted setting path -> layer that set it
    config_label: str | None  # e.g. "print.json"; never an absolute path
    config_sha256: str | None
    config_dir: Path  # base directory for relative cover/image paths (not serialized)
    metadata: dict[str, Any] = field(default_factory=dict)  # book.json + overrides

    @property
    def provider(self) -> str:
        return self.settings.provider

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, machine-independent representation for manifests."""
        settings = self.settings.to_dict()
        settings.pop("output", None)  # output location is environment-specific
        return {
            "schema_version": SCHEMA_VERSION,
            "book": self.book_slug,
            "provider": self.provider,
            "layers": list(self.layers),
            "config": {"file": self.config_label, "sha256": self.config_sha256},
            "metadata": dict(self.metadata),
            "settings": settings,
            "provenance": {k: self.provenance[k] for k in sorted(self.provenance)},
        }


def load_config_file(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a print.json file (read-only). Returns (data, sha256)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: print.json must contain a JSON object")
    for key in _META_KEYS:
        data.pop(key, None)
    return data, hashlib.sha256(raw).hexdigest()


def _merge(
    base: dict[str, Any], layer: Mapping[str, Any], label: str, prov: dict[str, str], prefix=""
) -> None:
    for key, value in layer.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _merge(base[key], value, label, prov, path)
        else:
            base[key] = copy.deepcopy(value)
            stale = [p for p in prov if p.startswith(path + ".")]
            for p in stale:
                del prov[p]
            prov[path] = label
            if isinstance(value, Mapping):
                for sub in _leaf_paths(value, path):
                    prov[sub] = label


def _leaf_paths(data: Mapping[str, Any], prefix: str) -> list[str]:
    paths = []
    for key, value in data.items():
        path = f"{prefix}.{key}"
        paths.extend(_leaf_paths(value, path) if isinstance(value, Mapping) else [path])
    return paths


def _provider_name(cli: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    for layer in (cli, config):
        if "provider" in layer:
            value = layer["provider"]
            if not isinstance(value, str):
                raise ConfigError(f"provider: must be a string, got {value!r}")
            return value
    return PLATFORM_DEFAULTS["provider"]


def _book_metadata(book: Book, settings: PrintSettings) -> dict[str, Any]:
    meta = settings.metadata
    return {
        "title": meta.title or book.title,
        "subtitle": meta.subtitle if meta.subtitle is not None else book.subtitle,
        "author": meta.author or book.author,
        "description": meta.description if meta.description is not None else book.description,
        "language": meta.language,
        "isbn": meta.isbn,
        "publisher": meta.publisher,
        "copyright_year": meta.copyright_year,
        "copyright_holder": meta.copyright_holder,
        "edition": meta.edition,
    }


def resolve_print_job(
    book: Book,
    *,
    config_path: Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> ResolvedPrintJob:
    """Resolve settings for ``book``.

    ``config_path``: explicit ``--config`` file; otherwise ``<book>/print.json`` is
    used if present (it is optional and never created or edited).
    ``cli_overrides``: nested dict of explicit command-line values (highest precedence).
    """
    cli = dict(cli_overrides or {})
    if config_path is not None:
        config, digest = load_config_file(Path(config_path))
        label = f"{CONFIG_FILENAME} (--config {Path(config_path).name})"
        config_label: str | None = Path(config_path).name
        config_dir = Path(config_path).resolve().parent
    elif (book.root / CONFIG_FILENAME).is_file():
        config, digest = load_config_file(book.root / CONFIG_FILENAME)
        label = CONFIG_FILENAME
        config_label = CONFIG_FILENAME
        config_dir = book.root
    else:
        config, digest, label, config_label, config_dir = {}, None, None, None, book.root

    from printforge.providers import get_provider  # deferred: providers import config

    provider = _provider_name(cli, config)
    provider_layer = get_provider(provider).default_settings()

    merged: dict[str, Any] = {}
    prov: dict[str, str] = {}
    layers = [LAYER_PLATFORM, f"provider defaults ({provider})"]
    _merge(merged, PLATFORM_DEFAULTS, LAYER_PLATFORM, prov)
    _merge(merged, provider_layer, layers[1], prov)
    if label is not None:
        layers.append(label)
        _merge(merged, config, label, prov)
    if cli:
        layers.append(LAYER_CLI)
        _merge(merged, cli, LAYER_CLI, prov)

    def source_of(path: str) -> str:
        probe = path
        while probe:
            if probe in prov:
                return prov[probe]
            probe = probe.rpartition(".")[0]
        return label or LAYER_PLATFORM

    settings = validate(merged, source_of)
    return ResolvedPrintJob(
        settings=settings,
        book_slug=book.slug,
        layers=tuple(layers),
        provenance=dict(prov),
        config_label=config_label,
        config_sha256=digest,
        config_dir=config_dir,
        metadata=_book_metadata(book, settings),
    )
