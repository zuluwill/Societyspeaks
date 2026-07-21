"""Plain-text share copy for daily questions (built in Python, not Jinja)."""

from __future__ import annotations

from flask_babel import _


def _quoted_excerpt(text: str, max_len: int) -> str:
    excerpt = (text or '').strip()
    if len(excerpt) > max_len:
        excerpt = excerpt[: max_len - 1].rstrip() + '…'
    return f'"{excerpt}"'


def build_daily_question_share_text(question_text: str, *, max_len: int = 150) -> str:
    quote = _quoted_excerpt(question_text, max_len)
    return _(
        "%(quote)s — What's your take? Vote in under 2 minutes.",
        quote=quote,
    )


def build_daily_results_share_text(
    question_text: str,
    *,
    total: int,
    agree: int,
    disagree: int,
    unsure: int,
    max_len: int = 120,
) -> str:
    quote = _quoted_excerpt(question_text, max_len)
    stats = _(
        '%(agree)s%% agree · %(disagree)s%% disagree · %(unsure)s%% unsure',
        agree=agree,
        disagree=disagree,
        unsure=unsure,
    )
    return _(
        '%(quote)s — What do you think? %(total)d people have weighed in. %(stats)s',
        quote=quote,
        total=total,
        stats=stats,
    )
