"""
Utility functions for the Daily Questions feature.
These are reusable across routes, email templates, and scheduler jobs.
"""
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
from flask import url_for
from app import db
from flask_babel import gettext as _


def _coerce_daily_question_delivery_prefs(
    email_frequency,
    timezone,
    preferred_send_day,
    preferred_send_hour,
):
    """Normalise frequency, optional IANA timezone, send day (0–6), hour (0–23)."""
    from app.models import DailyQuestionSubscriber

    allowed = DailyQuestionSubscriber.VALID_EMAIL_FREQUENCIES
    if email_frequency not in allowed:
        email_frequency = 'weekly'

    tz_stripped = (timezone or '').strip() if timezone else ''
    tz_out = None
    if tz_stripped:
        try:
            import pytz
            pytz.timezone(tz_stripped)
            tz_out = tz_stripped
        except Exception:
            tz_out = None

    try:
        day = int(preferred_send_day)
    except (TypeError, ValueError):
        day = 1
    if day < 0 or day > 6:
        day = 1

    try:
        hour = int(preferred_send_hour)
    except (TypeError, ValueError):
        hour = 9
    if hour < 0 or hour > 23:
        hour = 9

    return email_frequency, tz_out, day, hour


def format_dq_hour_12h(hour):
    """Format hour 0–23 as '9:00 am' / '12:00 pm' (matches public subscribe labels)."""
    try:
        h = int(hour)
    except (TypeError, ValueError):
        h = 9
    h = max(0, min(23, h))
    if h == 0:
        return '12:00 am'
    if h < 12:
        return f'{h}:00 am'
    if h == 12:
        return '12:00 pm'
    return f'{h - 12}:00 pm'


def daily_question_email_send_window_utc_label():
    """Fixed daily-email UTC time; must match scheduler `daily_question_email` cron."""
    from app.daily.constants import (
        DAILY_QUESTION_EMAIL_SEND_UTC_HOUR,
        DAILY_QUESTION_EMAIL_SEND_UTC_MINUTE,
    )
    h = DAILY_QUESTION_EMAIL_SEND_UTC_HOUR
    m = DAILY_QUESTION_EMAIL_SEND_UTC_MINUTE
    return f'{h}:{m:02d} UTC'


def monthly_digest_schedule_short():
    """Plain-language monthly schedule (must match should_receive_monthly_digest_now)."""
    from app.daily.constants import MONTHLY_DIGEST_DAY_OF_MONTH, MONTHLY_DIGEST_LOCAL_HOUR

    ordinals = {1: '1st', 2: '2nd', 3: '3rd', 21: '21st', 22: '22nd', 23: '23rd', 31: '31st'}
    day = MONTHLY_DIGEST_DAY_OF_MONTH
    ordinal = ordinals.get(day, f'{day}th')
    return f'{ordinal} of each month at {format_dq_hour_12h(MONTHLY_DIGEST_LOCAL_HOUR)} in your time zone'


def build_daily_subscribe_recap(subscriber):
    """
    Build a JSON-friendly recap dict for the subscribe success page (stored in session).
    """
    from app.models import DailyQuestionSubscriber

    if subscriber is None:
        return None
    freq = (subscriber.email_frequency or 'weekly').strip().lower()
    if freq not in DailyQuestionSubscriber.VALID_EMAIL_FREQUENCIES:
        freq = 'weekly'
    tz = (subscriber.timezone or '').strip() or None
    day_name = DailyQuestionSubscriber.SEND_DAYS.get(subscriber.preferred_send_day, 'Tuesday')
    time_12 = format_dq_hour_12h(subscriber.preferred_send_hour)

    recap = {
        'frequency': freq,
        'frequency_label': {'daily': 'Daily', 'weekly': 'Weekly', 'monthly': 'Monthly'}.get(
            freq, freq.title()
        ),
        'timezone': tz,
        'daily_window_label': daily_question_email_send_window_utc_label(),
        'monthly_schedule_short': monthly_digest_schedule_short(),
    }
    if freq == 'weekly':
        recap['weekly_day_name'] = day_name
        recap['weekly_time_label'] = time_12
    return recap


