"""Plain-text share copy for social platforms (built in Python, not Jinja)."""

from __future__ import annotations

from flask_babel import _


def build_discussion_share_text(title: str, *, participant_count: int | None = None) -> str:
    """Engagement-focused copy for discussion permalinks."""
    clean_title = (title or '').strip()
    if participant_count and participant_count > 0:
        return _(
            '%(title)s — %(count)d people are weighing in. Add your voice on Society Speaks.',
            title=clean_title,
            count=participant_count,
        )
    return _(
        '%(title)s — What do you think? Join the conversation on Society Speaks.',
        title=clean_title,
    )


def build_brief_share_text(
    brief_title: str,
    *,
    story_count: int,
    brief_type: str = 'daily',
) -> str:
    """Engagement-focused copy for Daily / Weekly Brief permalinks."""
    clean_title = (brief_title or '').strip()
    count = max(int(story_count or 0), 0)
    if brief_type == 'weekly':
        return _(
            '%(title)s — %(count)d under-reported stories from 140+ sources. Free civic intelligence.',
            title=clean_title,
            count=count,
        )
    return _(
        '%(title)s — %(count)d curated stories with multi-perspective analysis. Your 5-minute civic upgrade.',
        title=clean_title,
        count=count,
    )


def build_profile_share_text(name: str, *, is_company: bool = False) -> str:
    """Share copy for public profile pages."""
    clean_name = (name or '').strip()
    if is_company:
        return _(
            '%(name)s is shaping policy through public dialogue on Society Speaks — join the conversation.',
            name=clean_name,
        )
    return _(
        '%(name)s is contributing to public discourse on Society Speaks — add your voice.',
        name=clean_name,
    )
