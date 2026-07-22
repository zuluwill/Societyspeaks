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
from app.lib.vote_identity import get_voter_fingerprint
from app.models import DailyBriefSubscriber, DailyQuestion, DailyQuestionSubscriber

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
        'question_id': question.id,
        'question_number': question.question_number,
        'question_text': question.question_text,
        'vote': vote,
        'vote_choice': vote,
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
            'question_id': question.id,
            'question_number': question.question_number,
            'vote_choice': vote_choice,
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
    **extra: Any,
) -> None:
    """POST recorded vote — the E1 ≥2% confirmed/delivered numerator."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return

    distinct_id = distinct_id_override or resolve_email_vote_distinct_id(subscriber)
    identify_props = email_vote_identify_properties(subscriber, voter_channel)
    participation_source = participation_source_for_email_vote(source, voter_channel)

    base_props = {
        'question_id': question.id,
        'question_number': question.question_number,
        'question_text': question.question_text,
        'vote': vote_choice,
        'vote_choice': vote_choice,
        'voter_channel': voter_channel,
        'source': source or 'email',
        'participation_source': participation_source,
        'confirmation_step': 'confirmed',
        'has_reason': has_reason,
        'voted_via_email': True,
        'is_authenticated': bool(current_user.is_authenticated),
    }
    base_props.update(extra)

    if not distinct_id:
        _log.warning(
            "Skipping email_vote_confirmed — no distinct_id "
            "(question_id=%s, subscriber=%s)",
            question.id,
            getattr(subscriber, 'id', None),
        )
        return

    # The cookie→subscriber-hash alias already fired on the confirm-viewed GET
    # that always precedes this POST; PostHog aliasing is one-shot per pair, so
    # we do not repeat it here. This event attributes to subscriber:<hash>
    # directly via ``distinct_id`` regardless, and ``identify_properties`` keep
    # the person profile current.
    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='email_vote_confirmed',
        properties=base_props,
        identify_properties=identify_props,
    )

    # Keep legacy event for existing dashboards; enriched props carry the funnel labels.
    track_daily_question_participated(
        question=question,
        vote=vote_choice,
        participation_source=participation_source,
        subscriber=subscriber,
        voted_via_email=True,
        has_reason=has_reason,
        distinct_id_override=distinct_id,
        identify_properties=identify_props,
        voter_channel=voter_channel,
        source=source or 'email',
        confirmation_step='confirmed',
        **extra,
    )
