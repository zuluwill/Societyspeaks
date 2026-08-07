"""
E1 stance card context for the daily brief (web + email handoff).

Pairs a brief edition with the live published daily question that belongs with it.
Brief D wires the question for D+1 (see ``wire_tomorrow_question_from_brief``);
morning local-hour sends deliver brief D-1 on day D when that companion is live.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from flask import has_request_context, url_for
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


def _safe_daily_results_url(question_date: date) -> str:
    """Relative daily permalink; falls back when url_for cannot run."""
    date_str = question_date.isoformat()
    try:
        # _external=False: with SERVER_NAME set (tests) and no request, the
        # default url_for builds an absolute URL which breaks template/assert
        # expectations that want a path.
        return url_for('daily.by_date', date_str=date_str, _external=False)
    except Exception:
        return f'/daily/{date_str}'


def _published_question_for_brief(*, brief_date: Optional[date] = None) -> Optional[DailyQuestion]:
    """
    Published daily question paired with this brief edition.

    Always returns today's live question (or None) so the web vote form — which
    posts to ``DailyQuestion.get_today()`` — cannot diverge from the card copy.

    Resolution (send window only: brief date is today or yesterday):

    1. Prefer the question wired *from* this brief when that question is today's
       (``question_date == brief_date + 1 == today``). This is the morning-wave
       path: London 08:10 on day D receives brief D-1 with day's D question.
    2. Else, for today's brief edition, today's published question (evening wave
       after 18:00 UTC publish, when tomorrow's wired question is still scheduled).
    """
    today = date.today()
    if brief_date is None:
        brief_date = today

    # Archive / future editions: no CTA. Morning delivery of yesterday's edition
    # and same-day evening delivery are the only live windows.
    if brief_date not in (today, today - timedelta(days=1)):
        return None

    companion_date = brief_date + timedelta(days=1)
    if companion_date == today:
        companion = DailyQuestion.query.filter_by(
            question_date=today,
            status='published',
        ).first()
        if companion is not None:
            frame = companion.coverage_frame_json or {}
            frame_brief = frame.get('brief_date')
            # Accept discussion-sourced companions (no frame) and brief-sourced
            # ones that point back at this edition. Reject mis-wired frames.
            if not frame_brief or frame_brief == brief_date.isoformat():
                return companion

    if brief_date == today:
        return DailyQuestion.query.filter_by(
            question_date=today,
            status='published',
        ).first()

    return None


def _stance_subline(question: DailyQuestion) -> str:
    """Framing line for web stance card and brief email handoff."""
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
    return subline


def _has_user_voted(question: DailyQuestion) -> bool:
    """
    Whether the current visitor has already voted on this question.

    Safe outside a request context (scheduler / email render): returns False
    rather than touching flask_login's current_user proxy, which is None when
    there is no request.
    """
    if not has_request_context():
        return False

    from flask_login import current_user

    from app.models import DailyQuestionResponse
    from app.lib.vote_identity import anonymous_fingerprint_aliases_for_daily_lookup

    try:
        authenticated = bool(current_user.is_authenticated)
    except (AttributeError, RuntimeError):
        # LocalProxy unbound / None outside a proper login request context.
        return False

    if authenticated:
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
    Context for components/stance_card.html on a live brief edition.

    Returns None outside the today/yesterday send window or when there is no
    published question for today.
    """
    question = _published_question_for_brief(brief_date=brief_date)
    if not question:
        return None

    frame = question.coverage_frame_json or {}
    is_brief_sourced = (
        question.source_type == 'brief'
        and bool(question.source_brief_item_id)
        and bool(frame)
    )

    subline = _stance_subline(question)

    sourcing_brief_url = None
    brief_date_str = frame.get('brief_date')
    if is_brief_sourced and brief_date_str:
        try:
            sourcing_brief_url = url_for(
                'brief.view_date', date_str=brief_date_str, _external=False,
            )
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
        # Match sourcing_brief_url: never 500 the brief when url_for cannot
        # run (no request context / SERVER_NAME — e.g. some unit tests).
        'results_url': _safe_daily_results_url(question.question_date),
    }


def build_stance_email_handoff(
    *,
    brief_date: date,
    base_url: str,
    subscriber: Any = None,
) -> Optional[dict[str, Any]]:
    """
    Context for the stance card in daily_brief.html.

    Must not touch flask_login / request-bound vote state — email renders run
    on the scheduler without a request context.

    When ``subscriber`` is provided, includes one-click vote URLs (same
    GET-confirm / POST-record flow as the standalone daily question email).

    ``src=brief_stance`` is a query param (not only a hash) so Resend click
    tracking can attribute the web fallback CTA; ``#stance`` scrolls the card.
    """
    question = _published_question_for_brief(brief_date=brief_date)
    if not question:
        return None

    root = base_url.rstrip('/')
    date_str = brief_date.isoformat()
    show_early_signal = not question.is_cold_start
    vote_pcts = question.vote_percentages if show_early_signal else None

    handoff: dict[str, Any] = {
        'question': question,
        'subline': _stance_subline(question),
        'show_early_signal': show_early_signal,
        'vote_pcts': vote_pcts,
        # Web fallback when the reader wants context or to add a reason.
        'stance_url': f"{root}/brief/{date_str}?src=brief_stance#stance",
        'tradeoffs_url': f"{root}/play/daily?src=brief_tradeoffs",
        'show_first_timer_hint': (
            subscriber is not None and (subscriber.total_briefs_received or 0) == 0
        ),
    }

    if subscriber is not None:
        vote_token = subscriber.generate_vote_token(question.id)
        vote_qs = '?source=brief_email'
        handoff['vote_agree_url'] = f"{root}/daily/v/{vote_token}/agree{vote_qs}"
        handoff['vote_disagree_url'] = f"{root}/daily/v/{vote_token}/disagree{vote_qs}"
        handoff['vote_unsure_url'] = f"{root}/daily/v/{vote_token}/unsure{vote_qs}"

    handoff['tradeoffs'] = _tradeoffs_daily_context()

    return handoff


