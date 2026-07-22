"""PostHog instrumentation for daily-question participation and email vote funnels."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional, Union

from flask_login import current_user

from app.lib.posthog_utils import (
    email_subscriber_distinct_id,
    request_is_prefetch,
    request_is_scripted_client,
    resolve_request_distinct_id,
    safe_posthog_capture,
    stitch_email_subscriber_posthog_identity,
    stitch_posthog_on_user_login,
)
from app.lib.time import utcnow_naive
from app.lib.vote_identity import get_voter_fingerprint
from app.models import DailyBriefSubscriber, DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber

try:
    import posthog as _posthog
except ImportError:
    _posthog = None

_log = logging.getLogger(__name__)

VoterChannel = Literal['question', 'brief']
SubscriberT = Union[DailyQuestionSubscriber, DailyBriefSubscriber]


def participation_source_for_email_vote(source: str, voter_channel: VoterChannel) -> str:
    """Normalize ``?source=`` query param into a stable analytics label."""
    if source == 'brief_email' or voter_channel == 'brief':
        return 'brief_stance_email'
    if source == 'weekly_digest':
        return 'weekly_digest_email'
    return 'daily_question_email'


_VOTE_LABELS = {1: 'agree', -1: 'disagree', 0: 'unsure'}


def question_analytics_properties(question: DailyQuestion) -> dict[str, Any]:
    """Rich, human-readable question metadata for PostHog breakdowns and dashboards."""
    props: dict[str, Any] = {
        'question_id': question.id,
        'question_number': question.question_number,
        'question_text': question.question_text,
        'question_date': question.question_date.isoformat() if question.question_date else None,
        'source_type': question.source_type,
        'topic_category': question.topic_category,
        'contestability_score': question.contestability_score,
        'editorial_contest_rating': question.editorial_contest_rating,
    }
    try:
        discussion = question.source_discussion
        if discussion is not None:
            props['discussion_id'] = discussion.id
            title = getattr(discussion, 'title', None) or getattr(discussion, 'question', None)
            if title:
                props['discussion_title'] = str(title)[:200]
    except Exception:
        pass
    try:
        topic = question.source_trending_topic
        if topic is not None:
            props['trending_topic_id'] = topic.id
            if getattr(topic, 'title', None):
                props['trending_topic_title'] = str(topic.title)[:200]
            if getattr(topic, 'geographic_scope', None):
                props['question_geographic_scope'] = topic.geographic_scope
    except Exception:
        pass
    return {key: value for key, value in props.items() if value is not None and value != ''}


def vote_choice_label(vote_value: Any) -> str:
    """Map numeric vote or string choice to a stable analytics label."""
    if isinstance(vote_value, str):
        return vote_value
    try:
        return _VOTE_LABELS.get(int(vote_value), str(vote_value))
    except (TypeError, ValueError):
        return str(vote_value)


def mark_posthog_confirmed_mirrored(response_id: int) -> None:
    """Stamp audit column after a durable PostHog mirror of an email-confirmed vote."""
    try:
        from app import db

        row = db.session.get(DailyQuestionResponse, response_id)
        if row is None:
            return
        row.posthog_confirmed_mirrored_at = utcnow_naive()
        db.session.commit()
    except Exception as exc:
        from app import db

        db.session.rollback()
        _log.warning(
            'Failed to stamp posthog_confirmed_mirrored_at for response %s: %s',
            response_id,
            exc,
        )


def subscriber_for_analytics(
    subscriber: Optional[SubscriberT] = None,
) -> Optional[SubscriberT]:
    """Resolve the email subscriber tied to this request, if any.

    Checks explicit argument, Flask session keys, then the signed ``ss_subref``
    cookie (survives session expiry — see ``subscriber_identity``).
    """
    if subscriber is not None and getattr(subscriber, 'email', None):
        return subscriber
    try:
        from flask import session

        from app import db
        from app.lib.subscriber_identity import read_subscriber_ref

        for key, model in (
            ('brief_subscriber_id', DailyBriefSubscriber),
            ('daily_subscriber_id', DailyQuestionSubscriber),
        ):
            sub_id = session.get(key)
            if not sub_id:
                continue
            sub = db.session.get(model, sub_id)
            if sub and sub.email:
                return sub

        ref = read_subscriber_ref()
        if ref:
            if ref.get('b'):
                sub = db.session.get(DailyBriefSubscriber, ref['b'])
                if sub and sub.email:
                    return sub
            if ref.get('q'):
                sub = db.session.get(DailyQuestionSubscriber, ref['q'])
                if sub and sub.email:
                    return sub
    except Exception as exc:
        _log.warning("Failed to resolve subscriber for analytics: %s", exc)
    return None


def resolve_daily_participation_distinct_id(
    subscriber: Optional[SubscriberT] = None,
) -> Optional[str]:
    """Stable PostHog ``distinct_id`` for daily-question participation events.

    Prefer authenticated ``user_id``, then the browser PostHog cookie (via
    :func:`resolve_request_distinct_id`), then a durable anonymous fallback:
    email-subscriber hash when the visitor arrived via email, else the unified
    voter fingerprint.

    For the email confirm funnel, use :func:`resolve_email_vote_distinct_id`
    instead — it always prefers the subscriber hash for anonymous visitors.
    """
    if current_user.is_authenticated:
        return resolve_request_distinct_id(user_id=current_user.id)

    resolved = subscriber_for_analytics(subscriber)
    email_fallback = (
        email_subscriber_distinct_id(resolved.email)
        if resolved and resolved.email
        else None
    )

    fingerprint: Optional[str] = None
    try:
        fingerprint = get_voter_fingerprint()
    except Exception:
        pass

    return resolve_request_distinct_id(
        anon_fallback=email_fallback or fingerprint,
    )


def resolve_email_vote_distinct_id(subscriber: SubscriberT) -> Optional[str]:
    """Canonical PostHog ``distinct_id`` for email vote funnel events.

    Anonymous email voters must always resolve to ``subscriber:<hash>`` so
    confirm-viewed and confirmed events stitch to the same person across
    devices and sessions. Logged-in voters still use ``str(user_id)``.
    """
    if current_user.is_authenticated:
        return resolve_request_distinct_id(user_id=current_user.id)
    return email_subscriber_distinct_id(getattr(subscriber, 'email', None))


def email_vote_identify_properties(
    subscriber: SubscriberT,
    voter_channel: VoterChannel,
) -> dict[str, Any]:
    """Non-PII person properties for email vote funnel identify calls."""
    props: dict[str, Any] = {}
    if voter_channel == 'brief':
        props['brief_subscriber_id'] = subscriber.id
    else:
        props['daily_subscriber_id'] = subscriber.id
    cohort = getattr(subscriber, 'source', None)
    if cohort:
        props['subscriber_cohort'] = cohort
    cadence = getattr(subscriber, 'cadence', None)
    if cadence:
        props['subscriber_cadence'] = cadence
    tier = getattr(subscriber, 'tier', None)
    if tier:
        props['subscriber_tier'] = tier
    return props


def track_subscriber_login(
    user,
    *,
    subscriber_email: Optional[str],
    source: str,
) -> None:
    """Post-login PostHog stitch for subscriber magic-link paths."""
    stitch_posthog_on_user_login(
        user,
        subscriber_email=subscriber_email,
        properties={'method': 'magic_link', 'source': source},
    )


def track_daily_question_participated(
    *,
    question: DailyQuestion,
    vote: str,
    participation_source: str,
    subscriber: Optional[SubscriberT] = None,
    voted_via_email: bool = False,
    has_reason: bool = False,
    distinct_id_override: Optional[str] = None,
    identify_properties: Optional[dict[str, Any]] = None,
    **extra: Any,
) -> None:
    """Record ``daily_question_participated`` for web, batch, and other vote paths."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return

    resolved_subscriber = subscriber_for_analytics(subscriber)
    distinct_id = distinct_id_override or resolve_daily_participation_distinct_id(
        subscriber=resolved_subscriber
    )
    if not distinct_id:
        _log.warning(
            "Skipping daily_question_participated — no distinct_id "
            "(question_id=%s, participation_source=%s)",
            question.id,
            participation_source,
        )
        return

    props = {
        **question_analytics_properties(question),
        'vote': vote,
        'vote_choice': vote_choice_label(vote),
        'participation_source': participation_source,
        'has_reason': has_reason,
        'voted_via_email': voted_via_email,
        'is_authenticated': bool(current_user.is_authenticated),
    }
    props.update(extra)

    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='daily_question_participated',
        properties=props,
        identify_properties=identify_properties,
    )


