"""Render Daily / Weekly Brief OG share cards."""

from __future__ import annotations

from typing import Optional

from app.lib import og_card_render as ocr


def is_available() -> bool:
    return ocr.is_available()


def render_brief_png(
    *,
    title: str,
    story_count: int = 0,
    brief_type: str = 'daily',
    badge_label: str = 'Daily Brief',
    stories_label: Optional[str] = None,
    cta_label: str = 'Free civic intelligence from 140+ sources',
) -> Optional[bytes]:
    """Render a 1200×630 brief card with title and story count."""
    if stories_label:
        footer_left = stories_label
    elif story_count > 0:
        footer_left = f'{story_count} stories · {cta_label}'
    else:
        footer_left = cta_label

    badge = badge_label if brief_type == 'daily' else 'Weekly Brief'

    return ocr.render_branded_card(
        badge_text=badge,
        headline=title,
        footer_left=footer_left[:120],
        headline_max_lines=3,
    )