def build_weekly_stance_card_context(
    *,
    week_start: date,
    week_end: date,
) -> Optional[dict[str, Any]]:
    """
    Context for components/stance_card.html on a published weekly brief edition.

    Picks the week's highest-scored published question (same ranker as the
    Tuesday weekly question digest, scoped to the edition's calendar week).
    """
    from app.daily.question_digest_selection import select_best_question_for_week

    question = select_best_question_for_week(week_start, week_end)
    if not question:
        return None

    frame = question.coverage_frame_json or {}
    is_brief_sourced = (
        question.source_type == 'brief'
        and bool(question.source_brief_item_id)
        and bool(frame)
    )

    subline = _("This week's most debated question — where do you stand?")
    if is_brief_sourced:
        subline = _stance_subline(question)

    show_early_signal = not question.is_cold_start
    vote_pcts = question.vote_percentages if show_early_signal else None

    return {
        'question': question,
        'is_brief_sourced': is_brief_sourced,
        'frame': frame,
        'subline': subline,
        'sourcing_brief_url': None,
        'show_early_signal': show_early_signal,
        'vote_pcts': vote_pcts,
        'has_voted': _has_user_voted(question),
        'stance_anchor': 'stance',
        # The shared card defaults to "Daily Question #N", which is wrong on a
        # page headed "The Weekly Brief" covering a whole week.
        'kicker': _("This week's question"),
        'results_url': _safe_daily_results_url(question.question_date),
    }


def build_weekly_stance_email_handoff(
    *,
    week_start: date,
    week_end: date,
    week_end_date: date,
    base_url: str,
    subscriber: Any = None,
) -> Optional[dict[str, Any]]:
    """
    Context for the stance card block in weekly brief emails.

    Uses the same week-scoped question ranker as the web weekly edition.
    """
    from app.daily.question_digest_selection import select_best_question_for_week

    question = select_best_question_for_week(week_start, week_end)
    if not question:
        return None

    root = base_url.rstrip('/')
    date_str = week_end_date.isoformat()
    show_early_signal = not question.is_cold_start
    vote_pcts = question.vote_percentages if show_early_signal else None

    handoff: dict[str, Any] = {
        'question': question,
        'subline': _("This week's most debated question — where do you stand?"),
        # Overrides the daily email's "Today's question" kicker, which misreads
        # on an edition covering the whole week.
        'kicker': _("This week's question"),
        'show_early_signal': show_early_signal,
        'vote_pcts': vote_pcts,
        'stance_url': f"{root}/brief/weekly/{date_str}?src=weekly_brief_stance#stance",
        'tradeoffs_url': f"{root}/play/daily?src=weekly_brief_tradeoffs",
        'show_first_timer_hint': (
            subscriber is not None and (subscriber.total_briefs_received or 0) == 0
        ),
    }

    if subscriber is not None:
        vote_token = subscriber.generate_vote_token(question.id)
        vote_qs = '?source=weekly_brief_email'
        handoff['vote_agree_url'] = f"{root}/daily/v/{vote_token}/agree{vote_qs}"
        handoff['vote_disagree_url'] = f"{root}/daily/v/{vote_token}/disagree{vote_qs}"
        handoff['vote_unsure_url'] = f"{root}/daily/v/{vote_token}/unsure{vote_qs}"

    handoff['tradeoffs'] = _tradeoffs_daily_context()

    return handoff


def _tradeoffs_daily_context() -> Optional[dict[str, Any]]:
    """Today's Tradeoffs scenario metadata (shared by the brief email + web card)."""
    from flask import current_app

    if not current_app.config.get('GAME_ENABLED', True):
        return None
    try:
        from app.game.services.daily_service import daily_meta

        meta = daily_meta()
        return {
            'title': meta.get('title') or '',
            'category': meta.get('category') or '',
            'teaser': meta.get('teaser') or '',
            'total_turns': meta.get('total_turns') or 5,
        }
    except Exception:
        return None


def build_tradeoffs_card_context() -> Optional[dict[str, Any]]:
    """Context for the web brief's Tradeoffs promo card (components/stance_tradeoffs_card.html).

    Returns None when the game is disabled or today's scenario can't be loaded, so
    the brief page silently falls back to no card rather than erroring. Includes the
    live scenario (title / category / teaser), turn count, a source-tagged play URL,
    and cached participation stats for social proof when they're worth showing.
    """
    meta = _tradeoffs_daily_context()
    if meta is None:
        return None

    try:
        play_url = url_for('game.daily', src='brief_tradeoffs', _external=False)
    except Exception:
        play_url = '/play/daily?src=brief_tradeoffs'

    participation = None
    try:
        from app.game.services.stats_service import participation_stats

        stats = participation_stats()
        if stats.get('show'):
            participation = stats
    except Exception:
        participation = None

    return {**meta, 'play_url': play_url, 'participation': participation}
