"""Built-in settings layers.

Precedence (lowest to highest)::

    platform defaults  <  provider defaults  <  print.json  <  explicit CLI flags

``PLATFORM_DEFAULTS`` is complete: every setting has a value, so the validator
never has to invent one. Provider layers only override what the provider cares
about.
"""

from __future__ import annotations

from typing import Any

PLATFORM_DEFAULTS: dict[str, Any] = {
    "version": 1,
    "provider": "kdp",
    "format": "paperback",
    "trim": {"width": "6in", "height": "9in"},
    "interior": {"bleed": False, "ink": "black", "paper": "white"},
    "margins": {
        "top": "0.75in",
        "bottom": "0.75in",
        "outside": "0.625in",
        "inside": "auto",
        "gutter_extra": "0.125in",
    },
    "typography": {
        "body_font": "DejaVu Serif",
        "heading_font": "DejaVu Serif",
        "mono_font": "DejaVu Sans Mono",
        "font_size": "10.5pt",
        "line_height": "1.4",
        "paragraph_indent": "0.25in",
        "justify": True,
        "hyphenate": True,
        "language": "en",
    },
    "images": {"min_dpi": 300},
    "toc": {
        "enabled": True,
        "depth": 1,
        "title": "Contents",
        "include_front_matter": False,
        "include_parts": True,
    },
    "front_matter": {"half_title": False, "title_page": True, "copyright_page": True},
    "metadata": {
        "title": None,
        "subtitle": None,
        "author": None,
        "description": None,
        "language": None,
        "isbn": None,
        "publisher": None,
        "copyright_year": None,
        "copyright_holder": None,
        "edition": None,
    },
    "cover": {
        "finish": "matte",
        "front_image": None,
        "back_image": None,
        "wrap_image": None,
        "spine_text": "auto",
        "background_color": "#1F2A44",
        "text_color": "#FFFFFF",
        "back_text": None,
    },
    "output": {"directory": None},
}

# Provider default layers (KDP paperback: 6x9 in, black ink, white paper, no bleed).
PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "kdp": {
        "format": "paperback",
        "trim": {"width": "6in", "height": "9in"},
        "interior": {"bleed": False, "ink": "black", "paper": "white"},
    },
}
