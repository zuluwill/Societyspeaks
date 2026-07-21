"""Plain-text helpers for social share URLs."""

from __future__ import annotations

import html
from urllib.parse import quote


def plain_share_text(value) -> str:
    """Return unescaped plain text safe for share URL query params."""
    if value is None:
        return ''
    return html.unescape(str(value))


def share_urlencode(value) -> str:
    """URL-encode share copy after stripping HTML entities from Jinja autoescape."""
    return quote(plain_share_text(value), safe='')
