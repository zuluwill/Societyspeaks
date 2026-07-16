"""
E1 stance card context for the daily brief (web + email handoff).

Builds template data for today's published daily question at the end of the brief.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from flask import url_for
from flask_babel import gettext as _, lazy_gettext as _l

from app.models import DailyQuestion


# lazy_gettext so pybabel extracts these literals — a dynamic `_(dict.get(...))`
# is invisible to the extractor and would ship untranslated in all locales.
DOMINANT_FRAME_LABELS = {
    'left': _l('left-leaning outlets'),
    'center': _l('centre outlets'),
    'right': _l('right-leaning outlets'),
    'balanced': _l('mixed outlets'),
}


def _has_user_voted(question: DailyQuestion) -> bool:
    from flask_login import current_user

    from app.models import DailyQuestionResponse
    from app.lib.vote_identity import anonymous_fingerprint_aliases_for_daily_lookup

    if current_user.is_authenticated:
        return DailyQuestionResponse.query.filter_by(
            daily_question_id=question.id,
            user_id=current_user.id,
        ).first() is not None

    fps = anonymous_fingerprint_aliases_for_daily_lookup()
    if not fps:
        return False
    return DailyQuestionResponse.query.filter(
        DailyQuestionResponse.daily_question_id == question.id,
        DailyQuestionResponse.session_fingerprint.in_(fps),
    ).first() is not None


def build_stance_card_context(*, brief_date: Optional[date] = None) -> Optional[dict[str, Any]]:
    """
    Context for components/stance_card.html on today's brief only.

    Returns None when there is no published question for today or the brief is not today.
    """
    today = date.today()
    if brief_date is not None and brief_date != today:
        return None

    question = DailyQuestion.query.filter_by(
        question_date=today,
        status='published',
    ).first()
    if not question:
        return None

    frame = question.coverage_frame_json or {}
    is_brief_sourced = (
        question.source_type == 'brief'
        and bool(question.source_brief_item_id)
        and bool(frame)
    )

    subline = _('Where do you stand?')
    if is_brief_sourced:
        if frame.get('is_underreported'):
            subline = _('Barely covered anywhere. Where do you stand?')
        else:
            dominant = frame.get('dominant_frame') or 'unknown'
            frame_label = DOMINANT_FRAME_LABELS.get(dominant) or _('the press')
            subline = _(
                'The press leaned toward %(frame)s on this story. Where do you stand?',
                frame=frame_label,
            )

    sourcing_brief_url = None
    brief_date_str = frame.get('brief_date')
    if is_brief_sourced and brief_date_str:
        try:
            sourcing_brief_url = url_for('brief.view_date', date_str=brief_date_str)
        except Exception:
            # Any url_for failure (BuildError if the endpoint is ever renamed,
            # RuntimeError outside app context) falls back to the stable path
            # rather than 500-ing the whole brief page.
            sourcing_brief_url = f'/brief/{brief_date_str}'

    show_early_signal = not question.is_cold_start
    vote_pcts = question.vote_percentages if show_early_signal else None

    return {
        'question': question,
        'is_brief_sourced': is_brief_sourced,
        'frame': frame,
        'subline': subline,
        'sourcing_brief_url': sourcing_brief_url,
        'show_early_signal': show_early_signal,
        'vote_pcts': vote_pcts,
        'has_voted': _has_user_voted(question),
        'stance_anchor': 'stance',
        'results_url': url_for(
            'daily.by_date',
            date_str=question.question_date.isoformat(),
        ),
    }


def build_stance_email_handoff(*, brief_date: date, base_url: str) -> Optional[dict[str, Any]]:
    """Minimal context for the single tracked link in daily_brief.html."""
    ctx = build_stance_card_context(brief_date=brief_date)
    if not ctx:
        return None

    date_str = brief_date.isoformat()
    return {
        'question': ctx['question'],
        'stance_url': f"{base_url.rstrip('/')}/brief/{date_str}#stance",
    }
