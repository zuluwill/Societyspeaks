"""
Unified Resend Email Client

Handles all email delivery via Resend API:
- Transactional emails (password reset, welcome, account activation)
- Daily question emails (with batch API support for high volume)
- Daily brief emails (already handled by brief/email_client.py)

Replaces Loops.so integration with a single, simpler provider.
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any
from flask import render_template, current_app, url_for
import requests

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter for API calls"""
    def __init__(self, rate_per_second: float):
        self.rate = rate_per_second
        self.min_interval = 1.0 / rate_per_second
        self.last_call = 0.0
        self.lock = threading.Lock()
    
    def acquire(self):
        """Wait until we can make another call"""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_call
            if time_since_last < self.min_interval:
                time.sleep(self.min_interval - time_since_last)
            self.last_call = time.time()


class ResendEmailClient:
    """
    Unified Resend client for all transactional and batch emails.

    Features:
    - Single email sends for transactional (password reset, welcome)
    - Batch API for high-volume sends (daily questions)
    - Rate limiting (14 emails/sec for single, batched requests for bulk)
    - Retry logic with exponential backoff
    - Jinja2 template rendering
    """

    API_URL = 'https://api.resend.com/emails'
    BATCH_API_URL = 'https://api.resend.com/emails/batch'
    RATE_LIMIT = 14  # emails per second for single sends
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    BATCH_SIZE = 100  # Resend allows up to 100 emails per batch request

    def __init__(self):
        self.api_key = os.environ.get('RESEND_API_KEY')
        self._disabled = False
        
        if not self.api_key:
            # Graceful degradation in development
            flask_env = os.environ.get('FLASK_ENV', 'production')
            if flask_env in ('development', 'testing'):
                logger.warning(
                    "RESEND_API_KEY not set - email sending disabled. "
                    "Set RESEND_API_KEY in your .env file to enable emails."
                )
                self._disabled = True
            else:
                raise ValueError("RESEND_API_KEY environment variable required in production")

        self.rate_limiter = RateLimiter(self.RATE_LIMIT)
        
        # Email addresses - use brief.societyspeaks.io subdomain which is verified in Resend
        self.from_email = os.environ.get('RESEND_FROM_EMAIL', 'Society Speaks <hello@brief.societyspeaks.io>')
        self.from_email_daily = os.environ.get('RESEND_DAILY_FROM_EMAIL', 'Daily Questions <daily@brief.societyspeaks.io>')
        
        # Base URL for building links
        self.base_url = os.environ.get('BASE_URL', 'https://societyspeaks.io')

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def _send_with_retry(self, email_data: Dict[str, Any], use_rate_limit: bool = True) -> bool:
        """
        Send single email with retry logic.

        Args:
            email_data: Email payload for Resend API
            use_rate_limit: Whether to apply rate limiting

        Returns:
            bool: Success status
        """
        # Skip sending if disabled (dev mode without API key)
        if self._disabled:
            logger.info(f"Email skipped (RESEND_API_KEY not set): {email_data.get('to', ['unknown'])[0]}")
            return True  # Return True to not break flows
        
        for attempt in range(self.MAX_RETRIES):
            try:
                if use_rate_limit:
                    self.rate_limiter.acquire()

                response = requests.post(
                    self.API_URL,
                    json=email_data,
                    headers=self._get_headers(),
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

    def _send_batch(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send batch of emails using Resend Batch API.

        Args:
            emails: List of email payloads (max 100)

        Returns:
            dict: {'sent': count, 'failed': count, 'errors': list}
        """
        results = {'sent': 0, 'failed': 0, 'errors': []}

        if not emails:
            return results
        
        # Skip sending if disabled (dev mode without API key)
        if self._disabled:
            logger.info(f"Batch of {len(emails)} emails skipped (RESEND_API_KEY not set)")
            results['sent'] = len(emails)  # Pretend success to not break flows
            return results

        if len(emails) > self.BATCH_SIZE:
            raise ValueError(f"Batch size {len(emails)} exceeds maximum {self.BATCH_SIZE}")

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    self.BATCH_API_URL,
                    json=emails,
                    headers=self._get_headers(),
                    timeout=60  # Longer timeout for batch
                )

                if response.status_code == 200:
                    data = response.json()
                    # Resend returns {"data": [{"id": "..."}, ...]}
                    if 'data' in data:
                        results['sent'] = len(data['data'])
                    else:
                        results['sent'] = len(emails)
                    return results
                elif response.status_code == 429:
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 2)
                        logger.warning(f"Batch rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        results['failed'] = len(emails)
                        results['errors'].append(f"Rate limited after {self.MAX_RETRIES} attempts")
                        return results
                else:
                    results['failed'] = len(emails)
                    results['errors'].append(f"API error: {response.status_code} - {response.text}")
                    return results

            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Batch timeout (attempt {attempt + 1}/{self.MAX_RETRIES})")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    results['failed'] = len(emails)
                    results['errors'].append("Timeout after retries")
                    return results

            except requests.exceptions.RequestException as e:
                results['failed'] = len(emails)
                results['errors'].append(str(e))
                return results

        return results

    # =========================================================================
    # TRANSACTIONAL EMAILS
    # =========================================================================

    def send_password_reset(self, user, token: str) -> bool:
        """
        Send password reset email.

        Args:
            user: User object with email and username
            token: Password reset token

        Returns:
            bool: Success status
        """
        reset_url = f"{self.base_url}/auth/reset-password/{token}"
        
        try:
            html = render_template(
                'emails/password_reset.html',
                username=user.username or 'User',
                reset_url=reset_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for password_reset: {e}")
            return False

        email_data = {
            'from': self.from_email,
            'to': [user.email],
            'subject': 'Reset Your Password - Society Speaks',
            'html': html
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Password reset email sent to {user.email}")
        else:
            logger.error(f"Failed to send password reset email to {user.email}")

        return success

    def send_welcome_email(self, user, verification_url: Optional[str] = None) -> bool:
        """
        Send welcome email to new user.

        Args:
            user: User object with email and username
            verification_url: Optional email verification URL

        Returns:
            bool: Success status
        """
        try:
            html = render_template(
                'emails/welcome.html',
                username=user.username or 'There',
                verification_url=verification_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for welcome: {e}")
            return False

        email_data = {
            'from': self.from_email,
            'to': [user.email],
            'subject': 'Welcome to Society Speaks!',
            'html': html
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Welcome email sent to {user.email}")
        else:
            logger.error(f"Failed to send welcome email to {user.email}")

        return success

    def send_account_activation(self, user, activation_token: str) -> bool:
        """
        Send account activation email.

        Args:
            user: User object with email and username
            activation_token: Activation token

        Returns:
            bool: Success status
        """
        activation_url = f"{self.base_url}/auth/activate/{activation_token}"
        
        try:
            html = render_template(
                'emails/account_activation.html',
                username=user.username or 'User',
                activation_url=activation_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for account_activation: {e}")
            return False

        email_data = {
            'from': self.from_email,
            'to': [user.email],
            'subject': 'Activate Your Society Speaks Account',
            'html': html
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Account activation email sent to {user.email}")
        else:
            logger.error(f"Failed to send account activation email to {user.email}")

        return success

    # =========================================================================
    # DAILY QUESTION EMAILS
    # =========================================================================

    def send_daily_question_welcome(self, subscriber) -> bool:
        """
        Send welcome email to new daily question subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object

        Returns:
            bool: Success status
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        daily_question_url = f"{self.base_url}/daily"
        unsubscribe_url = f"{self.base_url}/daily/unsubscribe/{subscriber.magic_token}"
        
        try:
            html = render_template(
                'emails/daily_question_welcome.html',
                magic_link_url=magic_link_url,
                daily_question_url=daily_question_url,
                unsubscribe_url=unsubscribe_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for daily_question_welcome: {e}")
            return False

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': "You're Subscribed to Daily Civic Questions!",
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Daily question welcome email sent to {subscriber.email}")
        else:
            logger.error(f"Failed to send daily question welcome email to {subscriber.email}")

        return success

    def send_daily_question(self, subscriber, question) -> bool:
        """
        Send daily question email to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            question: DailyQuestion object

        Returns:
            bool: Success status
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        question_url = f"{self.base_url}/daily/{question.question_date.isoformat()}"
        unsubscribe_url = f"{self.base_url}/daily/unsubscribe/{subscriber.magic_token}"
        
        # One-click vote URLs
        vote_agree_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/agree"
        vote_disagree_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/disagree"
        vote_unsure_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/unsure"

        # Build streak message
        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."
        
        try:
            html = render_template(
                'emails/daily_question.html',
                question_number=question.question_number,
                question_text=question.question_text,
                question_context=question.context or "",
                why_this_question=why_this,
                topic_category=question.topic_category or "Civic",
                magic_link_url=magic_link_url,
                question_url=question_url,
                streak_message=streak_message,
                unsubscribe_url=unsubscribe_url,
                vote_agree_url=vote_agree_url,
                vote_disagree_url=vote_disagree_url,
                vote_unsure_url=vote_unsure_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for daily_question: {e}")
            return False

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

        success = self._send_with_retry(email_data)
        
        if success:
            subscriber.last_email_sent = datetime.utcnow()
        
        return success

    def _build_daily_question_email(self, subscriber, question) -> Dict[str, Any]:
        """
        Build email payload for a daily question (used in batch sending).

        Args:
            subscriber: DailyQuestionSubscriber with magic_token
            question: DailyQuestion object

        Returns:
            dict: Email payload for Resend API
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        question_url = f"{self.base_url}/daily/{question.question_date.isoformat()}"
        unsubscribe_url = f"{self.base_url}/daily/unsubscribe/{subscriber.magic_token}"
        
        # One-click vote URLs
        vote_agree_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/agree"
        vote_disagree_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/disagree"
        vote_unsure_url = f"{self.base_url}/daily/v/{subscriber.magic_token}/unsure"

        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."
        
        html = render_template(
            'emails/daily_question.html',
            question_number=question.question_number,
            question_text=question.question_text,
            question_context=question.context or "",
            why_this_question=why_this,
            topic_category=question.topic_category or "Civic",
            magic_link_url=magic_link_url,
            question_url=question_url,
            streak_message=streak_message,
            unsubscribe_url=unsubscribe_url,
            vote_agree_url=vote_agree_url,
            vote_disagree_url=vote_disagree_url,
            vote_unsure_url=vote_unsure_url,
            base_url=self.base_url
        )

        return {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

    def send_daily_question_batch(
        self,
        subscribers: List,
        question,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Send daily question to multiple subscribers using batch API.

        Processes subscribers in batches of 100 for efficiency.
        Much faster than individual sends (1 API call per 100 vs 100 calls).

        Args:
            subscribers: List of DailyQuestionSubscriber objects (must have magic_tokens set)
            question: DailyQuestion object
            on_progress: Optional callback(sent, failed, total) for progress updates

        Returns:
            dict: {'sent': int, 'failed': int, 'errors': list, 'failed_emails': list}
        """
        from app import db

        results = {
            'sent': 0,
            'failed': 0,
            'errors': [],
            'failed_emails': []
        }

        if not subscribers:
            return results

        total = len(subscribers)
        processed = 0

        # Process in batches
        for i in range(0, total, self.BATCH_SIZE):
            batch_subscribers = subscribers[i:i + self.BATCH_SIZE]
            batch_emails = []

            for subscriber in batch_subscribers:
                try:
                    email_payload = self._build_daily_question_email(subscriber, question)
                    batch_emails.append(email_payload)
                except Exception as e:
                    logger.error(f"Failed to build email for {subscriber.email}: {e}")
                    results['failed'] += 1
                    results['failed_emails'].append(subscriber.email)

            if batch_emails:
                batch_result = self._send_batch(batch_emails)
                results['sent'] += batch_result['sent']
                results['failed'] += batch_result['failed']
                results['errors'].extend(batch_result.get('errors', []))

                # Update last_email_sent for successful sends
                # Note: With batch API, we assume all or none in the batch succeeded
                if batch_result['sent'] > 0:
                    for subscriber in batch_subscribers:
                        subscriber.last_email_sent = datetime.utcnow()

            processed += len(batch_subscribers)

            if on_progress:
                on_progress(results['sent'], results['failed'], total)

            logger.info(
                f"Batch {i // self.BATCH_SIZE + 1}: "
                f"{results['sent']} sent, {results['failed']} failed of {total}"
            )

        # Commit last_email_sent updates
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to commit last_email_sent updates: {e}")

        return results


# =============================================================================
# CONVENIENCE FUNCTIONS (drop-in replacements for email_utils.py functions)
# =============================================================================

def get_resend_client() -> ResendEmailClient:
    """Get or create ResendEmailClient instance"""
    return ResendEmailClient()


def send_password_reset_email(user, token: str) -> bool:
    """
    Send password reset email via Resend.
    Drop-in replacement for email_utils.send_password_reset_email
    """
    try:
        client = get_resend_client()
        return client.send_password_reset(user, token)
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
        return False


def send_welcome_email(user, verification_url: Optional[str] = None) -> bool:
    """
    Send welcome email via Resend.
    Drop-in replacement for email_utils.send_welcome_email
    """
    try:
        client = get_resend_client()
        return client.send_welcome_email(user, verification_url)
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return False


def send_account_activation_email(user, activation_token: str) -> bool:
    """
    Send account activation email via Resend.
    Drop-in replacement for email_utils.send_account_activation_email
    """
    try:
        client = get_resend_client()
        return client.send_account_activation(user, activation_token)
    except Exception as e:
        logger.error(f"Failed to send account activation email: {e}")
        return False


def send_daily_question_welcome_email(subscriber) -> bool:
    """
    Send daily question welcome email via Resend.
    Drop-in replacement for email_utils.send_daily_question_welcome_email
    """
    try:
        client = get_resend_client()
        return client.send_daily_question_welcome(subscriber)
    except Exception as e:
        logger.error(f"Failed to send daily question welcome email: {e}")
        return False


def send_daily_question_email(subscriber, question) -> bool:
    """
    Send single daily question email via Resend.
    Drop-in replacement for email_utils.send_daily_question_email
    """
    try:
        client = get_resend_client()
        return client.send_daily_question(subscriber, question)
    except Exception as e:
        logger.error(f"Failed to send daily question email: {e}")
        return False


def send_discussion_notification_email(user, discussion, notification_type: str, additional_data: Optional[Dict] = None) -> bool:
    """
    Send discussion notification email via Resend.
    Drop-in replacement for email_utils.send_discussion_notification_email

    Args:
        user: User object to notify
        discussion: Discussion object
        notification_type: 'new_participant', 'new_response', or 'discussion_active'
        additional_data: Optional additional template data

    Returns:
        bool: Success status
    """
    try:
        client = get_resend_client()

        # Generate discussion URL
        base_url = client.base_url
        discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"

        # Prepare notification-specific content
        if notification_type == 'new_participant':
            subject = f"New participant in your discussion"
            message = f"Someone new has joined your discussion '{discussion.title}'"
        elif notification_type == 'new_response':
            subject = f"New response in your discussion"
            message = f"There's new activity in your discussion '{discussion.title}'"
        else:
            subject = f"Activity in your discussion"
            message = f"There's been activity in your discussion '{discussion.title}'"

        # Build simple HTML email
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; border-bottom: 2px solid #1e40af; padding-bottom: 20px; margin-bottom: 20px;">
                <h1 style="margin: 0; font-size: 24px; color: #1e40af;">Society Speaks</h1>
            </div>
            
            <p>Hi {user.username or 'there'},</p>
            
            <p>{message}</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{discussion_url}" style="background-color: #1e40af; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600;">View Discussion</a>
            </div>
            
            <p style="color: #6b7280; font-size: 14px;">
                You're receiving this because you created this discussion and have notifications enabled.
            </p>
            
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
            
            <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                Society Speaks - Sense-making, not sensationalism
            </p>
        </body>
        </html>
        """

        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': subject,
            'html': html_content
        }

        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Discussion notification email sent to {user.email}")
        else:
            logger.error(f"Failed to send discussion notification email to {user.email}")

        return success

    except Exception as e:
        logger.error(f"Failed to send discussion notification email: {e}")
        return False


def send_profile_completion_reminder_email(user, missing_fields: list, profile_url: str) -> bool:
    """
    Send profile completion reminder email via Resend.
    Drop-in replacement for email_utils.send_profile_completion_reminder_email
    
    Args:
        user: User object
        missing_fields: List of incomplete profile fields
        profile_url: URL to edit profile
        
    Returns:
        bool: Success status
    """
    try:
        client = get_resend_client()
        
        html = render_template(
            'emails/profile_completion_reminder.html',
            username=user.username or 'there',
            missing_fields=missing_fields,
            profile_url=profile_url,
            base_url=client.base_url
        )
        
        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': 'Complete Your Society Speaks Profile',
            'html': html
        }
        
        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Profile completion reminder sent to {user.email}")
            # Record analytics event
            from app.lib.email_analytics import EmailAnalytics
            EmailAnalytics.record_send(
                email=user.email,
                category=EmailAnalytics.CATEGORY_AUTH,
                subject='Complete Your Society Speaks Profile',
                user_id=user.id
            )
        else:
            logger.error(f"Failed to send profile completion reminder to {user.email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send profile completion reminder: {e}")
        return False


def send_weekly_discussion_digest(user, digest_data: dict) -> bool:
    """
    Send weekly discussion digest email via Resend.
    
    Args:
        user: User object
        digest_data: Dict containing:
            - discussions_with_activity: List of dicts with discussion activity
            - trending_topics: List of trending discussions
            - stats: Dict with user's weekly stats
            
    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        client = get_resend_client()
        
        # Build URLs
        dashboard_url = f"{client.base_url}/dashboard"
        settings_url = f"{client.base_url}/settings"
        
        # Render template
        html = render_template(
            'emails/weekly_digest.html',
            username=user.username or 'there',
            discussions_with_activity=digest_data.get('discussions_with_activity', []),
            trending_topics=digest_data.get('trending_topics', []),
            stats=digest_data.get('stats', {
                'discussions_created': 0,
                'votes_cast': 0,
                'responses_written': 0
            }),
            dashboard_url=dashboard_url,
            settings_url=settings_url,
            base_url=client.base_url
        )
        
        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': f'Your Weekly Discussion Digest - Society Speaks',
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{settings_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }
        
        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Weekly digest sent to {user.email}")
            # Record analytics event
            from app.lib.email_analytics import EmailAnalytics
            EmailAnalytics.record_send(
                email=user.email,
                category=EmailAnalytics.CATEGORY_AUTH,  # Could create CATEGORY_DIGEST
                subject='Your Weekly Discussion Digest',
                user_id=user.id
            )
        else:
            logger.error(f"Failed to send weekly digest to {user.email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send weekly digest: {e}")
        return False


def send_daily_question_to_all_subscribers() -> int:
    """
    Send today's daily question to all active subscribers using batch API.
    Drop-in replacement for email_utils.send_daily_question_to_all_subscribers

    Returns:
        int: Number of emails successfully sent
    """
    from app.models import DailyQuestion, DailyQuestionSubscriber
    from app import db

    # Get today's question
    question = DailyQuestion.get_today()
    if not question:
        logger.info("No daily question to send - none published for today")
        return 0

    # Get all active subscribers
    total_subscribers = DailyQuestionSubscriber.query.filter_by(is_active=True).count()

    if total_subscribers == 0:
        logger.info("No active subscribers to send daily question to")
        return 0

    logger.info(
        f"Starting daily question #{question.question_number} send to {total_subscribers} subscribers "
        f"(using batch API for efficiency)"
    )

    start_time = time.time()
    
    try:
        client = get_resend_client()
    except Exception as e:
        logger.error(f"Failed to initialize Resend client: {e}")
        return 0

    # Process in chunks to manage memory
    CHUNK_SIZE = 500
    total_sent = 0
    total_failed = 0
    skipped_duplicates = 0
    offset = 0

    while True:
        # Get chunk of subscribers
        subscribers = DailyQuestionSubscriber.query.filter_by(is_active=True)\
            .order_by(DailyQuestionSubscriber.id)\
            .offset(offset)\
            .limit(CHUNK_SIZE)\
            .all()

        if not subscribers:
            break

        # Filter out subscribers who already received today's email (duplicate prevention)
        eligible_subscribers = []
        for subscriber in subscribers:
            if subscriber.can_receive_email():
                eligible_subscribers.append(subscriber)
            else:
                skipped_duplicates += 1
        
        if not eligible_subscribers:
            offset += CHUNK_SIZE
            continue

        # Generate magic tokens for eligible subscribers in this chunk
        for subscriber in eligible_subscribers:
            subscriber.generate_magic_token()
        
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to generate magic tokens: {e}")
            db.session.rollback()
            offset += CHUNK_SIZE
            continue

        # Send batch
        results = client.send_daily_question_batch(eligible_subscribers, question)
        total_sent += results['sent']
        total_failed += results['failed']

        if results['errors']:
            for error in results['errors'][:5]:  # Log first 5 errors
                logger.warning(f"Batch error: {error}")

        offset += CHUNK_SIZE

        # Progress log
        elapsed = time.time() - start_time
        rate = total_sent / elapsed if elapsed > 0 else 0
        logger.info(
            f"Progress: {total_sent} sent, {total_failed} failed "
            f"({rate:.1f} emails/sec)"
        )

    elapsed_total = time.time() - start_time
    final_rate = total_sent / elapsed_total if elapsed_total > 0 else 0

    logger.info(
        f"Daily question #{question.question_number} complete: "
        f"{total_sent} sent, {total_failed} failed, {skipped_duplicates} skipped (already sent) "
        f"of {total_subscribers} in {elapsed_total:.1f} seconds ({final_rate:.1f} emails/sec)"
    )

    return total_sent
