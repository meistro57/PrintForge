"""Provider registry. Core code looks providers up here by name."""

from __future__ import annotations

from printforge.errors import ConfigError
from printforge.providers.base import (
    CoverRules,
    PageCountRange,
    PageSize,
    ProviderProfile,
    RuleSource,
)
from printforge.providers.kdp import KDP

_REGISTRY: dict[str, ProviderProfile] = {KDP.name: KDP}


def provider_names() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> ProviderProfile:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ConfigError(
            f"provider: unknown provider {name!r} (supported: {', '.join(provider_names())})"
        ) from None


__all__ = [
    "CoverRules",
    "PageCountRange",
    "PageSize",
    "ProviderProfile",
    "RuleSource",
    "get_provider",
    "provider_names",
]
