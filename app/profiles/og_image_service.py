"""Render public profile OG share cards."""

from __future__ import annotations

from typing import Optional

from app.lib import og_card_render as ocr


def is_available() -> bool:
    return ocr.is_available()


def render_profile_png(
    *,
    name: str,
    is_company: bool = False,
    badge_label: Optional[str] = None,
    footer_label: Optional[str] = None,
    cta_label: str = 'Join the conversation on Society Speaks',
) -> Optional[bytes]:
    """Render a 1200×630 profile card."""
    badge = badge_label or ('Organization' if is_company else 'Community voice')
    footer_left = footer_label or cta_label

    return ocr.render_branded_card(
        badge_text=badge,
        headline=name,
        footer_left=footer_left[:120],
        headline_max_lines=2,
    )
