"""Server-side PostHog captures for guided-journey lifecycle events.

Flow-critical events (started / step_completed / completed) are captured on
vote POSTs. Recap GET is an idempotent backup for completed only, and only
when this visitor actually finished — sitemap crawlers must not count.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from flask import current_app, session
from flask_login import current_user
from sqlalchemy import distinct, func

from app import cache, db
from app.lib.participation_metrics import visible_statement_vote_filters
from app.lib.posthog_utils import (
    request_is_prefetch,
    resolve_request_distinct_id,
    safe_posthog_capture,
)
from app.lib.vote_identity import anonymous_fingerprint_aliases_for_daily_lookup
from app.models import Discussion, Programme, Statement, StatementVote

try:
    import posthog as _posthog
except ImportError:
    _posthog = None


def _journey_anon_fallback():
    """Stable anonymous identity shared across journey events for a visitor."""
    import uuid as _uuid

    fp = session.get('statement_vote_fingerprint') or session.get('journey_anon_id')
    if not fp:
        fp = str(_uuid.uuid4())
        session['journey_anon_id'] = fp
        session.modified = True
    return fp


def journey_distinct_id():
    """Canonical PostHog distinct_id for a journey event in this request."""
    if current_user.is_authenticated:
        return str(current_user.id)
    return resolve_request_distinct_id(anon_fallback=_journey_anon_fallback())


def _posthog_ready() -> bool:
    return bool(_posthog and getattr(_posthog, 'project_api_key', None))


def _journey_type(programme: Programme) -> str:
    return 'global' if getattr(programme, 'geographic_scope', 'global') == 'global' else 'country'


def _common_props(programme: Programme, extra: Optional[dict] = None) -> dict:
    props = {
        'journey_id': programme.id,
        'journey_type': _journey_type(programme),
        'journey_slug': programme.slug,
        'journey_name': programme.name,
        'is_authenticated': current_user.is_authenticated,
    }
    if extra:
        props.update(extra)
    return props


def capture_journey_started(programme: Programme, *, total_steps: int) -> None:
    """Fire journey_started once per visitor per programme per 24h (action-gated)."""
    if not _posthog_ready():
        return
    ph_id = journey_distinct_id()
    if not ph_id:
        return
    cache_key = f'ph_journey_started:{programme.id}:{ph_id[:32]}'
    try:
        if cache.get(cache_key):
            return
        sent = safe_posthog_capture(
            posthog_client=_posthog,
            distinct_id=ph_id,
            event='journey_started',
            properties=_common_props(programme, {'total_steps': total_steps}),
            durable=True,
            insert_id=f'journey_started:{programme.id}:{ph_id[:32]}:{date.today().isoformat()}',
        )
        if sent:
            cache.set(cache_key, True, timeout=86400)
    except Exception as exc:
        current_app.logger.warning('PostHog journey_started error: %s', exc)


def capture_journey_completed(programme: Programme, *, is_complete: bool, total_steps: int) -> None:
    """Fire journey_completed only when this visitor finished every theme.

    Recap URLs are in the sitemap; firing on every GET re-inflated completions
    with crawler hits (~30–70/week vs a handful of real voters).
    """
    if not is_complete or request_is_prefetch() or not _posthog_ready():
        return
    ph_id = journey_distinct_id()
    if not ph_id:
        return
    cache_key = f'ph_journey_completed:{programme.id}:{ph_id[:32]}'
    try:
        if cache.get(cache_key):
            return
        sent = safe_posthog_capture(
            posthog_client=_posthog,
            distinct_id=ph_id,
            event='journey_completed',
            properties=_common_props(programme, {'total_steps': total_steps}),
            durable=True,
            insert_id=f'journey_completed:{programme.id}:{ph_id[:32]}',
        )
        if sent:
            cache.set(cache_key, True, timeout=86400 * 30)
    except Exception as exc:
        current_app.logger.warning('PostHog journey_completed error: %s', exc)


def _theme_vote_progress(discussion: Discussion) -> tuple[int, int]:
    """Published (visible-statement) vote count vs statement total for this visitor."""
    vis = visible_statement_vote_filters(Statement)
    total = (
        Statement.query.filter(
            Statement.discussion_id == discussion.id,
            *vis,
        ).count()
    )
    if current_user.is_authenticated:
        voted = (
            db.session.query(func.count(distinct(StatementVote.statement_id)))
            .join(Statement, Statement.id == StatementVote.statement_id)
            .filter(
                StatementVote.discussion_id == discussion.id,
                StatementVote.user_id == current_user.id,
                *vis,
            )
            .scalar()
        ) or 0
    else:
        aliases = anonymous_fingerprint_aliases_for_daily_lookup()
        fps = [fp for fp in aliases if fp]
        if not fps:
            return 0, total
        voted = (
            db.session.query(func.count(distinct(StatementVote.statement_id)))
            .join(Statement, Statement.id == StatementVote.statement_id)
            .filter(
                StatementVote.discussion_id == discussion.id,
                StatementVote.user_id.is_(None),
                StatementVote.session_fingerprint.in_(fps),
                *vis,
            )
            .scalar()
        ) or 0
    return int(voted), int(total)


def capture_journey_vote_events(discussion: Discussion) -> None:
    """On a guided-journey vote: started (24h dedup) and step_completed when done."""
    if not discussion or not discussion.programme_id:
        return
    from app.programmes.journey import (
        is_guided_journey_programme,
        ordered_journey_discussions,
    )

    programme = discussion.programme
    if not programme or not is_guided_journey_programme(programme):
        return
    if not discussion.has_native_statements:
        return

    ordered = ordered_journey_discussions(programme)
    total_steps = len(ordered)
    capture_journey_started(programme, total_steps=total_steps)

    if not _posthog_ready():
        return
    try:
        voted, total = _theme_vote_progress(discussion)
        if total <= 0 or voted < total:
            return
        step_num = next(
            (i + 1 for i, d in enumerate(ordered) if d.id == discussion.id),
            None,
        )
        if step_num is None:
            return
        ph_id = journey_distinct_id()
        if not ph_id:
            return
        cache_key = f'ph_journey_step_completed:{programme.id}:{discussion.id}:{ph_id[:32]}'
        if not cache.get(cache_key):
            sent = safe_posthog_capture(
                posthog_client=_posthog,
                distinct_id=ph_id,
                event='journey_step_completed',
                properties=_common_props(
                    programme,
                    {
                        'step_number': step_num,
                        'step_name': discussion.programme_theme or discussion.slug,
                        'step_type': 'voting',
                        'is_final_step': step_num == total_steps,
                        'total_steps': total_steps,
                    },
                ),
                durable=True,
                insert_id=f'journey_step_completed:{programme.id}:{discussion.id}:{ph_id[:32]}',
            )
            if sent:
                cache.set(cache_key, True, timeout=86400)

        from app.programmes.journey import build_journey_progress

        uid = current_user.id if current_user.is_authenticated else None
        aliases = None if uid else anonymous_fingerprint_aliases_for_daily_lookup()
        progress = build_journey_progress(
            programme,
            uid,
            discussions=ordered,
            anon_fingerprint_aliases=aliases,
        )
        if progress.get('is_journey_complete'):
            capture_journey_completed(
                programme, is_complete=True, total_steps=total_steps
            )
    except Exception as exc:
        current_app.logger.warning('PostHog journey_step_completed error: %s', exc)