def user_has_active_daily_question_subscription_for_preferences(user):
    """True if a logged-in user can open daily.manage_preferences without a URL token."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    from app.models import DailyQuestionSubscriber
    from sqlalchemy import or_

    return (
        DailyQuestionSubscriber.query.filter(
            or_(
                DailyQuestionSubscriber.user_id == user.id,
                DailyQuestionSubscriber.email == user.email,
            ),
            DailyQuestionSubscriber.is_active.is_(True),
        ).first()
        is not None
    )


def _capture_daily_question_subscribe_posthog(email, subscriber, user, *, track_posthog):
    if not track_posthog:
        return
    try:
        from flask import request
        import posthog

        if not posthog or not getattr(posthog, 'project_api_key', None):
            return
        ref = request.referrer or ''
        props = {
            'subscription_tier': 'free',
            'plan_name': 'Daily Question',
            'email': email,
            'email_frequency': subscriber.email_frequency,
            'timezone': subscriber.timezone or '',
            'preferred_send_day': subscriber.preferred_send_day,
            'preferred_send_hour': subscriber.preferred_send_hour,
            'source': (
                'social'
                if (
                    'utm_source' in ref
                    or any(d in ref for d in ['twitter.com', 'x.com', 'bsky.social'])
                )
                else 'direct'
            ),
            'referrer': request.referrer,
        }
        posthog.capture(
            distinct_id=str(user.id) if user else email,
            event='daily_question_subscribed',
            properties=props,
        )
        posthog.flush()
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f'PostHog tracking error: {e}')


def process_daily_question_subscription(
    email,
    *,
    email_frequency='weekly',
    timezone=None,
    preferred_send_day=None,
    preferred_send_hour=None,
    update_delivery_preferences_on_reactivate=False,
    track_posthog=False,
):
    """Create/reactivate daily question subscriptions in one shared path."""
    from app.models import DailyQuestionSubscriber, User

    fq, tz, day, hr = _coerce_daily_question_delivery_prefs(
        email_frequency, timezone, preferred_send_day, preferred_send_hour
    )

    user = User.query.filter_by(email=email).first()
    existing = DailyQuestionSubscriber.query.filter_by(email=email).first()

    if existing:
        if user and existing.user_id != user.id:
            existing.user_id = user.id
        if existing.is_active:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                from flask import current_app
                current_app.logger.error(f"Failed to persist user_id link for {email}: {e}")
            return {
                'status': 'already_active',
                'subscriber': existing,
                'message': _('This email is already subscribed to daily questions.'),
            }

        existing.is_active = True
        if update_delivery_preferences_on_reactivate:
            existing.email_frequency = fq
            existing.timezone = tz
            existing.preferred_send_day = day
            existing.preferred_send_hour = hr
        existing.generate_magic_token()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            from flask import current_app
            current_app.logger.error(f"Reactivation DB error for {email}: {e}")
            return {
                'status': 'error',
                'subscriber': None,
                'message': _('An error occurred. Please try again.'),
                'error': str(e),
            }
        _capture_daily_question_subscribe_posthog(email, existing, user, track_posthog=track_posthog)
        return {
            'status': 'reactivated',
            'subscriber': existing,
            'message': _('Welcome back! Your subscription has been reactivated.'),
        }

    try:
        subscriber = DailyQuestionSubscriber(
            email=email,
            user_id=user.id if user else None,
            email_frequency=fq,
            timezone=tz,
            preferred_send_day=day,
            preferred_send_hour=hr,
        )
        subscriber.generate_magic_token()
        db.session.add(subscriber)
        db.session.commit()

        from app.resend_client import send_daily_question_welcome_email
        send_daily_question_welcome_email(subscriber)

        _capture_daily_question_subscribe_posthog(email, subscriber, user, track_posthog=track_posthog)

        return {
            'status': 'created',
            'subscriber': subscriber,
            'message': _('You have successfully subscribed to daily civic questions!'),
        }
    except Exception as e:
        db.session.rollback()
        from flask import current_app
        current_app.logger.error(f"Error creating daily subscriber: {e}")
        return {
            'status': 'error',
            'subscriber': None,
            'message': _('There was an error processing your subscription. Please try again.'),
            'error': str(e),
        }


def get_discussion_stats_for_question(question):
    """
    Get discussion statistics for a question's linked discussion.
    This is a user-agnostic version for use in email templates and selection logic.

    Unlike get_discussion_participation_data() in routes.py, this doesn't track
    user-specific vote counts - just general stats for display.

    Args:
        question: DailyQuestion object

    Returns:
        dict: {
            'has_discussion': bool,
            'discussion_id': int | None,
            'discussion_slug': str | None,
            'discussion_title': str | None,
            'participant_count': int,
            'response_count': int,
            'is_active': bool,  # Has activity in last 24h
            'discussion_url': str | None
        }
    """
    from app.models import StatementVote, Statement, Response

    # Default response for questions without discussions
    default_response = {
        'has_discussion': False,
        'discussion_id': None,
        'discussion_slug': None,
        'discussion_title': None,
        'participant_count': 0,
        'response_count': 0,
        'is_active': False,
        'discussion_url': None
    }

    # Null safety checks
    if not question:
        return default_response
    
    if not question.source_discussion_id:
        return default_response

    try:
        discussion = question.source_discussion
        if not discussion:
            return default_response
    except Exception as e:
        # Handle case where relationship fails
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error accessing source_discussion for question {question.id}: {e}")
        return default_response

    # Count participants (authenticated users who voted)
    participant_count = db.session.query(
        db.func.count(db.distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    # Add anonymous participants
    anon_count = db.session.query(
        db.func.count(db.distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0

    participant_count += anon_count

    # Count responses (statements added to discussion)
    response_count = Statement.query.filter_by(
        discussion_id=discussion.id
    ).count()

    # Check if discussion is active (has activity in last 24h)
    yesterday = utcnow_naive() - timedelta(hours=24)
    recent_votes = StatementVote.query.filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.created_at >= yesterday
    ).first()
    is_active = recent_votes is not None

    # Build discussion URL
    try:
        discussion_url = url_for(
            'discussions.view_discussion',
            discussion_id=discussion.id,
            slug=discussion.slug,
            _external=True
        )
    except Exception:
        # Fallback if url_for fails (e.g., outside request context)
        discussion_url = f"/discussions/{discussion.id}/{discussion.slug}"

    return {
        'has_discussion': True,
        'discussion_id': discussion.id,
        'discussion_slug': discussion.slug,
        'discussion_title': discussion.title,
        'participant_count': participant_count,
        'response_count': response_count,
        'is_active': is_active,
        'discussion_url': discussion_url
    }


def get_source_articles_for_question(question, limit=3):
    """
    Get source articles for a question for the "Learn More" section.
    
    This is a wrapper around get_source_articles() for DRY principles.
    Returns NewsArticle objects (same as routes.py version).

    Args:
        question: DailyQuestion object
        limit: Maximum number of articles to return

    Returns:
        list: List of NewsArticle objects (same format as routes.py)
    """
    from app.daily.routes import get_source_articles
    return get_source_articles(question, limit=limit)


def build_question_email_data(question, subscriber, base_url=None):
    """
    Build all the data needed for a question in the weekly digest email.
    DRY helper function used by both email sending and batch page.

    Args:
        question: DailyQuestion object
        subscriber: DailyQuestionSubscriber object
        base_url: Optional base URL (for use outside request context)

    Returns:
        dict: Contains question, discussion_stats, vote_urls, source_articles, question_url
    """
    # Get discussion stats (with error handling)
    try:
        discussion_stats = get_discussion_stats_for_question(question)
    except Exception as e:
        # Log error but continue with default stats
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error getting discussion stats for question {question.id}: {e}")
        discussion_stats = {
            'has_discussion': False,
            'discussion_id': None,
            'discussion_slug': None,
            'discussion_title': None,
            'participant_count': 0,
            'response_count': 0,
            'is_active': False,
            'discussion_url': None
        }

    # Generate vote token and URLs
    vote_token = subscriber.generate_vote_token(question.id)

    if base_url:
        # Use provided base_url (for use outside request context, e.g., email sending)
        vote_urls = {
            'agree': f"{base_url}/daily/v/{vote_token}/agree?q={question.id}&source=weekly_digest",
            'disagree': f"{base_url}/daily/v/{vote_token}/disagree?q={question.id}&source=weekly_digest",
            'unsure': f"{base_url}/daily/v/{vote_token}/unsure?q={question.id}&source=weekly_digest",
        }
        question_url = f"{base_url}/daily/{question.question_date.isoformat()}"
    else:
        # Use url_for (for use within request context)
        try:
            vote_urls = {
                'agree': url_for('daily.one_click_vote',
                               token=vote_token,
                               vote_choice='agree',
                               _external=True) + f'?q={question.id}&source=weekly_digest',
                'disagree': url_for('daily.one_click_vote',
                                  token=vote_token,
                                  vote_choice='disagree',
                                  _external=True) + f'?q={question.id}&source=weekly_digest',
                'unsure': url_for('daily.one_click_vote',
                                token=vote_token,
                                vote_choice='unsure',
                                _external=True) + f'?q={question.id}&source=weekly_digest'
            }
            question_url = url_for('daily.by_date',
                                  date_str=question.question_date.isoformat(),
                                  _external=True)
        except Exception:
            # Fallback if url_for fails
            vote_urls = {
                'agree': f'/daily/v/{vote_token}/agree?q={question.id}&source=weekly_digest',
                'disagree': f'/daily/v/{vote_token}/disagree?q={question.id}&source=weekly_digest',
                'unsure': f'/daily/v/{vote_token}/unsure?q={question.id}&source=weekly_digest'
            }
            question_url = f"/daily/{question.question_date.isoformat()}"

    # Get source articles for learning (returns NewsArticle objects)
    try:
        source_articles = get_source_articles_for_question(question, limit=5)
    except Exception as e:
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error getting source articles for question {question.id}: {e}")
        source_articles = []

    return {
        'question': question,
        'discussion_stats': discussion_stats,
        'vote_urls': vote_urls,
        'source_articles': source_articles,
        'question_url': question_url
    }