def track_email_vote_confirm_viewed(
    *,
    subscriber: SubscriberT,
    question: DailyQuestion,
    vote_choice: str,
    voter_channel: VoterChannel,
    source: str,
) -> None:
    """GET confirm page — separates email clicks from confirmed votes.

    Fires on a bare GET, which is exactly what mail scanners and link
    prefetchers hit (the two-step confirm flow exists to stop them *voting*).
    Skip those so ``email_vote_confirm_viewed`` stays a human signal and the
    click → confirm-viewed → confirmed funnel isn't inflated by prefetch noise.
    Only the terminal POST ``email_vote_confirmed`` is the E1 numerator, so it
    is never gated; this GET step must not be gated more aggressively than that
    POST or the funnel could read confirmed > viewed.
    """
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return

    if request_is_prefetch() or request_is_scripted_client():
        return

    distinct_id = resolve_email_vote_distinct_id(subscriber)
    if not distinct_id:
        _log.warning(
            "Skipping email_vote_confirm_viewed — no distinct_id "
            "(question_id=%s, subscriber=%s)",
            question.id,
            getattr(subscriber, 'id', None),
        )
        return

    stitch_email_subscriber_posthog_identity(getattr(subscriber, 'email', None))
    identify_props = email_vote_identify_properties(subscriber, voter_channel)
    participation_source = participation_source_for_email_vote(source, voter_channel)

    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='email_vote_confirm_viewed',
        properties={
            **question_analytics_properties(question),
            'vote_choice': vote_choice_label(vote_choice),
            'voter_channel': voter_channel,
            'source': source or 'email',
            'participation_source': participation_source,
        },
        identify_properties=identify_props,
    )


