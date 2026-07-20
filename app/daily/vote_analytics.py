"""PostHog instrumentation for the email one-click vote funnel."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from flask_login import current_user

from app.lib.posthog_utils import (
    email_subscriber_distinct_id,
    request_is_prefetch,
    request_is_scripted_client,
    resolve_request_distinct_id,
    safe_posthog_capture,
)
from app.models import DailyBriefSubscriber, DailyQuestion, DailyQuestionSubscriber

try:
    import posthog as _posthog
except ImportError:
    _posthog = None

VoterChannel = Literal['question', 'brief']
SubscriberT = Union[DailyQuestionSubscriber, DailyBriefSubscriber]


def participation_source_for_email_vote(source: str, voter_channel: VoterChannel) -> str:
    """Normalize ``?source=`` query param into a stable analytics label."""
    if source == 'brief_email' or voter_channel == 'brief':
        return 'brief_stance_email'
    if source == 'weekly_digest':
        return 'weekly_digest_email'
    return 'daily_question_email'


def _distinct_id_for_subscriber(subscriber: SubscriberT) -> Optional[str]:
    return resolve_request_distinct_id(
        user_id=current_user.id if current_user.is_authenticated else None,
        anon_fallback=email_subscriber_distinct_id(subscriber.email),
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

    distinct_id = _distinct_id_for_subscriber(subscriber)
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
    )


def track_email_vote_confirmed(
    *,
    subscriber: SubscriberT,
    question: DailyQuestion,
    vote_choice: str,
    voter_channel: VoterChannel,
    source: str,
    has_reason: bool = False,
    **extra: Any,
) -> None:
    """POST recorded vote — the E1 ≥2% confirmed/delivered numerator."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return

    distinct_id = _distinct_id_for_subscriber(subscriber)
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

    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='email_vote_confirmed',
        properties=base_props,
    )

    # Keep legacy event for existing dashboards; enriched props carry the funnel labels.
    safe_posthog_capture(
        posthog_client=_posthog,
        distinct_id=distinct_id,
        event='daily_question_participated',
        properties=base_props,
    )
