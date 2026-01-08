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
from typing import List, Optional
from flask import render_template, current_app
from app.models import DailyBrief, DailyBriefSubscriber, BriefItem, db
from app.email_utils import RateLimiter

logger = logging.getLogger(__name__)


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
        self.api_key = os.environ.get('RESEND_API_KEY')
        if not self.api_key:
            raise ValueError("RESEND_API_KEY environment variable not set")

        self.rate_limiter = RateLimiter(self.RATE_LIMIT)
        self.from_email = os.environ.get('BRIEF_FROM_EMAIL', 'Daily Brief <hello@brief.societyspeaks.io>')

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
            base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL', 'https://societyspeaks.io')
            unsubscribe_url = f"{base_url}/brief/unsubscribe/{subscriber.magic_token}"

            # Prepare email data with List-Unsubscribe headers for compliance
            email_data = {
                'from': self.from_email,
                'to': [subscriber.email],
                'subject': brief.title,
                'html': html_content,
                'headers': {
                    'List-Unsubscribe': f'<{unsubscribe_url}>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
                }
            }

            # Send with rate limiting
            self.rate_limiter.acquire()

            success = self._send_with_retry(email_data)

            if success:
                # Update tracking
                subscriber.last_sent_at = datetime.utcnow()
                subscriber.total_briefs_received += 1
                db.session.commit()
                logger.info(f"Sent brief to {subscriber.email}")

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
        # Get base URL from config or env (APP_BASE_URL is the primary, fallback to SITE_URL)
        base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL', 'https://societyspeaks.io')
        base_url = base_url.rstrip('/')
        
        # Build URLs
        unsubscribe_url = f"{base_url}/brief/unsubscribe/{subscriber.magic_token}"
        preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"

        # Render template
        # Note: This assumes template exists at templates/emails/daily_brief.html
        try:
            html = render_template(
                'emails/daily_brief.html',
                brief=brief,
                subscriber=subscriber,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
                base_url=base_url
            )
            return html
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            # Fallback to simple HTML
            return self._fallback_html(brief, unsubscribe_url)

    def _fallback_html(self, brief: DailyBrief, unsubscribe_url: str) -> str:
        """
        Generate simple HTML email if template rendering fails.

        Args:
            brief: DailyBrief instance
            unsubscribe_url: Unsubscribe link

        Returns:
            str: Simple HTML email
        """
        items_html = ""
        for item in brief.items.order_by(BriefItem.position.asc()):
            bullets_html = "".join([f"<li>{bullet}</li>" for bullet in item.summary_bullets])
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

            <div style="margin-bottom: 30px; padding: 15px; background: #fffbf0; border-left: 4px solid #f0ad4e;">
                <p style="margin: 0; font-size: 14px; font-style: italic;">
                    {brief.intro_text}
                </p>
            </div>

            {items_html}

            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center;">
                <p><a href="{unsubscribe_url}" style="color: #666;">Unsubscribe</a> | <a href="https://societyspeaks.io/brief/archive" style="color: #666;">View Archive</a> | <a href="https://societyspeaks.io/brief/methodology" style="color: #666;">How We Work</a></p>
                <p style="margin-top: 10px;">Society Speaks – Sense-making, not sensationalism</p>
            </div>
        </body>
        </html>
        """
        return html


class BriefEmailScheduler:
    """
    Manages timezone-based email sending for daily brief.

    Sends emails at subscriber's preferred hour in their timezone.
    """

    def __init__(self):
        self.client = ResendClient()

    def get_subscribers_for_hour(self, utc_hour: int) -> List[DailyBriefSubscriber]:
        """
        Get subscribers who should receive email at this UTC hour.

        Args:
            utc_hour: Current UTC hour (0-23)

        Returns:
            List of DailyBriefSubscriber instances
        """
        all_subscribers = DailyBriefSubscriber.query.filter(
            DailyBriefSubscriber.status == 'active'
        ).all()

        subscribers_to_send = []

        for subscriber in all_subscribers:
            # Check eligibility AND duplicate prevention
            if not subscriber.can_receive_brief():
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

        logger.info(f"Found {len(subscribers_to_send)} subscribers for hour {utc_hour}")
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
                success = self.client.send_brief(subscriber, brief)
                if success:
                    results['sent'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to send to {subscriber.email}")

            except Exception as e:
                results['failed'] += 1
                error_msg = f"Error sending to {subscriber.email}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg)

        logger.info(f"Batch send complete: {results['sent']} sent, {results['failed']} failed")
        return results

    def send_todays_brief_hourly(self) -> Optional[dict]:
        """
        Send the latest brief to subscribers at current UTC hour.

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
        
        # Brief is published at 6pm UTC (18:00)
        # Before that, morning subscribers should get yesterday's brief
        BRIEF_PUBLISH_HOUR = 18
        
        if current_hour < BRIEF_PUBLISH_HOUR:
            # Morning hours - send yesterday's brief
            brief_date = today - timedelta(days=1)
            brief = DailyBrief.get_by_date(brief_date)
            if not brief:
                # Fallback to today's if yesterday's doesn't exist
                brief = DailyBrief.get_today()
            else:
                logger.info(f"Morning send: using yesterday's brief ({brief_date})")
        else:
            # Evening hours - send today's brief
            brief = DailyBrief.get_today()

        if not brief:
            logger.info("No published brief available, skipping send")
            return None

        # Get subscribers for this hour
        current_hour = datetime.utcnow().hour
        subscribers = self.get_subscribers_for_hour(current_hour)

        if not subscribers:
            logger.info(f"No subscribers for hour {current_hour}")
            return {'sent': 0, 'failed': 0, 'errors': []}

        # Send
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
