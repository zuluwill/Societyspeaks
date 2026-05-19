"""
Self-serve paid-briefings trial lifecycle helpers.

Shared predicates for scheduler jobs (payment prompt, expire, winback) so
eligibility rules stay in one place and tests don't drift from production.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.lib.time import utcnow_naive

# Days after auto-pause when the day-45 winback email may fire (inclusive).
WINBACK_MIN_DAYS_AFTER_PAUSE = 12
WINBACK_MAX_DAYS_AFTER_PAUSE = 21

# Self-serve trials only have a Personal plan (Block B). Centralise the
# plan/interval combo so the three "add a payment method" CTAs (day-25
# prompt, day-30 pause email, day-45 winback) stay aligned.
_PAYMENT_RESUME_PATH = '/billing/pending-checkout?plan=starter&interval=month'


def payment_resume_url(base_url: str) -> str:
    """Build the canonical "add a payment method / resume" URL.

    Used by every self-serve trial lifecycle email that prompts the user to
    convert. Stripping trailing slash on ``base_url`` keeps the joined URL
    free of double slashes regardless of how the caller resolves the host.
    """
    return f"{base_url.rstrip('/')}{_PAYMENT_RESUME_PATH}"


def paused_self_serve_sub_in_winback_window(
    sub,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Return True when ``sub`` is a self-serve row paused in the winback window.

    Uses ``canceled_at`` (set together with ``paused_at`` by
    ``expire_self_serve_trials_job``) as the timing anchor.
    """
    extra = sub.extra_data or {}
    if sub.status != 'canceled':
        return False
    if extra.get('trial_source') != 'self_serve':
        return False
    if not extra.get('paused_at'):
        return False
    if sub.canceled_at is None:
        return False
    now = now or utcnow_naive()
    age = now - sub.canceled_at
    return timedelta(days=WINBACK_MIN_DAYS_AFTER_PAUSE) <= age <= timedelta(
        days=WINBACK_MAX_DAYS_AFTER_PAUSE
    )


def user_has_later_active_stripe_subscription(user_id: int, *, exclude_sub_id: int) -> bool:
    """True if the user has another Stripe-backed sub in an access-granting status."""
    from app.models.billing import Subscription

    return (
        Subscription.query.filter(
            Subscription.user_id == user_id,
            Subscription.id != exclude_sub_id,
            Subscription.stripe_subscription_id.isnot(None),
            Subscription.status.in_(('trialing', 'active', 'past_due')),
        )
        .first()
        is not None
    )


def self_serve_winback_eligible(sub, *, now: Optional[datetime] = None) -> bool:
    """Whether ``send_self_serve_winback_job`` should email for this subscription."""
    if not paused_self_serve_sub_in_winback_window(sub, now=now):
        return False
    if user_has_later_active_stripe_subscription(sub.user_id, exclude_sub_id=sub.id):
        return False
    return True
