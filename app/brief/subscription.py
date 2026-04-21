"""
Brief subscription service.

Centralises subscription create/reactivate/already-active logic so that
both the public sign-up route and the authenticated dashboard route share
a single code path. Routes should import from here rather than calling
each other.
"""
import logging

from flask import session, request
from app import db
from app.models import DailyBriefSubscriber, User
from app.brief.email_client import ResendClient
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

DEFAULT_SEND_HOUR = 18


def process_subscription(
    email: str,
    timezone: str = 'UTC',
    preferred_hour: int = DEFAULT_SEND_HOUR,
    cadence: str = 'daily',
    preferred_weekly_day: int = 6,
    update_preferences_on_reactivate: bool = True,
    set_session: bool = False,
    track_posthog: bool = False,
    source: str = None,
) -> dict:
    """
    Create or reactivate a Daily Brief subscription.

    Handles three cases:
      - Already active: links user account if needed, returns 'already_active'.
      - Unsubscribed: reactivates and optionally updates preferences, returns 'reactivated'.
      - New: creates record, sends welcome email, returns 'created'.

    Args:
        email: Subscriber email address.
        timezone: Timezone for email delivery (default UTC).
        preferred_hour: Preferred send hour (see VALID_SEND_HOURS in brief/routes.py, default 18).
        cadence: 'daily' or 'weekly' (default 'daily').
        preferred_weekly_day: Day of week for weekly delivery 0=Mon, 6=Sun (default 6).
        update_preferences_on_reactivate: Whether to overwrite tz/hour on reactivation.
        set_session: Whether to set session['brief_subscriber_id'] after subscribe.
        track_posthog: Whether to emit a PostHog event.
        source: Optional source label written to the info log.

    Returns:
        dict with keys:
            status   — 'created' | 'reactivated' | 'already_active' | 'error'
            subscriber — DailyBriefSubscriber instance, or None on error.
            message  — Human-readable description.
            error    — Present only when status == 'error'.
    """
    if cadence not in ('daily', 'weekly'):
        cadence = 'daily'
    if not (0 <= preferred_weekly_day <= 6):
        preferred_weekly_day = 6

    existing = DailyBriefSubscriber.query.filter_by(email=email).first()

    if existing:
        # Link a pre-existing email-only subscriber to their user account when
        # they subscribe from an authenticated surface for the first time.
        user = User.query.filter_by(email=email).first()
        if user and existing.user_id != user.id:
            existing.user_id = user.id

        if existing.status == 'active':
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to persist user_id link for {email}: {e}")
            return {
                'status': 'already_active',
                'subscriber': existing,
                'message': _('This email is already subscribed to the daily brief.'),
            }

        # Reactivate
        existing.status = 'active'
        if update_preferences_on_reactivate:
            existing.timezone = timezone
            existing.preferred_send_hour = preferred_hour
            existing.cadence = cadence
            existing.preferred_weekly_day = preferred_weekly_day
        existing.generate_magic_token()
        existing.grant_free_access()
        existing.welcome_email_sent_at = None
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Reactivation DB error for {email}: {e}")
            return {
                'status': 'error',
                'subscriber': None,
                'message': _('An error occurred. Please try again.'),
                'error': str(e),
            }

        try:
            ResendClient().send_welcome(existing)
        except Exception as e:
            logger.error(f"Failed to send welcome email to {email}: {e}")

        if set_session:
            session['brief_subscriber_id'] = existing.id
            session.modified = True

        return {
            'status': 'reactivated',
            'subscriber': existing,
            'message': _('Welcome back! Your subscription has been reactivated.'),
        }

    # New subscriber
    user = User.query.filter_by(email=email).first()
    try:
        subscriber = DailyBriefSubscriber(
            email=email,
            user_id=user.id if user else None,
            timezone=timezone,
            preferred_send_hour=preferred_hour,
            cadence=cadence,
            preferred_weekly_day=preferred_weekly_day,
        )
        subscriber.generate_magic_token()
        subscriber.grant_free_access()
        db.session.add(subscriber)
        db.session.commit()

        source_str = f" (source: {source})" if source else ""
        logger.info(f"New brief subscriber: {email}{source_str}")

        try:
            ResendClient().send_welcome(subscriber)
        except Exception as e:
            logger.error(f"Failed to send welcome email to {email}: {e}")

        if set_session:
            session['brief_subscriber_id'] = subscriber.id
            session.modified = True

        if track_posthog:
            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    ref = request.referrer or ''
                    posthog.capture(
                        distinct_id=str(user.id) if user else email,
                        event='daily_brief_subscribed',
                        properties={
                            'subscription_tier': 'free',
                            'plan_name': 'Daily Brief',
                            'email': email,
                            'source': 'social' if (
                                'utm_source' in ref or
                                any(d in ref for d in ['twitter.com', 'x.com', 'bsky.social'])
                            ) else 'direct',
                            'referrer': request.referrer,
                            'subscription_type': 'daily_brief',
                        },
                    )
                    posthog.flush()
            except Exception as e:
                logger.warning(f"PostHog tracking error: {e}")

        return {
            'status': 'created',
            'subscriber': subscriber,
            'message': _('Successfully subscribed! Check your email for the first brief.'),
        }

    except Exception as e:
        db.session.rollback()
        logger.error(f"Subscription error for {email}: {e}")
        return {
            'status': 'error',
            'subscriber': None,
            'message': _('An error occurred. Please try again.'),
            'error': str(e),
        }
