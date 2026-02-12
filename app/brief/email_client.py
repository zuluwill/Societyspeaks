"""
Resend Email Client for Daily Brief

Handles email delivery via Resend API with timezone support.
"""

import os
import time
import requests
import threading
import logging
import pytz
from datetime import datetime
from email.utils import parseaddr
from typing import List, Optional
from flask import render_template, current_app
from app.models import DailyBrief, DailyBriefSubscriber, BriefItem, db
from app.brief.sections import SECTIONS, TOPIC_DISPLAY_LABELS, TOPIC_DISPLAY_COLORS
from app.email_utils import RateLimiter
from app.storage_utils import get_base_url

logger = logging.getLogger(__name__)


def _daily_brief_email_allowed() -> bool:
    """Allow sending only in deployed production unless explicitly overridden."""
    if os.environ.get('ALLOW_EMAIL_IN_NON_PROD') == '1':
        return True
    return os.environ.get('REPLIT_DEPLOYMENT') == '1'


class ResendClient:
    """
    Resend API client for sending daily brief emails.

    Features:
    - Rate limiting (14 emails/sec)
    - Retry logic with exponential backoff
    - HTML email rendering
    - Error tracking
    """

    API_URL = 'https://api.resend.com/emails'
    RATE_LIMIT = 14  # emails per second
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self):
        self._disabled = False
        if not _daily_brief_email_allowed():
            logger.warning(
                "Daily brief outbound email disabled outside deployed production. "
                "Set ALLOW_EMAIL_IN_NON_PROD=1 only for intentional testing."
            )
            self._disabled = True

        self.api_key = os.environ.get('RESEND_API_KEY')
        if not self.api_key:
            if self._disabled:
                logger.warning("RESEND_API_KEY not set - daily brief email disabled in non-production.")
            else:
                raise ValueError("RESEND_API_KEY environment variable not set")

        self.rate_limiter = RateLimiter(self.RATE_LIMIT)
        # Get email address from env and format with name
        self._from_email_addr = os.environ.get('BRIEF_FROM_EMAIL', 'hello@brief.societyspeaks.io')
        # Handle case where env var might already include name (for backwards compat)
        if '<' in self._from_email_addr and '>' in self._from_email_addr:
            self.from_email = self._from_email_addr
        else:
            self.from_email = f'Daily Brief <{self._from_email_addr}>'
        self.reply_to = os.environ.get('BRIEF_REPLY_TO', self._from_email_addr)

    def _extract_email_domain(self, address: Optional[str]) -> str:
        """Extract normalized domain for lightweight deliverability preflight logging."""
        if not address:
            return 'unknown'
        _, parsed_email = parseaddr(address)
        if not parsed_email or '@' not in parsed_email:
            return 'unknown'
        return parsed_email.split('@', 1)[1].lower()

    def _render_brief_text(
        self,
        brief: DailyBrief,
        magic_link_url: str,
        unsubscribe_url: str,
        preferences_url: str,
        sorted_items: Optional[List[BriefItem]] = None,
    ) -> str:
        """Render a plain-text alternative to improve inbox deliverability."""
        if sorted_items is None:
            sorted_items = self._get_sorted_brief_items(brief)

        lines = [
            brief.title or "Daily Brief",
            "",
            f"Date: {brief.date.strftime('%A, %B %d, %Y') if getattr(brief, 'date', None) else 'Today'}",
        ]

        intro_text = getattr(brief, 'intro_text', None)
        if intro_text:
            lines.extend(["", intro_text.strip()])

        lines.extend(["", "Top stories:"])
        for item in sorted_items:
            headline = (item.headline or '').strip()
            if not headline:
                continue
            lines.append(f"{item.position}. {headline}")

            quick_summary = (item.quick_summary or '').strip()
            if quick_summary:
                lines.append(f"   {quick_summary}")

            for bullet in (item.summary_bullets or [])[:3]:
                bullet_text = (bullet or '').strip()
                if bullet_text:
                    lines.append(f"   - {bullet_text}")

            if item.personal_impact:
                lines.append(f"   Why this matters: {item.personal_impact}")
            lines.append("")

        lines.extend([
            f"View on web: {magic_link_url}",
            f"Manage preferences: {preferences_url}",
            f"Unsubscribe: {unsubscribe_url}",
        ])
        return "\n".join(lines).strip() + "\n"

    def _get_sorted_brief_items(self, brief: DailyBrief) -> List[BriefItem]:
        """Fetch brief items once in position order for reuse across renderers."""
        return list(brief.items.order_by(BriefItem.position.asc()).all())

    def _render_welcome_text(
        self,
        subscriber: DailyBriefSubscriber,
        magic_link_url: str,
        preferences_url: str,
        unsubscribe_url: str,
        is_free_tier: bool,
        trial_end_date: str,
        trial_days: Optional[int],
    ) -> str:
        """Render a plain-text welcome email alternative."""
        cadence_label = 'Weekly Brief' if subscriber.cadence == 'weekly' else 'Daily Brief'
        lines = [
            f"Welcome to Society Speaks {cadence_label}",
            "",
            "Your access is active.",
        ]

        if not is_free_tier:
            lines.append(f"Trial ends: {trial_end_date}")
            if trial_days is not None:
                lines.append(f"Days remaining: {trial_days}")

        lines.extend([
            "",
            f"Preferred send hour: {subscriber.preferred_send_hour}:00",
            f"Timezone: {subscriber.timezone}",
            "",
            f"Open your brief: {magic_link_url}",
            f"Manage preferences: {preferences_url}",
            f"Unsubscribe: {unsubscribe_url}",
        ])
        return "\n".join(lines).strip() + "\n"

    def _from_for_brief(self, brief: DailyBrief = None) -> str:
        """Return from address with cadence-appropriate display name."""
        if '<' in self._from_email_addr and '>' in self._from_email_addr:
            return self._from_email_addr
        if brief and getattr(brief, 'brief_type', 'daily') == 'weekly':
            return f'Weekly Brief <{self._from_email_addr}>'
        return self.from_email

    def send_brief(
        self,
        subscriber: DailyBriefSubscriber,
        brief: DailyBrief
    ) -> bool:
        """
        Send brief email to a subscriber.

        Args:
            subscriber: DailyBriefSubscriber instance
            brief: DailyBrief instance to send

        Returns:
            bool: True if sent successfully
        """
        try:
            # Render email HTML
            html_content = self._render_email(subscriber, brief)

            # Build unsubscribe URL using environment config
            base_url = get_base_url()
            magic_link_url = f"{base_url}/brief/m/{subscriber.magic_token}"
            unsubscribe_url = f"{base_url}/brief/unsubscribe/{subscriber.magic_token}"
            preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"
            sorted_items = self._get_sorted_brief_items(brief)

            # Prepare email data with List-Unsubscribe headers for compliance
            email_data = {
                'from': self._from_for_brief(brief),
                'to': [subscriber.email],
                'subject': brief.title,
                'html': html_content,
                'text': self._render_brief_text(
                    brief=brief,
                    magic_link_url=magic_link_url,
                    unsubscribe_url=unsubscribe_url,
                    preferences_url=preferences_url,
                    sorted_items=sorted_items
                ),
                'reply_to': self.reply_to,
                'tags': [
                    {'name': 'campaign', 'value': 'daily_brief'},
                    {'name': 'brief_type', 'value': getattr(brief, 'brief_type', 'daily')},
                ],
                'headers': {
                    'List-Unsubscribe': f'<{unsubscribe_url}>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
                }
            }

            from_domain = self._extract_email_domain(email_data.get('from'))
            reply_to_domain = self._extract_email_domain(email_data.get('reply_to'))
            logger.info(
                "Brief send preflight: from_domain=%s reply_to_domain=%s brief_type=%s",
                from_domain,
                reply_to_domain,
                getattr(brief, 'brief_type', 'daily')
            )

            # Send with rate limiting
            self.rate_limiter.acquire()

            success = self._send_with_retry(email_data)

            if success:
                subscriber.last_sent_at = datetime.utcnow()
                subscriber.last_brief_id_sent = brief.id
                subscriber.total_briefs_received += 1
                db.session.commit()
                logger.info(f"Sent brief to {subscriber.email}")
                
                # Record analytics event
                try:
                    from app.lib.email_analytics import EmailAnalytics
                    EmailAnalytics.record_send(
                        email=subscriber.email,
                        category=EmailAnalytics.CATEGORY_DAILY_BRIEF,
                        subject=brief.title,
                        brief_subscriber_id=subscriber.id,
                        brief_id=brief.id
                    )
                except Exception as analytics_error:
                    logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

            return success

        except Exception as e:
            logger.error(f"Failed to send brief to {subscriber.email}: {e}")
            return False

    def _send_with_retry(self, email_data: dict) -> bool:
        """
        Send email with retry logic.

        Args:
            email_data: Email payload for Resend API

        Returns:
            bool: Success status
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        if self._disabled:
            recipient = (email_data.get('to') or ['unknown'])[0]
            logger.info(f"Daily brief email skipped (non-production guard): {recipient}")
            return True

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    self.API_URL,
                    json=email_data,
                    headers=headers,
                    timeout=30
                )

                if response.status_code == 200:
                    return True
                elif response.status_code == 429:
                    # Rate limited - wait and retry
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 2)
                        logger.warning(f"Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limited after {self.MAX_RETRIES} attempts")
                        return False
                else:
                    logger.error(f"Resend API error: {response.status_code} - {response.text}")
                    return False

            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Timeout (attempt {attempt + 1}/{self.MAX_RETRIES}), retrying...")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Timeout after {self.MAX_RETRIES} attempts")
                    return False

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
                return False

        return False

    def _render_email(
        self,
        subscriber: DailyBriefSubscriber,
        brief: DailyBrief
    ) -> str:
        """
        Render email HTML from template.

        Args:
            subscriber: Subscriber info for personalization
            brief: Brief content to render

        Returns:
            str: HTML email content
        """
        # Get base URL from config or env
        base_url = get_base_url()
        
        # Build URLs
        magic_link_url = f"{base_url}/brief/m/{subscriber.magic_token}"
        unsubscribe_url = f"{base_url}/brief/unsubscribe/{subscriber.magic_token}"
        preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"
        sorted_items = self._get_sorted_brief_items(brief)

        # Render template
        # Note: This assumes template exists at templates/emails/daily_brief.html
        try:
            html = render_template(
                'emails/daily_brief.html',
                brief=brief,
                sorted_items=sorted_items,
                subscriber=subscriber,
                magic_link_url=magic_link_url,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
                base_url=base_url,
                SECTIONS=SECTIONS,
                TOPIC_DISPLAY_LABELS=TOPIC_DISPLAY_LABELS,
                TOPIC_DISPLAY_COLORS=TOPIC_DISPLAY_COLORS
            )
            return html
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            # Fallback to simple HTML
            return self._fallback_html(brief, magic_link_url, unsubscribe_url)

    def _fallback_html(self, brief: DailyBrief, magic_link_url: str, unsubscribe_url: str) -> str:
        """
        Generate simple HTML email if template rendering fails.

        Args:
            brief: DailyBrief instance
            magic_link_url: Magic link to view brief on website
            unsubscribe_url: Unsubscribe link

        Returns:
            str: Simple HTML email
        """
        items_html = ""
        for item in self._get_sorted_brief_items(brief):
            bullets_html = "".join([f"<li>{bullet}</li>" for bullet in (item.summary_bullets or [])])
            items_html += f"""
            <div style="margin-bottom: 30px; padding: 20px; background: #f9f9f9; border-left: 4px solid #333;">
                <h2 style="margin: 0 0 10px 0; font-size: 18px;">{item.position}. {item.headline}</h2>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    {bullets_html}
                </ul>
                <p style="margin: 10px 0 5px 0; font-size: 12px; color: #666;">
                    Coverage: {item.source_count} sources
                </p>
            </div>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{brief.title}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px;">
                <h1 style="margin: 0; font-size: 24px;">SOCIETY SPEAKS DAILY BRIEF</h1>
                <p style="margin: 5px 0 0 0; font-size: 14px; color: #666;">{brief.date.strftime('%A, %B %d, %Y')}</p>
            </div>

            <div style="text-align: center; margin-bottom: 25px;">
                <a href="{magic_link_url}" style="display: inline-block; background-color: #d97706; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px;">View on Website</a>
            </div>

            <div style="margin-bottom: 30px; padding: 15px; background: #fffbf0; border-left: 4px solid #f0ad4e;">
                <p style="margin: 0; font-size: 14px; font-style: italic;">
                    {brief.intro_text}
                </p>
            </div>

            {items_html}

            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center;">
                <p><a href="{magic_link_url}" style="color: #d97706; font-weight: 600;">View on Website</a> | <a href="{unsubscribe_url}" style="color: #666;">Unsubscribe</a> | <a href="https://societyspeaks.io/brief/archive" style="color: #666;">View Archive</a></p>
                <p style="margin-top: 10px;">Society Speaks – Sense-making, not sensationalism</p>
            </div>
        </body>
        </html>
        """
        return html

    def send_welcome(self, subscriber: DailyBriefSubscriber, force: bool = False) -> bool:
        """
        Send welcome email to new daily brief subscriber.

        Args:
            subscriber: DailyBriefSubscriber instance
            force: If True, send even if welcome email was already sent (for manual resends)

        Returns:
            bool: True if sent successfully
        """
        try:
            # Safety check: prevent duplicate welcome emails
            if subscriber.welcome_email_sent_at and not force:
                logger.warning(f"Welcome email already sent to {subscriber.email} at {subscriber.welcome_email_sent_at}, skipping (use force=True to override)")
                return True  # Return True since email was already sent successfully

            base_url = get_base_url()

            magic_link_url = f"{base_url}/brief/m/{subscriber.magic_token}"
            preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"
            unsubscribe_url = f"{base_url}/brief/unsubscribe/{subscriber.magic_token}"

            # Determine subscription type for email content
            is_free_tier = subscriber.tier == 'free'
            trial_end_date = subscriber.trial_ends_at.strftime('%B %d, %Y') if subscriber.trial_ends_at else 'N/A'
            trial_days = subscriber.trial_days_remaining if subscriber.tier == 'trial' else None

            html_content = render_template(
                'emails/daily_brief_welcome.html',
                subscriber=subscriber,
                magic_link_url=magic_link_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                base_url=base_url,
                preferred_hour=subscriber.preferred_send_hour,
                timezone=subscriber.timezone,
                trial_end_date=trial_end_date,
                trial_days=trial_days,
                is_free_tier=is_free_tier
            )

            # Customize subject based on tier and cadence
            cadence_label = 'Weekly Brief' if subscriber.cadence == 'weekly' else 'Daily Brief'
            if is_free_tier:
                subject = f'Welcome to the {cadence_label} - Your Free Access is Active!'
            else:
                subject = f'Welcome to the {cadence_label} - Your Trial Has Started!'

            email_data = {
                'from': self.from_email,
                'to': [subscriber.email],
                'subject': subject,
                'html': html_content,
                'text': self._render_welcome_text(
                    subscriber=subscriber,
                    magic_link_url=magic_link_url,
                    preferences_url=preferences_url,
                    unsubscribe_url=unsubscribe_url,
                    is_free_tier=is_free_tier,
                    trial_end_date=trial_end_date,
                    trial_days=trial_days
                ),
                'reply_to': self.reply_to,
                'tags': [
                    {'name': 'campaign', 'value': 'brief_welcome'},
                    {'name': 'cadence', 'value': subscriber.cadence or 'daily'},
                ],
            }

            self.rate_limiter.acquire()
            success = self._send_with_retry(email_data)

            if success:
                # Record that welcome email was sent to prevent duplicates
                subscriber.welcome_email_sent_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Sent welcome email to {subscriber.email}")
            else:
                logger.error(f"Failed to send welcome email to {subscriber.email}")

            return success

        except Exception as e:
            logger.error(f"Error sending welcome email to {subscriber.email}: {e}")
            return False


class BriefEmailScheduler:
    """
    Manages timezone-based email sending for daily brief.

    Sends emails at subscriber's preferred hour in their timezone.
    """

    def __init__(self):
        self.client = ResendClient()

    def get_subscribers_for_hour(self, utc_hour: int, cadence: str = 'daily', brief_id: int = None) -> List[DailyBriefSubscriber]:
        """
        Get subscribers who should receive email at this UTC hour.

        Args:
            utc_hour: Current UTC hour (0-23)
            cadence: 'daily' or 'weekly' — filters by subscriber preference
            brief_id: Optional brief ID for DB-level idempotency check

        Returns:
            List of DailyBriefSubscriber instances
        """
        query = DailyBriefSubscriber.query.filter(
            DailyBriefSubscriber.status == 'active'
        )

        # Filter by cadence preference
        if cadence == 'weekly':
            query = query.filter(DailyBriefSubscriber.cadence == 'weekly')
        else:
            # Daily subscribers: include those without cadence set (backward compat)
            query = query.filter(
                db.or_(
                    DailyBriefSubscriber.cadence == 'daily',
                    DailyBriefSubscriber.cadence == None
                )
            )

        all_subscribers = query.all()

        subscribers_to_send = []

        for subscriber in all_subscribers:
            if not subscriber.can_receive_brief(brief_id=brief_id):
                continue

            # For weekly: also check it's their preferred day
            if cadence == 'weekly':
                now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
                try:
                    local_tz = pytz.timezone(subscriber.timezone)
                    now_local = now_utc.astimezone(local_tz)
                    preferred_day = getattr(subscriber, 'preferred_weekly_day', 6) or 6
                    if now_local.weekday() != preferred_day:
                        continue
                except Exception as e:
                    logger.error(f"Timezone error for {subscriber.email}: {e}")
                    continue

            # Convert subscriber's preferred time to UTC
            try:
                local_tz = pytz.timezone(subscriber.timezone)
                now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
                now_local = now_utc.astimezone(local_tz)

                # Check if it's their preferred send hour in their timezone
                if now_local.hour == subscriber.preferred_send_hour:
                    subscribers_to_send.append(subscriber)

            except Exception as e:
                logger.error(f"Timezone error for {subscriber.email}: {e}")
                continue

        logger.info(f"Found {len(subscribers_to_send)} {cadence} subscribers for hour {utc_hour}")
        return subscribers_to_send

    def send_to_subscribers(
        self,
        subscribers: List[DailyBriefSubscriber],
        brief: DailyBrief
    ) -> dict:
        """
        Send brief to list of subscribers.

        Args:
            subscribers: List of DailyBriefSubscriber instances
            brief: DailyBrief to send

        Returns:
            dict: {'sent': int, 'failed': int, 'errors': list}
        """
        results = {
            'sent': 0,
            'failed': 0,
            'errors': []
        }

        for subscriber in subscribers:
            try:
                if not subscriber.magic_token or (
                    subscriber.magic_token_expires and subscriber.magic_token_expires < datetime.utcnow()
                ):
                    subscriber.generate_magic_token(expires_hours=168)
                    db.session.commit()

                success = self.client.send_brief(subscriber, brief)
                if success:
                    results['sent'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to send to {subscriber.email}")

            except Exception as e:
                db.session.rollback()
                results['failed'] += 1
                error_msg = f"Error sending to {subscriber.email}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg)

        logger.info(f"Batch send complete: {results['sent']} sent, {results['failed']} failed")
        return results

    def send_todays_brief_hourly(self) -> Optional[dict]:
        """
        Send the latest daily brief to daily subscribers at current UTC hour.

        Called every hour by scheduler.
        
        Logic: The brief is generated at 5pm UTC and published at 6pm UTC.
        - Before 6pm UTC: Send yesterday's brief (today's isn't ready yet)
        - After 6pm UTC: Send today's brief

        Returns:
            dict: Send results, or None if no brief published
        """
        from datetime import date, timedelta

        current_hour = datetime.utcnow().hour
        today = date.today()

        lock_key = f"brief_send_lock:daily:{today.isoformat()}:{current_hour}"
        redis_url = os.environ.get('REDIS_URL')
        if redis_url:
            try:
                import redis as redis_lib
                r = redis_lib.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
                if not r.set(lock_key, os.getpid(), nx=True, ex=3500):
                    logger.info(f"Daily brief send already in progress for hour {current_hour} (lock held), skipping")
                    return {'sent': 0, 'failed': 0, 'errors': []}
            except Exception as e:
                logger.warning(f"Could not acquire Redis send lock: {e}, proceeding with send")
        
        BRIEF_PUBLISH_HOUR = 18
        
        if current_hour < BRIEF_PUBLISH_HOUR:
            brief_date = today - timedelta(days=1)
            brief = DailyBrief.get_by_date(brief_date, brief_type='daily')
            if not brief:
                brief = DailyBrief.get_today(brief_type='daily')
            else:
                logger.info(f"Morning send: using yesterday's brief ({brief_date})")
        else:
            brief = DailyBrief.get_today(brief_type='daily')

        if not brief:
            logger.info("No published daily brief available, skipping send")
            return None

        subscribers = self.get_subscribers_for_hour(current_hour, cadence='daily', brief_id=brief.id)

        if not subscribers:
            logger.info(f"No daily subscribers for hour {current_hour}")
            return {'sent': 0, 'failed': 0, 'errors': []}

        results = self.send_to_subscribers(subscribers, brief)
        return results

    def send_weekly_brief_hourly(self) -> Optional[dict]:
        """
        Send the latest weekly brief to weekly subscribers at current UTC hour.

        Called every hour by scheduler. Only delivers on the subscriber's
        preferred weekly day. Prevents re-sending the same weekly brief
        by checking if the brief was created within the last 7 days.

        Returns:
            dict: Send results, or None if no weekly brief available
        """
        from datetime import date, timedelta

        current_hour = datetime.utcnow().hour
        today = date.today()

        lock_key = f"brief_send_lock:weekly:{today.isoformat()}:{current_hour}"
        redis_url = os.environ.get('REDIS_URL')
        if redis_url:
            try:
                import redis as redis_lib
                r = redis_lib.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
                if not r.set(lock_key, os.getpid(), nx=True, ex=3500):
                    logger.info(f"Weekly brief send already in progress for hour {current_hour} (lock held), skipping")
                    return {'sent': 0, 'failed': 0, 'errors': []}
            except Exception as e:
                logger.warning(f"Could not acquire Redis send lock: {e}, proceeding with send")

        # Find the most recent weekly brief
        brief = DailyBrief.query.filter(
            DailyBrief.brief_type == 'weekly',
            DailyBrief.status.in_(['ready', 'published'])
        ).order_by(DailyBrief.date.desc()).first()

        if not brief:
            logger.debug("No published weekly brief available")
            return None

        # Prevent re-sending old weekly briefs: only send if created within last 7 days
        if brief.date <= date.today() - timedelta(days=7):
            logger.debug(f"Weekly brief ({brief.date}) is older than 7 days, skipping")
            return None

        subscribers = self.get_subscribers_for_hour(current_hour, cadence='weekly', brief_id=brief.id)

        if not subscribers:
            return {'sent': 0, 'failed': 0, 'errors': []}

        logger.info(f"Sending weekly brief ({brief.date}) to {len(subscribers)} subscribers")
        results = self.send_to_subscribers(subscribers, brief)
        return results


def send_brief_to_subscriber(subscriber_email: str, brief_date: Optional[str] = None) -> bool:
    """
    Convenience function to send brief to a single subscriber.

    Args:
        subscriber_email: Email address
        brief_date: Date string (YYYY-MM-DD), or None for today

    Returns:
        bool: Success status
    """
    from datetime import date

    subscriber = DailyBriefSubscriber.query.filter_by(email=subscriber_email).first()
    if not subscriber:
        logger.error(f"Subscriber not found: {subscriber_email}")
        return False

    # Verify subscriber status (allow test sends even if already sent today)
    if subscriber.status != 'active':
        logger.error(f"Subscriber not active: {subscriber_email} (status: {subscriber.status})")
        return False

    if brief_date:
        brief_date_obj = datetime.strptime(brief_date, '%Y-%m-%d').date()
        brief = DailyBrief.get_by_date(brief_date_obj)
    else:
        brief = DailyBrief.get_today()

    if not brief:
        logger.error(f"Brief not found for date: {brief_date or 'today'}")
        return False

    client = ResendClient()
    return client.send_brief(subscriber, brief)
