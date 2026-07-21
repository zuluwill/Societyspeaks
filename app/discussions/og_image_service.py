"""Render discussion OG share cards for Bluesky / X / LinkedIn unfurls."""

from __future__ import annotations

from typing import Optional

from app.lib import og_card_render as ocr


def is_available() -> bool:
    return ocr.is_available()


def render_discussion_png(
    *,
    title: str,
    topic: Optional[str] = None,
    participant_count: int = 0,
    badge_label: str = 'Public Discussion',
    participants_label: Optional[str] = None,
    cta_label: str = 'Join the conversation',
) -> Optional[bytes]:
    """Render a 1200×630 discussion card with title and social proof."""
    if participants_label:
        footer_left = participants_label
    elif participant_count > 0:
        footer_left = f'{participant_count} participants · {cta_label}'
    else:
        footer_left = cta_label

    badge = badge_label
    if topic and topic.strip():
        badge = f'{badge_label} · {topic.strip()[:40]}'

    return ocr.render_branded_card(
        badge_text=badge[:80],
        headline=title,
        footer_left=footer_left[:120],
        headline_max_lines=4,
    )