def track_email_vote_confirmed(
    *,
    subscriber: SubscriberT,
    question: DailyQuestion,
    vote_choice: str,
    voter_channel: VoterChannel,
    source: str,
    has_reason: bool = False,
    distinct_id_override: Optional[str] = None,
    response_id: Optional[int] = None,
    **extra: Any,
) -> None:
    """POST recorded vote — the E1 ≥2% confirmed/delivered numerator."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return

    distinct_id = distinct_id_override or resolve_email_vote_distinct_id(subscriber)
    identify_props = email_vote_identify_properties(subscriber, voter_channel)
    participation_source = participation_source_for_email_vote(source, voter_channel)
    vote_label = vote_choice_label(vote_choice)

    base_props = {
        **question_analytics_properties(question),
        'vote': vote_label,
        'vote_choice': vote_label,
        'voter_channel': voter_channel,
        'source': source or 'email',
        'participation_source': participation_source,
        'confirmation_step': 'confirmed',
        'has_reason': has_reason,
        'voted_via_email': True,
        'is_authenticated': bool(current_user.is_authenticated),
    }
    if response_id is not None:
        base_props['response_id'] = response_id
    base_props.update(extra)

    if not distinct_id:
        _log.warning(
            "Skipping email_vote_confirmed — no distinct_id "
            "(question_id=%s, subscriber=%s)",
            question.id,
            getattr(subscriber, 'id', None),
        )
        return

    insert_id = f'dqr:{response_id}:email_vote_confirmed' if response_id else None

    # Best-effort enqueue only — never block the confirm POST (see posthog_utils
    # doctrine). ``posthog_confirmed_mirrored_at`` is stamped exclusively by
    # :func:`reconcile_unmirrored_email_votes_to_posthog` so loss cannot hide
    # behind a premature audit flag.
    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='email_vote_confirmed',
        properties=base_props,
        identify_properties=identify_props,
        insert_id=insert_id,
    )

    # Keep legacy event for existing dashboards; enriched props carry the funnel labels.
    track_daily_question_participated(
        question=question,
        vote=vote_label,
        participation_source=participation_source,
        subscriber=subscriber,
        voted_via_email=True,
        has_reason=has_reason,
        distinct_id_override=distinct_id,
        identify_properties=identify_props,
        voter_channel=voter_channel,
        source=source or 'email',
        confirmation_step='confirmed',
        response_id=response_id,
        **extra,
    )


def mirror_email_vote_confirmed_to_posthog(
    response: DailyQuestionResponse,
    *,
    subscriber: Optional[SubscriberT] = None,
    voter_channel: VoterChannel = 'brief',
    source: str = 'brief_email',
) -> bool:
    """Idempotent backfill of ``email_vote_confirmed`` from a stored response row."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return False
    if not response.voted_via_email:
        return False
    if response.posthog_confirmed_mirrored_at is not None:
        return False

    question = response.daily_question
    if question is None:
        return False

    distinct_id = response.posthog_distinct_id
    if not distinct_id and subscriber is not None:
        distinct_id = resolve_email_vote_distinct_id(subscriber)
    if not distinct_id:
        _log.warning(
            'Skipping mirror for response %s — no distinct_id',
            response.id,
        )
        return False

    vote_label = vote_choice_label(response.vote)
    participation_source = participation_source_for_email_vote(source, voter_channel)
    props = {
        **question_analytics_properties(question),
        'vote': vote_label,
        'vote_choice': vote_label,
        'voter_channel': voter_channel,
        'source': source or 'email',
        'participation_source': participation_source,
        'confirmation_step': 'confirmed',
        'has_reason': bool(response.reason),
        'voted_via_email': True,
        'response_id': response.id,
        'mirrored_from_db': True,
    }
    identify_props = (
        email_vote_identify_properties(subscriber, voter_channel) if subscriber else None
    )

    captured = safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='email_vote_confirmed',
        properties=props,
        identify_properties=identify_props,
        insert_id=f'dqr:{response.id}:email_vote_confirmed',
        durable=True,
    )
    if captured:
        mark_posthog_confirmed_mirrored(response.id)
    return captured


