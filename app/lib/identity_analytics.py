"""Canonical identity / acquisition analytics.

Every account birth and every first email verification must go through these
helpers so PostHog acquisition dashboards stay path-agnostic.

Product-specific funnel events (``paid_briefing_trial_*``, checkout, etc.) are
additive and live at their call sites — they do not replace identity events.

``signup_method`` / ``verification_method`` are the dimensions used to break
down conversion paths in insights. Keep the vocabulary below stable.
"""
from __future__ import annotations

from typing import Any, Optional

from app.analytics.events import record_event
from app.lib.posthog_utils import safe_posthog_capture

# Stable vocab — do not rename without updating PostHog insights / dashboards.
SIGNUP_METHOD_REGISTER = 'register'
SIGNUP_METHOD_TRIAL_MAGIC_LINK = 'trial_magic_link'
SIGNUP_METHOD_ADMIN = 'admin'

VERIFICATION_METHOD_EMAIL_LINK = 'email_link'
VERIFICATION_METHOD_MAGIC_LINK = 'magic_link'


def _posthog_client(override: Any = None):
    if override is not None:
        return override
    try:
        import posthog
        return posthog
    except ImportError:
        return None


def track_user_signed_up(
    user,
    *,
    signup_method: str,
    properties: Optional[dict] = None,
    source: str = 'web',
    posthog_client: Any = None,
    record_internal: bool = True,
) -> None:
    """Fire ``user_signed_up`` (+ optional internal ``account_created``).

    Call only when a *new* User row was just created — never for returning
    find-or-create hits.
    """
    if user is None or not getattr(user, 'id', None):
        return

    props = {
        'signup_method': signup_method,
        'username': getattr(user, 'username', None),
        **(properties or {}),
    }

    if record_internal:
        record_event(
            'account_created',
            user_id=user.id,
            source=source,
            event_metadata={
                'username': getattr(user, 'username', None),
                'signup_method': signup_method,
            },
        )

    safe_posthog_capture(
        posthog_client=_posthog_client(posthog_client),
        distinct_id=str(user.id),
        event='user_signed_up',
        properties=props,
        identify_properties={
            'email': getattr(user, 'email', None),
            'username': getattr(user, 'username', None),
            'signup_method': signup_method,
        },
        insert_id=f'user_signed_up:{user.id}',
        durable=True,
    )


def track_email_verified(
    user,
    *,
    verification_method: str,
    properties: Optional[dict] = None,
    posthog_client: Any = None,
) -> None:
    """Fire ``email_verified`` after a False→True transition has been committed.

    Callers must only invoke this when the account actually became verified
    on this request (not on every login).
    """
    if user is None or not getattr(user, 'id', None):
        return

    props = {
        'user_id': user.id,
        'verification_method': verification_method,
        **(properties or {}),
    }
    safe_posthog_capture(
        posthog_client=_posthog_client(posthog_client),
        distinct_id=str(user.id),
        event='email_verified',
        properties=props,
        insert_id=f'email_verified:{user.id}',
        durable=True,
    )
