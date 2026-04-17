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
from datetime import datetime
from app.lib.time import utcnow_naive
from typing import List, Dict, Optional, Any, Tuple
from flask import render_template, current_app, url_for
import requests
from app.email_utils import RateLimiter, extract_clean_email as _extract_clean_email  # shared utilities
from app.briefing.link_tracker import wrap_links as _wrap_links

logger = logging.getLogger(__name__)



def _email_sending_allowed_for_environment() -> bool:
    """
    Allow outbound email only in deployed production by default.

    Override for intentional non-production testing with:
    ALLOW_EMAIL_IN_NON_PROD=1
    """
    if os.environ.get('ALLOW_EMAIL_IN_NON_PROD') == '1':
        return True
    return os.environ.get('REPLIT_DEPLOYMENT') == '1'


_RESEND_API_URL = 'https://api.resend.com/emails'
_RESEND_BATCH_API_URL = 'https://api.resend.com/emails/batch'

_RETRYABLE_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    OSError,
    IOError,
)


def _resend_http_post(
    api_key: str,
    body: Any,
    url: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 30,
    log_prefix: str = "Resend",
) -> Tuple[Optional[requests.Response], Optional[str]]:
    """
    POST to the Resend API with exponential-backoff retry on transient errors.

    Returns (response, None) on HTTP 200, or (None, error_str) on failure.
    Logs all warnings and errors internally.
    """
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response, None
            elif response.status_code == 429:
                if attempt < max_retries - 1:
                    wait = retry_delay * (2 ** attempt)
                    logger.warning(
                        f"{log_prefix} rate limited — waiting {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                err = f"Rate limited after {max_retries} attempts"
                logger.error(f"{log_prefix}: {err}")
                return None, err
            else:
                err = f"API error: {response.status_code} - {response.text}"
                logger.error(f"{log_prefix}: {err}")
                return None, err
        except _RETRYABLE_ERRORS as e:
            if attempt < max_retries - 1:
                wait = retry_delay * (2 ** attempt)
                logger.warning(
                    f"{log_prefix} transient error (attempt {attempt + 1}/{max_retries}): "
                    f"{type(e).__name__}: {e} — retrying in {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                err = f"Transient error after {max_retries} attempts: {e}"
                logger.error(f"{log_prefix}: {err}")
                return None, err
        except requests.exceptions.RequestException as e:
            err = f"Request error (non-retryable): {e}"
            logger.error(f"{log_prefix}: {err}")
            return None, err
    return None, "Max retries exceeded"


def resend_post_with_retry(
    api_key: str,
    payload: dict,
    url: str = _RESEND_API_URL,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 30,
) -> Tuple[bool, Optional[str]]:
    """
    POST a single email to the Resend API with exponential-backoff retry.

    Retries on transient OS/network errors (OSError/IOError/Timeout/ConnectionError)
    that can occur when TLS certificate files are read from the overlay filesystem.

    Returns:
        (success, message_id)  — message_id is None on failure or if Resend omits it.
    """
    response, err = _resend_http_post(api_key, payload, url, max_retries, retry_delay, timeout)
    if response is None:
        return False, err
    try:
        message_id = response.json().get('id')
    except Exception:
        message_id = None
    return True, message_id


def resend_batch_with_retry(
    api_key: str,
    payloads: list,
    url: str = _RESEND_BATCH_API_URL,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 60,
) -> Tuple[bool, int, int, List[str]]:
    """
    POST a batch of emails to the Resend batch API with exponential-backoff retry.

    Returns:
        (success, sent_count, failed_count, errors)
    """
    response, error = _resend_http_post(
        api_key, payloads, url, max_retries, retry_delay, timeout, log_prefix="Resend batch"
    )
    if response is None:
        return False, 0, len(payloads or []), [error or "Unknown error"]

    try:
        data = response.json() or {}
    except Exception as e:
        return False, 0, len(payloads or []), [f"Invalid JSON response from Resend batch API: {e}"]

    created = data.get("data") or []
    raw_errors = data.get("errors") or []

    sent_count = len(created)
    failed_count = len(raw_errors)

    # If Resend returns no structured errors, treat the call as fully successful.
    # This matches strict validation mode (atomic success) responses.
    errors: List[str] = []
    for err in raw_errors:
        if isinstance(err, dict):
            idx = err.get("index")
            msg = err.get("message") or err.get("error") or str(err)
            if idx is not None:
                errors.append(f"[{idx}] {msg}")
            else:
                errors.append(msg)
        else:
            errors.append(str(err))

    # If we received neither data nor errors, fall back to optimistic "all sent"
    # but preserve any top-level error fields if present.
    if sent_count == 0 and failed_count == 0:
        sent_count = len(payloads or [])

    success = failed_count == 0
    return success, sent_count, failed_count, errors


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

    RATE_LIMIT = 14  # emails per second for single sends
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    BATCH_SIZE = 100  # Resend allows up to 100 emails per batch request

    def __init__(self):
        self.api_key = os.environ.get('RESEND_API_KEY')
        self._disabled = False
        self.last_message_id: Optional[str] = None
        self.last_send_error: Optional[str] = None
        self._email_allowed = _email_sending_allowed_for_environment()

        if not self._email_allowed:
            logger.warning(
                "Outbound email disabled outside deployed production. "
                "Set ALLOW_EMAIL_IN_NON_PROD=1 only for intentional testing."
            )
            self._disabled = True
        
        if not self.api_key:
            # Graceful degradation in non-production or when email sending is intentionally disabled.
            flask_env = os.environ.get('FLASK_ENV', 'production')
            if (not self._email_allowed) or flask_env in ('development', 'testing'):
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

    def _send_with_retry(self, email_data: Dict[str, Any], use_rate_limit: bool = True) -> bool:
        """
        Send a single email via Resend with rate limiting and retry.

        Args:
            email_data: Email payload for Resend API
            use_rate_limit: Whether to apply rate limiting (default True)

        Returns:
            bool: True on success, False on failure
        """
        if self._disabled:
            logger.info(f"Email skipped (disabled): {email_data.get('to', ['unknown'])[0]}")
            self.last_message_id = None
            return True

        # Validate and normalise the 'to' addresses before sending.
        # Resend rejects bare angle-bracket addresses like <user@domain.com> with
        # a 422 validation_error; catching them here prevents avoidable API round-trips.
        raw_to = email_data.get('to') or []
        cleaned_to = []
        for raw_addr in raw_to:
            clean = _extract_clean_email(raw_addr)
            if clean is None:
                logger.error(
                    f"Skipping email send — invalid 'to' address: {repr(raw_addr)}"
                )
                self.last_message_id = None
                return False
            cleaned_to.append(clean)
        email_data = {**email_data, 'to': cleaned_to}

        if use_rate_limit:
            self.rate_limiter.acquire()

        success, result = resend_post_with_retry(
            self.api_key,
            email_data,
            max_retries=self.MAX_RETRIES,
            retry_delay=self.RETRY_DELAY,
        )
        if success:
            self.last_message_id = result
            self.last_send_error = None
        else:
            self.last_message_id = None
            self.last_send_error = result
        return success

    def _send_batch(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send a batch of emails via the Resend Batch API.

        Args:
            emails: List of email payloads (max 100 per Resend limit)

        Returns:
            dict: {'sent': count, 'failed': count, 'errors': list}
        """
        results: Dict[str, Any] = {'sent': 0, 'failed': 0, 'errors': []}

        if not emails:
            return results

        if self._disabled:
            logger.info(f"Batch of {len(emails)} emails skipped (disabled)")
            results['sent'] = len(emails)
            return results

        # Validate and normalise each payload's 'to' field before sending.
        valid_emails = []
        for payload in emails:
            raw_to = payload.get('to') or []
            cleaned_to = []
            all_valid = True
            for raw_addr in raw_to:
                clean = _extract_clean_email(raw_addr)
                if clean is None:
                    logger.error(f"Batch: dropping email with invalid 'to' address: {repr(raw_addr)}")
                    results['failed'] += 1
                    results['errors'].append(f"Invalid address: {repr(raw_addr)}")
                    all_valid = False
                    break
                cleaned_to.append(clean)
            if all_valid:
                valid_emails.append({**payload, 'to': cleaned_to})

        if not valid_emails:
            return results

        if len(valid_emails) > self.BATCH_SIZE:
            raise ValueError(f"Batch size {len(valid_emails)} exceeds maximum {self.BATCH_SIZE}")

        success, sent_count, failed_count, errors = resend_batch_with_retry(
            self.api_key,
            valid_emails,
            max_retries=self.MAX_RETRIES,
            retry_delay=self.RETRY_DELAY,
        )
        results['sent'] += sent_count
        if not success:
            results['failed'] += failed_count or (len(valid_emails) - sent_count)
            results['errors'].extend(errors)
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

    def send_verification_email(self, user, verification_url: str) -> bool:
        """
        Send a standalone email verification email (used for resends).

        Args:
            user: User object with email and username
            verification_url: The full verification URL

        Returns:
            bool: Success status
        """
        try:
            html = render_template(
                'emails/verify_email.html',
                username=user.username or 'there',
                verification_url=verification_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for verify_email: {e}")
            return False

        email_data = {
            'from': self.from_email,
            'to': [user.email],
            'subject': 'Verify your Society Speaks email address',
            'html': html
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)

        if success:
            logger.info(f"Verification email sent to {user.email}")
        else:
            logger.error(f"Failed to send verification email to {user.email}")

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
            # Build preferences URL for managing frequency
            preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
            
            html = render_template(
                'emails/daily_question_welcome.html',
                magic_link_url=magic_link_url,
                daily_question_url=daily_question_url,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
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

    def _build_vote_urls(self, subscriber, question_id: int) -> dict:
        """
        Build question-specific one-click vote URLs.
        
        DRY helper method used by both single and batch email sending.

        Args:
            subscriber: DailyQuestionSubscriber with generate_vote_token method
            question_id: The daily question ID to bind the token to

        Returns:
            dict with 'agree', 'disagree', 'unsure' URLs
        """
        vote_token = subscriber.generate_vote_token(question_id)
        return {
            'agree': f"{self.base_url}/daily/v/{vote_token}/agree",
            'disagree': f"{self.base_url}/daily/v/{vote_token}/disagree",
            'unsure': f"{self.base_url}/daily/v/{vote_token}/unsure",
        }

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

        # Generate question-specific vote URLs using helper
        vote_urls = self._build_vote_urls(subscriber, question.id)

        # Build streak message
        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."

        try:
            from app.daily.utils import get_source_articles_for_question
            source_articles = get_source_articles_for_question(question, limit=3)
        except Exception:
            source_articles = []
        
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
                vote_agree_url=vote_urls['agree'],
                vote_disagree_url=vote_urls['disagree'],
                vote_unsure_url=vote_urls['unsure'],
                base_url=self.base_url,
                source_articles=source_articles
            )
        except Exception as e:
            logger.error(f"Template rendering failed for daily_question: {e}")
            return False

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=question.id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )

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
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                    question_subscriber_id=subscriber.id,
                    daily_question_id=question.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

        return success

    def send_weekly_questions_digest(self, subscriber, questions) -> bool:
        """
        Send weekly digest email with 5 questions to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            questions: List of DailyQuestion objects (up to 5)

        Returns:
            bool: Success status
        """
        from app.daily.utils import get_discussion_stats_for_question

        if not questions:
            logger.warning(f"No questions provided for weekly digest to {subscriber.email}")
            return False

        # Build URLs with question IDs for batch page
        question_ids = ','.join(str(q.id) for q in questions)
        batch_url = f"{self.base_url}/daily/weekly?token={subscriber.magic_token}&questions={question_ids}"
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
        unsubscribe_url = f"{self.base_url}/daily/unsubscribe/{subscriber.magic_token}"

        # Build question data with vote URLs, discussion stats, and source articles
        from app.daily.utils import build_question_email_data
        
        questions_data = []
        for question in questions:
            # Use DRY helper function to build all question data (with base_url for email context)
            q_data = build_question_email_data(question, subscriber, base_url=self.base_url)
            questions_data.append(q_data)

        # Get send day name for footer
        send_day_name = subscriber.get_send_day_name()
        send_hour = subscriber.preferred_send_hour

        try:
            html = render_template(
                'emails/weekly_questions_digest.html',
                questions=questions_data,
                batch_url=batch_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                send_day_name=send_day_name,
                send_hour=send_hour,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for weekly_questions_digest: {e}")
            return False

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=questions[0].id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )

        # Build subject line
        first_question = questions[0].question_text[:50]
        subject = f"5 Questions This Week: {first_question}..."

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': subject,
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

        success = self._send_with_retry(email_data)

        if success:
            subscriber.last_weekly_email_sent = utcnow_naive()
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=subject,
                    question_subscriber_id=subscriber.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

        return success

    def send_monthly_questions_digest(self, subscriber, questions) -> bool:
        """
        Send monthly digest email with 10 questions to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            questions: List of DailyQuestion objects (up to 10)

        Returns:
            bool: Success status
        """
        from app.daily.utils import get_discussion_stats_for_question

        if not questions:
            logger.warning(f"No questions provided for monthly digest to {subscriber.email}")
            return False

        # Build URLs with question IDs for batch page
        question_ids = ','.join(str(q.id) for q in questions)
        batch_url = f"{self.base_url}/daily/weekly?token={subscriber.magic_token}&questions={question_ids}"
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
        unsubscribe_url = f"{self.base_url}/daily/unsubscribe/{subscriber.magic_token}"

        # Build question data with vote URLs, discussion stats, and source articles
        from app.daily.utils import build_question_email_data
        
        questions_data = []
        for question in questions:
            # Use DRY helper function to build all question data (with base_url for email context)
            q_data = build_question_email_data(question, subscriber, base_url=self.base_url)
            questions_data.append(q_data)

        try:
            # Reuse weekly digest template but with different title
            html = render_template(
                'emails/weekly_questions_digest.html',
                questions=questions_data,
                batch_url=batch_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                send_day_name='Monthly',
                send_hour=9,
                base_url=self.base_url,
                is_monthly=True
            )
        except Exception as e:
            logger.error(f"Template rendering failed for monthly_questions_digest: {e}")
            return False

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=questions[0].id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )

        # Build subject line
        first_question = questions[0].question_text[:50]
        subject = f"10 Questions This Month: {first_question}..."

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': subject,
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

        success = self._send_with_retry(email_data)

        if success:
            subscriber.last_weekly_email_sent = utcnow_naive()  # Reuse field for monthly tracking
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=subject,
                    question_subscriber_id=subscriber.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

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

        # Generate question-specific vote URLs using helper (DRY)
        vote_urls = self._build_vote_urls(subscriber, question.id)

        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."

        try:
            from app.daily.utils import get_source_articles_for_question
            source_articles = get_source_articles_for_question(question, limit=3)
        except Exception:
            source_articles = []
        
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
            vote_agree_url=vote_urls['agree'],
            vote_disagree_url=vote_urls['disagree'],
            vote_unsure_url=vote_urls['unsure'],
            base_url=self.base_url,
            source_articles=source_articles
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

                batch_errors = batch_result.get('errors', [])
                is_validation_failure = (
                    batch_result['sent'] == 0
                    and batch_result['failed'] > 0
                    and any('422' in str(e) for e in batch_errors)
                )

                if is_validation_failure:
                    # Batch rejected by Resend due to a bad address (422).
                    # Resend doesn't say which one, so fall back to individual sends.
                    # Any address that also fails individually is invalid — deactivate
                    # it so it never blocks future batches again.
                    logger.warning(
                        f"Batch rejected with 422 (bad address in batch of {len(batch_emails)}); "
                        f"falling back to individual sends to identify the invalid address."
                    )
                    individual_sent = 0
                    individual_failed = 0
                    for sub, payload in zip(batch_subscribers, batch_emails):
                        ok = self._send_with_retry(payload, use_rate_limit=True)
                        if ok:
                            individual_sent += 1
                            sub.last_email_sent = utcnow_naive()
                            try:
                                from app.lib.email_analytics import EmailAnalytics
                                EmailAnalytics.record_send(
                                    email=sub.email,
                                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                                    subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                                    question_subscriber_id=sub.id,
                                    daily_question_id=question.id
                                )
                            except Exception as analytics_error:
                                logger.warning(f"Failed to record analytics for {sub.email}: {analytics_error}")
                        else:
                            individual_failed += 1
                            # Permanently deactivate — bad address that blocks everyone else.
                            try:
                                sub.is_active = False
                                sub.unsubscribe_reason = 'invalid_email'
                                sub.unsubscribed_at = utcnow_naive()
                                logger.warning(
                                    f"Deactivated subscriber {sub.id} <{sub.email}> — "
                                    f"individual send failed after batch 422; address is invalid."
                                )
                            except Exception as deactivate_err:
                                logger.error(f"Failed to deactivate subscriber {sub.id}: {deactivate_err}")
                    results['sent'] += individual_sent
                    results['failed'] += individual_failed
                    results['errors'].extend(batch_errors)
                else:
                    results['sent'] += batch_result['sent']
                    results['failed'] += batch_result['failed']
                    results['errors'].extend(batch_errors)

                # Update last_email_sent for successful batch sends
                if batch_result['sent'] > 0:
                    for subscriber in batch_subscribers:
                        subscriber.last_email_sent = utcnow_naive()
                        
                        # Record analytics event for each successful send
                        try:
                            from app.lib.email_analytics import EmailAnalytics
                            EmailAnalytics.record_send(
                                email=subscriber.email,
                                category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                                subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                                question_subscriber_id=subscriber.id,
                                daily_question_id=question.id
                            )
                        except Exception as analytics_error:
                            logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

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


def send_verification_email(user, verification_url: str) -> bool:
    """
    Send a standalone verification email via Resend (used for resends after expiry).
    """
    try:
        client = get_resend_client()
        return client.send_verification_email(user, verification_url)
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
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
        notification_type: 'new_participant', 'new_response', 'discussion_update', or 'discussion_active'
        additional_data: Optional additional template data

    Returns:
        bool: Success status
    """
    try:
        client = get_resend_client()

        # Generate discussion URL
        base_url = client.base_url
        discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"

        is_host = user.id == discussion.creator_id

        # Prepare notification-specific content (align with in-app copy in email_utils)
        if notification_type == 'new_participant':
            subject = "New participant in your discussion"
            message = f"Someone new has joined your discussion '{discussion.title}'"
        elif notification_type == 'new_response':
            if is_host:
                subject = "New activity in your discussion"
                message = f"There's new activity in your discussion '{discussion.title}'"
            else:
                subject = "New activity in a discussion you follow"
                message = (
                    f"There's new activity in a discussion you're following: '{discussion.title}'"
                )
        elif notification_type == 'discussion_update':
            subject = f"Update: {discussion.title}"
            message = f"A new update was posted to '{discussion.title}'"
        else:
            subject = "Activity in your discussion"
            message = f"There's been activity in your discussion '{discussion.title}'"

        # Render using the standard base email template
        settings_url = f"{base_url}/settings"
        html_content = render_template(
            'emails/discussion_notification.html',
            username=user.username or 'there',
            subject=subject,
            message=message,
            discussion_title=discussion.title,
            discussion_url=discussion_url,
            notification_type=notification_type,
            settings_url=settings_url,
            base_url=base_url,
        )

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


def send_org_invitation_email(email: str, org_name: str, inviter_name: str, invite_url: str, role: str = 'editor', invitee_name: str = '') -> bool:
    """
    Send an organisation team invitation email for the paid Briefings product.

    This is used when a company-profile owner or admin invites a new member to
    their paid briefings workspace (Team / Enterprise plan). It is distinct from
    the Daily Brief subscription emails and from programme steward invites.

    Args:
        email:        Recipient email address.
        org_name:     Company/organisation name shown in the email.
        inviter_name: Display name of the person who sent the invite.
        invite_url:   Full URL the recipient clicks to accept (contains the token).
        role:         Role being granted – 'admin', 'editor', or 'viewer'.
        invitee_name: Optional first name for a personalised greeting.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    try:
        client = get_resend_client()
        expiry_days = int(os.environ.get('PARTNER_INVITE_EXPIRY_DAYS', '7'))
        html = render_template(
            'emails/org_member_invite.html',
            org_name=org_name,
            inviter_name=inviter_name,
            invite_url=invite_url,
            role=role.capitalize(),
            invitee_name=invitee_name,
            expiry_days=expiry_days,
            base_url=client.base_url,
        )
        email_data = {
            'from': client.from_email,
            'to': [email],
            'subject': f"You've been invited to join {org_name} on Society Speaks",
            'html': html,
        }
        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Org invitation email sent to {email} for org '{org_name}'")
        else:
            logger.error(f"Failed to send org invitation email to {email}")
        return success
    except Exception as e:
        logger.error(f"Failed to send org invitation email to {email}: {e}")
        return False


def _send_user_transactional_email(
    user,
    template: str,
    subject: str,
    context: Dict[str, Any],
    client=None,
) -> bool:
    """Render and send a transactional email to a single user via Resend.

    Handles client lookup, template rendering, sending, and logging.
    'context' is merged with username and base_url automatically.
    """
    recipient = getattr(user, 'email', None)
    if not recipient:
        logger.error(f"Failed to send '{subject}': user has no email")
        return False

    username = getattr(user, 'username', None) or 'there'
    try:
        client = client or get_resend_client()
        html = render_template(
            template,
            username=username,
            base_url=client.base_url,
            **context,
        )
        email_data = {
            'from': client.from_email,
            'to': [recipient],
            'subject': subject,
            'html': html,
        }
        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Sent '{subject}' to {recipient}")
        else:
            logger.error(f"Failed to send '{subject}' to {recipient}")
        return success
    except Exception as e:
        logger.error(f"Failed to send '{subject}' to {recipient}: {e}")
        return False


def send_trial_ending_email(user, days_remaining: int = 3, upgrade_url: Optional[str] = None) -> bool:
    """
    Notify a paid-briefings subscriber that their 30-day free trial is ending soon.

    Triggered by the Stripe `customer.subscription.trial_will_end` webhook (fires
    3 days before trial end).  This is for the paid Briefings product only — it is
    unrelated to the Daily Brief newsletter subscription.

    Args:
        user:           User object (must have .email and .username).
        days_remaining: Days left in the trial (typically 3 from Stripe webhook).
        upgrade_url:    Full URL to the plans/pricing page.  Callers in a request
                        context should pass url_for('briefing.landing', _external=True).
                        Defaults to base_url + '/briefings/landing' for contexts
                        where url_for is unavailable (e.g. scheduled jobs).

    Returns:
        bool: True if sent successfully.
    """
    client = None
    if not upgrade_url:
        try:
            client = get_resend_client()
            upgrade_url = f"{client.base_url}/briefings/landing"
        except Exception:
            upgrade_url = '/briefings/landing'
    return _send_user_transactional_email(
        user,
        'emails/trial_ending.html',
        f"Your free trial ends in {days_remaining} day{'s' if days_remaining != 1 else ''} — keep your briefings going",
        {'days_remaining': days_remaining, 'upgrade_url': upgrade_url},
        client=client,
    )


def send_subscription_cancelled_email(user, resubscribe_url: Optional[str] = None, briefing_count: int = 0) -> bool:
    """
    Notify a user that their subscription has been cancelled and their briefings paused.

    Triggered by the Stripe `customer.subscription.deleted` webhook.

    Args:
        user:             User object (must have .email and .username).
        resubscribe_url:  Full URL to the plans/pricing page.
        briefing_count:   Number of briefings that were paused.

    Returns:
        bool: True if sent successfully.
    """
    client = None
    if not resubscribe_url:
        try:
            client = get_resend_client()
            resubscribe_url = f"{client.base_url}/briefings/landing"
        except Exception:
            resubscribe_url = '/briefings/landing'
    return _send_user_transactional_email(
        user,
        'emails/subscription_cancelled.html',
        'Your Society Speaks subscription has ended',
        {'resubscribe_url': resubscribe_url, 'briefing_count': briefing_count},
        client=client,
    )


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

    # Get all active subscribers with 'daily' frequency (filter for weekly digest feature)
    total_subscribers = DailyQuestionSubscriber.query.filter_by(
        is_active=True,
        email_frequency='daily'
    ).count()

    if total_subscribers == 0:
        logger.info("No active daily frequency subscribers to send daily question to")
        return 0

    logger.info(
        f"Starting daily question #{question.question_number} send to {total_subscribers} daily frequency subscribers "
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
        # Get chunk of subscribers (filtered by daily frequency)
        subscribers = DailyQuestionSubscriber.query.filter_by(
            is_active=True,
            email_frequency='daily'
        ).order_by(DailyQuestionSubscriber.id)\
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


def send_journey_reminder_email(
    subscription,
    programme,
    next_discussion,
    theme_checklist: list,
    completed_themes: int,
    total_themes: int,
    base_url: str = None,
) -> bool:
    """
    Send a progress-based journey reminder email.

    Args:
        subscription: JourneyReminderSubscription instance
        programme: Programme instance
        next_discussion: Discussion instance for the next incomplete theme
        theme_checklist: list of dicts with keys 'name' and 'is_complete'
        completed_themes: int — how many themes the user has finished
        total_themes: int — total themes in the journey
        base_url: override base URL (defaults to client.base_url)

    Returns:
        bool: True if sent successfully
    """
    try:
        client = get_resend_client()
        _base = base_url or client.base_url

        resume_token = subscription.generate_resume_token(expires_hours=72)
        programme_url = f"{_base}/programmes/{programme.slug}"
        continue_url = (
            f"{programme_url}?jrt={resume_token}"
            if not subscription.user_id
            else f"{_base}/programmes/{programme.slug}"
        )
        unsubscribe_url = f"{_base}/programmes/{programme.slug}/journey-reminder/unsubscribe?token={resume_token}"

        pct = int((completed_themes / total_themes * 100)) if total_themes else 0
        next_theme_name = (
            getattr(next_discussion, 'programme_theme', None) or next_discussion.title
        )
        next_statement_count = getattr(next_discussion, 'statement_count', 7) or 7

        html = render_template(
            'emails/journey_reminder.html',
            username=subscription.email.split('@')[0] if not subscription.user_id else (
                subscription.user.username if subscription.user else subscription.email.split('@')[0]
            ),
            programme_name=programme.name,
            programme_url=programme_url,
            continue_url=continue_url,
            unsubscribe_url=unsubscribe_url,
            completed_themes=completed_themes,
            total_themes=total_themes,
            pct=pct,
            next_theme_name=next_theme_name,
            next_statement_count=next_statement_count,
            theme_checklist=theme_checklist,
            is_anonymous=not subscription.user_id,
        )

        email_data = {
            'from': client.from_email,
            'to': [subscription.email],
            'subject': f"Continue your journey: {next_theme_name} — Society Speaks",
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
            },
        }

        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Journey reminder sent to {subscription.email} for {programme.slug}")
        else:
            logger.error(f"Failed to send journey reminder to {subscription.email}")
        return success

    except Exception as e:
        logger.error(f"Failed to send journey reminder email: {e}", exc_info=True)
        return False