def reconcile_unmirrored_email_votes_to_posthog(
    *,
    days: int = 30,
    limit: int = 500,
) -> dict[str, int]:
    """Reconcile Neon email-confirmed votes into PostHog.

    Sole writer of ``posthog_confirmed_mirrored_at``. Live vote POSTs enqueue
    best-effort events with deterministic ``$insert_id``; this job re-sends any
    row still unstamped (PostHog dedupes duplicates) and stamps only what it
    processes. Runs out-of-band so vote latency is never taxed.
    """
    from datetime import timedelta

    from app.models import DailyBriefSubscriber

    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return {'candidates': 0, 'mirrored': 0, 'skipped_no_identity': 0, 'failed': 0}

    cutoff = utcnow_naive() - timedelta(days=days)
    rows = (
        DailyQuestionResponse.query.filter(
            DailyQuestionResponse.voted_via_email.is_(True),
            DailyQuestionResponse.posthog_confirmed_mirrored_at.is_(None),
            DailyQuestionResponse.created_at >= cutoff,
        )
        .order_by(DailyQuestionResponse.created_at.asc())
        .limit(limit)
        .all()
    )
    if not rows:
        return {'candidates': 0, 'mirrored': 0, 'skipped_no_identity': 0, 'failed': 0}

    subscriber_index: dict[str, DailyBriefSubscriber] = {}
    for sub in DailyBriefSubscriber.query.filter(DailyBriefSubscriber.email.isnot(None)).all():
        did = email_subscriber_distinct_id(sub.email)
        if did:
            subscriber_index[did] = sub

    mirrored = 0
    skipped_no_identity = 0
    failed = 0
    for response in rows:
        if not response.posthog_distinct_id:
            skipped_no_identity += 1
            continue
        subscriber = subscriber_index.get(response.posthog_distinct_id)
        if mirror_email_vote_confirmed_to_posthog(
            response,
            subscriber=subscriber,
            voter_channel='brief',
            source='brief_email',
        ):
            mirrored += 1
        else:
            failed += 1

    # NB: do NOT shutdown/flush the shared PostHog client here — this runs in the
    # long-lived scheduler process (every 15 min) and shutting the client down
    # would kill delivery of every other server event (brief sends, digests,
    # social posts) for the rest of the worker's life. Per-row ``durable=True``
    # already drains the queue non-destructively; the manual backfill relies on
    # the process atexit drain registered by create_app.
    _log.info(
        'PostHog stance mirror reconcile: candidates=%d mirrored=%d '
        'skipped_no_identity=%d failed=%d',
        len(rows),
        mirrored,
        skipped_no_identity,
        failed,
    )
    return {
        'candidates': len(rows),
        'mirrored': mirrored,
        'skipped_no_identity': skipped_no_identity,
        'failed': failed,
    }
