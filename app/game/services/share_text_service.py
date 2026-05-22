"""Pasteable outcome summary for chat/social sharing (MapTap-style identity card)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask_babel import _, format_date, ngettext

from app.game.constants import DEFAULT_SOCIETY_NAME, STAT_VISIBLE

# Fixed emoji keys — not translated; numbers carry meaning across locales.
_STAT_EMOJI = {
    'prosperity': '📈',
    'trust': '🤝',
    'fairness': '⚖️',
    'stability': '🏛',
}


def _format_played_date(when: Optional[datetime]) -> str:
    if when is None:
        return format_date(date.today(), format='medium')
    day = when.date() if isinstance(when, datetime) else when
    return format_date(day, format='medium')


def _compact_stat_line(visible_stats: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in STAT_VISIBLE:
        value = int(visible_stats.get(key, 0) or 0)
        emoji = _STAT_EMOJI.get(key, '')
        parts.append(f'{value} {emoji}'.strip())
    return '  '.join(parts)


def build_share_text(
    *,
    society_name: str,
    headline: str,
    governance_label: Optional[str],
    scenario_title: str,
    visible_stats: Dict[str, Any],
    trait_chips: Optional[List[str]] = None,
    streak_current: int = 0,
    contradiction_summary: Optional[str] = None,
    share_url: str,
    challenge_url: Optional[str] = None,
    played_at: Optional[datetime] = None,
) -> str:
    """Build a chat-friendly results block: identity, stats, CTA, link."""
    name = (society_name or '').strip() or _(DEFAULT_SOCIETY_NAME)
    lines: List[str] = []

    lines.append(_('Tradeoffs · %(date)s', date=_format_played_date(played_at)))
    lines.append('')
    lines.append(_('⚖️ %(society)s', society=name))
    lines.append('')
    lines.append(f'"{headline.strip()}"')
    lines.append('')

    identity_bits: List[str] = []
    if governance_label:
        identity_bits.append(governance_label.strip())
    if scenario_title:
        identity_bits.append(scenario_title.strip())
    if identity_bits:
        lines.append(' · '.join(identity_bits))

    chips = [c.strip() for c in (trait_chips or []) if c and str(c).strip()]
    if chips:
        lines.append(' · '.join(chips))

    lines.append(_compact_stat_line(visible_stats))

    if streak_current >= 2:
        lines.append(
            '🔥 '
            + ngettext('%(num)d-day streak', '%(num)d-day streak', streak_current)
        )

    if contradiction_summary and contradiction_summary.strip():
        lines.append('')
        lines.append(contradiction_summary.strip())

    lines.append('')
    lines.append(_('What kind of leader would you be?'))
    lines.append(share_url.strip())
    if challenge_url and challenge_url.strip():
        lines.append('')
        lines.append(_('Challenge a friend to the same scenario:'))
        lines.append(challenge_url.strip())

    # Collapse accidental double blanks while preserving paragraph breaks.
    cleaned: List[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank
    return '\n'.join(cleaned).strip() + '\n'
