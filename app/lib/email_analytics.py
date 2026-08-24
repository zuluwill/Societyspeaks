"""
Email Analytics Service

Unified, DRY service for tracking and analyzing email events across all email types.
Integrates with Resend webhooks and provides admin reporting.

Usage:
    from app.lib.email_analytics import EmailAnalytics
    
    # Record an event from webhook
    EmailAnalytics.record_from_webhook(payload)
    
    # Record a sent email
    EmailAnalytics.record_send(
        email='user@example.com',
        category=EmailAnalytics.CATEGORY_AUTH,
        resend_id='abc123',
        subject='Welcome!'
    )
    
    # Get stats for admin dashboard
    stats = EmailAnalytics.get_dashboard_stats()
"""

import logging
from datetime import timedelta
from app.lib.time import utcnow_naive
from typing import Dict, Any, Optional, List, Tuple
from flask import current_app, has_app_context
from app import db
from app.email_utils import extract_clean_email
from app.models import (
    EmailEvent, User, DailyBriefSubscriber,
    DailyQuestionSubscriber, DailyBrief, DailyQuestion, BriefRecipient,
    GameReminderSubscription, JourneyReminderSubscription,
)

logger = logging.getLogger(__name__)

# First-party click-tracking URL substring. Matches the route registered at
# app/brief/routes.py (`brief.brief_track_click`, `/brief/track/click/<id>`).
# If that blueprint path ever changes, update this constant too — grep for the
# other end by the constant name.
_FIRST_PARTY_CLICK_TRACKER_PATH = "/brief/track/click"
SOFT_BOUNCE_WINDOW_DAYS = 30
# Automated bounce handling must not overwrite these — complaint/unsub is a
# legal state; Resend suppression is stronger than our own bounce flag.
_DELIVERABILITY_STATUS_LOCK = frozenset({'unsubscribed', 'suppressed'})


def recipient_email_from_webhook(data: Dict[str, Any]) -> Optional[str]:
    """Pull a bare address out of Resend's `to` field (list, string, or dict)."""
    to_raw = data.get('to') if isinstance(data, dict) else None
    if to_raw is None:
        return None
    if isinstance(to_raw, (list, tuple)):
        first = to_raw[0] if to_raw else None
    else:
        first = to_raw
    if isinstance(first, dict):
        first = first.get('email') or first.get('address')
    if not first:
        return None
    return extract_clean_email(str(first))


def _email_equals(column, email: str):
    from sqlalchemy import func
    return func.lower(column) == email.strip().lower()


def address_cannot_receive_mail(email: Optional[str]) -> bool:
    """True when marketing mail to this address would bounce or is legally blocked.

    Does not apply to transactional auth mail (password reset), which must still
    be attempted if the user requests it.
    """
    if not email or not str(email).strip():
        return False
    from sqlalchemy import and_, func, or_

    if DailyBriefSubscriber.query.filter(
        _email_equals(DailyBriefSubscriber.email, email),
        DailyBriefSubscriber.status.in_(('bounced', 'suppressed')),
    ).first():
        return True
    cutoff = utcnow_naive() - timedelta(days=SOFT_BOUNCE_WINDOW_DAYS)
    return (
        EmailEvent.query.filter(
            _email_equals(EmailEvent.recipient_email, email),
            EmailEvent.created_at >= cutoff,
            or_(
                EmailEvent.event_type == EmailEvent.EVENT_COMPLAINED,
                EmailEvent.event_type == 'suppressed',
                and_(
                    EmailEvent.event_type == EmailEvent.EVENT_BOUNCED,
                    func.lower(EmailEvent.bounce_type).in_(('hard', 'permanent')),
                ),
            ),
        ).first()
        is not None
    )


class EmailAnalytics:
    """
    Unified email analytics service.
    DRY: All email tracking goes through this single service.
    """

    # Re-exported from EmailEvent so there is a single source of truth for
    # category / event-type strings. External call sites keep using
    # ``EmailAnalytics.CATEGORY_*`` / ``EmailAnalytics.EVENT_*``.
    CATEGORY_AUTH = EmailEvent.CATEGORY_AUTH
    CATEGORY_DAILY_BRIEF = EmailEvent.CATEGORY_DAILY_BRIEF
    CATEGORY_DAILY_QUESTION = EmailEvent.CATEGORY_DAILY_QUESTION
    CATEGORY_DISCUSSION = EmailEvent.CATEGORY_DISCUSSION
    CATEGORY_ADMIN = EmailEvent.CATEGORY_ADMIN

    EVENT_SENT = EmailEvent.EVENT_SENT
    EVENT_DELIVERED = EmailEvent.EVENT_DELIVERED
    EVENT_OPENED = EmailEvent.EVENT_OPENED
    EVENT_CLICKED = EmailEvent.EVENT_CLICKED
    EVENT_BOUNCED = EmailEvent.EVENT_BOUNCED
    EVENT_COMPLAINED = EmailEvent.EVENT_COMPLAINED
    # Resend refused to send: the address is on its suppression list
    # (prior hard bounce or complaint). Not defined on EmailEvent because it
    # only ever arrives via webhook.
    EVENT_SUPPRESSED = 'suppressed'

    @classmethod
    def record_send(cls, email: str, category: str, resend_id: Optional[str] = None,
                    subject: Optional[str] = None, user_id: Optional[int] = None,
                    brief_subscriber_id: Optional[int] = None, question_subscriber_id: Optional[int] = None,
                    brief_id: Optional[int] = None, daily_question_id: Optional[int] = None) -> Optional[EmailEvent]:
        """
        Record that an email was sent.
        Call this after successfully sending via Resend.
        
        Returns:
            EmailEvent: The created event record, or None if failed
        """
        try:
            event = EmailEvent.record_event(
                recipient_email=email,
                event_type=cls.EVENT_SENT,
                email_category=category,
                resend_email_id=resend_id,
                email_subject=subject,
                user_id=user_id,
                brief_subscriber_id=brief_subscriber_id,
                question_subscriber_id=question_subscriber_id,
                brief_id=brief_id,
                daily_question_id=daily_question_id
            )
            if event is None:
                logger.warning(f"EmailEvent.record_event returned None for {email}")
                return None
            db.session.commit()
            logger.debug(f"Recorded send event for {email} ({category})")
            return event
        except Exception as e:
            logger.error(f"Failed to record send event: {e}")
            db.session.rollback()
            return None

    @classmethod
    def record_click(
        cls,
        email: str,
        category: str,
        click_url: str,
        brief_subscriber_id: Optional[int] = None,
        question_subscriber_id: Optional[int] = None,
        brief_id: Optional[int] = None,
        daily_question_id: Optional[int] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[EmailEvent]:
        """
        Record that a tracked link in an email was clicked.
        Call this from click-tracking redirect endpoints.

        Returns:
            EmailEvent: The created event record, or None if failed
        """
        try:
            event = EmailEvent.record_event(
                recipient_email=email,
                event_type=cls.EVENT_CLICKED,
                email_category=category,
                click_url=click_url,
                brief_subscriber_id=brief_subscriber_id,
                question_subscriber_id=question_subscriber_id,
                brief_id=brief_id,
                daily_question_id=daily_question_id,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            if event is None:
                logger.warning(f"EmailEvent.record_event returned None for click from {email}")
                return None
            db.session.commit()
            logger.debug(f"Recorded click event for {email} ({category}) -> {click_url[:80]}")
            return event
        except Exception as e:
            logger.error(f"Failed to record click event: {e}")
            db.session.rollback()
            return None

    @classmethod
    def record_from_webhook(cls, payload: Dict[str, Any]) -> Optional[EmailEvent]:
        """
        Process a Resend webhook payload and record the event.
        DRY: Single method handles all webhook event types.
        
        Args:
            payload: Resend webhook payload
            
        Returns:
            EmailEvent or None if processing failed
        """
        try:
            event_type = payload.get('type', '')
            data = payload.get('data', {})
            
            if not event_type:
                logger.warning("Webhook payload missing event type")
                return None
            
            # Extract recipient email (Resend may send a list, a string, or
            # "Name <addr>"; look up subscribers case-insensitively).
            recipient_email = recipient_email_from_webhook(data)
            if not recipient_email:
                logger.warning("Webhook payload missing recipient email")
                return None
            canonical = (
                DailyBriefSubscriber.query.filter(
                    _email_equals(DailyBriefSubscriber.email, recipient_email)
                ).first()
                or DailyQuestionSubscriber.query.filter(
                    _email_equals(DailyQuestionSubscriber.email, recipient_email)
                ).first()
                or User.query.filter(_email_equals(User.email, recipient_email)).first()
            )
            if canonical is not None and getattr(canonical, 'email', None):
                recipient_email = canonical.email
            
            # Normalize event type (remove 'email.' prefix)
            normalized_type = event_type.replace('email.', '')

            # Ignore Resend email.sent by default: sends are recorded first-party
            # at API-call time without a resend_email_id, so the idempotency check
            # below cannot dedupe against them and webhook sends would double-count.
            if normalized_type == cls.EVENT_SENT:
                if not (
                    has_app_context()
                    and current_app.config.get(
                        "EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_SENDS", False
                    )
                ):
                    logger.info(
                        "Skipping Resend email.sent webhook (first-party send recording is authoritative)"
                    )
                    return None

            # Optional: ignore Resend email.clicked when first-party tracking is authoritative
            # (set EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_CLICKS=false; see admin email analytics).
            if normalized_type == cls.EVENT_CLICKED:
                if has_app_context() and not current_app.config.get(
                    "EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_CLICKS", True
                ):
                    logger.info(
                        "Skipping Resend email.clicked webhook (EMAIL_ANALYTICS_RECORD_RESEND_WEBHOOK_CLICKS is false)"
                    )
                    return None
                click_preview = ""
                click_block = data.get("click") or {}
                if isinstance(click_block, dict):
                    click_preview = (
                        click_block.get("link")
                        or click_block.get("url")
                        or ""
                    )
                if _FIRST_PARTY_CLICK_TRACKER_PATH in (click_preview or ""):
                    logger.info(
                        "Skipping Resend email.clicked; link uses first-party brief tracker URL"
                    )
                    return None

            # Durable idempotency: ignore duplicate webhook events for same
            # resend_email_id + event_type + recipient combination.
            resend_email_id = data.get('email_id')
            if resend_email_id:
                duplicate = EmailEvent.query.filter_by(
                    resend_email_id=resend_email_id,
                    event_type=normalized_type,
                    recipient_email=recipient_email
                ).first()
                if duplicate:
                    logger.info(
                        f"Duplicate webhook event ignored: {normalized_type} "
                        f"for {recipient_email} ({resend_email_id})"
                    )
                    duplicate.was_created = False
                    return duplicate
            
            # Determine email category and find related records
            category, context = cls._identify_email_context(recipient_email, data)
            
            # Extract additional data based on event type
            click_url: Optional[str] = None
            bounce_type: Optional[str] = None
            complaint_type: Optional[str] = None
            
            if normalized_type == cls.EVENT_CLICKED:
                click_data = data.get('click', {})
                click_url = click_data.get('link') or click_data.get('url')
            elif normalized_type == cls.EVENT_BOUNCED:
                bounce_data = data.get('bounce', {})
                bounce_type = bounce_data.get('type', 'unknown')
            elif normalized_type == cls.EVENT_COMPLAINED:
                complaint_data = data.get('complaint', {})
                complaint_type = complaint_data.get('type', 'spam')
            
            # Record the event
            event = EmailEvent.record_event(
                recipient_email=recipient_email,
                event_type=normalized_type,
                email_category=category,
                resend_email_id=resend_email_id,
                email_subject=data.get('subject'),
                user_id=context.get('user_id'),
                brief_subscriber_id=context.get('brief_subscriber_id'),
                question_subscriber_id=context.get('question_subscriber_id'),
                brief_id=context.get('brief_id'),
                click_url=click_url,
                bounce_type=bounce_type,
                complaint_type=complaint_type
            )
            
            if event is None:
                logger.warning(f"Failed to create event for webhook: {normalized_type}")
                return None
            
            # Handle status updates for bounces/complaints/suppressions
            if normalized_type in [cls.EVENT_BOUNCED, cls.EVENT_COMPLAINED, cls.EVENT_SUPPRESSED]:
                cls._handle_deliverability_issue(recipient_email, normalized_type, bounce_type)
            
            db.session.commit()
            logger.info(f"Recorded webhook event: {normalized_type} for {recipient_email}")
            # was_created lets callers distinguish a fresh event from a
            # returned duplicate (svix retries) when updating counters.
            event.was_created = True
            return event
            
        except Exception as e:
            logger.error(f"Failed to process webhook: {e}")
            db.session.rollback()
            return None

    @classmethod
    def _identify_email_context(cls, email: str, data: Dict) -> tuple:
        """
        Identify email category and related records based on recipient.
        Subscriber/list membership takes precedence over User heuristics so
        webhook rows match categories used at send time (record_send).

        Returns:
            tuple: (category, context_dict)
        """
        subject = (data.get("subject") or "").lower()
        context: Dict[str, Any] = {}

        brief_subscriber = DailyBriefSubscriber.query.filter(
            _email_equals(DailyBriefSubscriber.email, email)
        ).first()
        briefing_recipient = BriefRecipient.query.filter(
            _email_equals(BriefRecipient.email, email)
        ).first()
        question_subscriber = DailyQuestionSubscriber.query.filter(
            _email_equals(DailyQuestionSubscriber.email, email)
        ).first()
        user = User.query.filter(_email_equals(User.email, email)).first()

        if brief_subscriber:
            context["brief_subscriber_id"] = brief_subscriber.id
        if question_subscriber:
            context["question_subscriber_id"] = question_subscriber.id
        if user:
            context["user_id"] = user.id

        # Precedence: list membership first (matches send-time categories); subject only
        # disambiguates when the same address appears on multiple lists.
        if brief_subscriber and briefing_recipient:
            if any(
                k in subject
                for k in ("question of the day", "daily question")
            ):
                category = cls.CATEGORY_DAILY_QUESTION
            else:
                category = cls.CATEGORY_DAILY_BRIEF
        elif brief_subscriber and question_subscriber:
            if any(
                k in subject
                for k in (
                    "question of the day",
                    "daily question",
                    "your question",
                )
            ):
                category = cls.CATEGORY_DAILY_QUESTION
            else:
                category = cls.CATEGORY_DAILY_BRIEF
        elif brief_subscriber or briefing_recipient:
            category = cls.CATEGORY_DAILY_BRIEF
        elif question_subscriber:
            category = cls.CATEGORY_DAILY_QUESTION
        elif user:
            if "password" in subject or "reset" in subject:
                category = cls.CATEGORY_AUTH
            elif "welcome" in subject:
                category = cls.CATEGORY_AUTH
            elif "discussion" in subject or "notification" in subject:
                category = cls.CATEGORY_DISCUSSION
            else:
                category = cls.CATEGORY_AUTH
        else:
            category = cls.CATEGORY_AUTH

        return category, context

    # Number of soft bounces before an address is suppressed.
    SOFT_BOUNCE_SUPPRESS_THRESHOLD = 3
    # Resend sends Permanent / Transient / Undetermined. We also accept the
    # older hard/soft labels so a single comparison covers both vocabularies.
    _HARD_BOUNCE_TYPES = frozenset({'hard', 'permanent'})

    @classmethod
    def classify_bounce_type(cls, bounce_type: Optional[str]) -> str:
        """Map a Resend (or legacy) bounce.type to 'hard' or 'soft'."""
        token = (bounce_type or '').strip().lower()
        if token in cls._HARD_BOUNCE_TYPES:
            return 'hard'
        return 'soft'

    @classmethod
    def _count_soft_bounces(cls, email: str) -> int:
        """Return soft/transient bounce events recorded for *email*.

        Counts anything that is not a hard/Permanent bounce, including
        historical Resend ``Transient`` rows written before we normalised
        the vocabulary.
        """
        try:
            from sqlalchemy import func, or_

            cutoff = utcnow_naive() - timedelta(days=SOFT_BOUNCE_WINDOW_DAYS)
            return EmailEvent.query.filter(
                _email_equals(EmailEvent.recipient_email, email),
                EmailEvent.event_type == cls.EVENT_BOUNCED,
                EmailEvent.created_at >= cutoff,
                or_(
                    EmailEvent.bounce_type.is_(None),
                    func.lower(EmailEvent.bounce_type).notin_(
                        tuple(cls._HARD_BOUNCE_TYPES)
                    ),
                ),
            ).count()
        except Exception as e:
            logger.warning(f"Could not count soft bounces for {email}: {e}")
            return 0

    @classmethod
    def _handle_deliverability_issue(cls, email: str, event_type: str, bounce_type: Optional[str] = None):
        """
        Handle bounces and complaints by updating subscriber status.
        DRY: Centralized deliverability handling.

        Hard/Permanent bounces and complaints suppress immediately.
        Soft/Transient bounces are suppressed once SOFT_BOUNCE_SUPPRESS_THRESHOLD
        is reached (counted across all recorded EmailEvent rows for the address).
        """
        try:
            bounce_class = cls.classify_bounce_type(bounce_type)
            is_hard_bounce = event_type == cls.EVENT_BOUNCED and bounce_class == 'hard'
            is_complaint = event_type == cls.EVENT_COMPLAINED
            is_suppressed = event_type == cls.EVENT_SUPPRESSED

            # For soft bounces, check whether the threshold has been crossed.
            # The current event has already been written to EmailEvent before this
            # method is called, so the count includes the event we just recorded.
            suppress_soft = False
            if event_type == cls.EVENT_BOUNCED and bounce_class == 'soft':
                soft_count = cls._count_soft_bounces(email)
                if soft_count >= cls.SOFT_BOUNCE_SUPPRESS_THRESHOLD:
                    suppress_soft = True
                    logger.warning(
                        f"Soft-bounce threshold reached for {email} "
                        f"({soft_count} soft bounces) — suppressing"
                    )
                else:
                    logger.info(
                        f"Soft bounce recorded for {email} "
                        f"({soft_count}/{cls.SOFT_BOUNCE_SUPPRESS_THRESHOLD} before suppression)"
                    )

            should_suppress = is_hard_bounce or is_complaint or suppress_soft or is_suppressed

            if not should_suppress:
                return

            # Update brief subscriber
            brief_sub = DailyBriefSubscriber.query.filter(
                _email_equals(DailyBriefSubscriber.email, email)
            ).first()
            if brief_sub:
                locked = brief_sub.status in _DELIVERABILITY_STATUS_LOCK
                if is_complaint:
                    brief_sub.status = 'unsubscribed'
                    brief_sub.unsubscribed_at = utcnow_naive()
                    logger.info(f"Unsubscribed brief subscriber {email} due to complaint")
                elif locked:
                    logger.info(
                        f"Leaving brief subscriber {email} as {brief_sub.status} "
                        f"(bounce/suppression must not overwrite unsub or Resend suppression)"
                    )
                elif is_suppressed:
                    # Distinct status: Resend will never deliver to this address,
                    # so it must leave the active pool — but 'suppressed' keeps it
                    # distinguishable from our own bounce handling for audits.
                    brief_sub.status = 'suppressed'
                    logger.info(f"Marked brief subscriber {email} as suppressed (Resend suppression list)")
                else:
                    brief_sub.status = 'bounced'
                    reason = 'hard bounce' if is_hard_bounce else 'repeated soft bounces'
                    logger.info(f"Marked brief subscriber {email} as bounced ({reason})")

            # Update question subscriber
            question_sub = DailyQuestionSubscriber.query.filter(
                _email_equals(DailyQuestionSubscriber.email, email)
            ).first()
            if question_sub and question_sub.is_active:
                question_sub.is_active = False
                if is_complaint:
                    logger.info(f"Deactivated question subscriber {email} due to complaint")
                else:
                    reason = 'hard bounce' if is_hard_bounce else 'repeated soft bounces'
                    logger.info(f"Deactivated question subscriber {email} ({reason})")

            # Update every briefing-recipient row for this address
            for briefing_recipient in BriefRecipient.query.filter(
                _email_equals(BriefRecipient.email, email)
            ).all():
                if briefing_recipient.status == 'unsubscribed':
                    continue
                briefing_recipient.status = 'unsubscribed'
                briefing_recipient.unsubscribed_at = utcnow_naive()
                if is_complaint:
                    logger.info(f"Unsubscribed briefing recipient {email} due to complaint")
                else:
                    reason = 'hard bounce' if is_hard_bounce else 'repeated soft bounces'
                    logger.info(f"Unsubscribed briefing recipient {email} ({reason})")

            now = utcnow_naive()
            pause_reason = 'complaint' if is_complaint else 'bounce'
            for reminder in GameReminderSubscription.query.filter(
                _email_equals(GameReminderSubscription.email, email),
                GameReminderSubscription.unsubscribed_at.is_(None),
            ).all():
                reminder.unsubscribed_at = now
                reminder.unsubscribe_reason = pause_reason
                logger.info(f"Paused game reminder for {email} ({pause_reason})")
            for reminder in JourneyReminderSubscription.query.filter(
                _email_equals(JourneyReminderSubscription.email, email),
                JourneyReminderSubscription.unsubscribed_at.is_(None),
            ).all():
                reminder.unsubscribed_at = now
                logger.info(f"Paused journey reminder for {email} ({pause_reason})")

        except Exception as e:
            logger.error(f"Failed to handle deliverability issue: {e}")

    @classmethod
    def get_dashboard_stats(cls, days: int = 7) -> Dict[str, Any]:
        """
        Get comprehensive stats for admin dashboard.
        DRY: Single method for all dashboard statistics.
        
        Returns:
            Dict with overall stats and per-category breakdowns
        """
        # Overall stats
        overall = EmailEvent.get_stats(days=days)
        
        # Per-category stats
        categories = {}
        for cat in [
            cls.CATEGORY_AUTH,
            cls.CATEGORY_DAILY_BRIEF,
            cls.CATEGORY_DAILY_QUESTION,
            cls.CATEGORY_DISCUSSION,
            cls.CATEGORY_ADMIN,
        ]:
            categories[cat] = EmailEvent.get_stats(email_category=cat, days=days)
        
        # Subscriber counts
        brief_subscribers = DailyBriefSubscriber.query.filter_by(status='active').count()
        question_subscribers = DailyQuestionSubscriber.query.filter_by(is_active=True).count()
        total_users = User.query.count()
        
        return {
            'overall': overall,
            'by_category': categories,
            'subscribers': {
                'brief': brief_subscribers,
                'question': question_subscribers,
                'users': total_users
            },
            'period_days': days
        }

    @classmethod
    def get_recent_events(
        cls,
        category: Optional[str] = None,
        limit: int = 50,
        days: Optional[int] = None
    ) -> List[EmailEvent]:
        """
        Get recent email events for display.
        
        Args:
            category: Filter by category (optional)
            limit: Max events to return
            
        Returns:
            List of EmailEvent objects
        """
        query = EmailEvent.query.order_by(EmailEvent.created_at.desc())
        if category:
            query = query.filter(EmailEvent.email_category == category)
        if days and days > 0:
            cutoff = utcnow_naive() - timedelta(days=days)
            query = query.filter(EmailEvent.created_at >= cutoff)
        return query.limit(limit).all()

    @classmethod
    def get_email_performance(cls, email: str, days: int = 30) -> Dict[str, Any]:
        """
        Get performance metrics for a specific email address.
        Useful for subscriber detail views.
        """
        cutoff = utcnow_naive() - timedelta(days=days)
        
        events = EmailEvent.query.filter(
            EmailEvent.recipient_email == email,
            EmailEvent.created_at >= cutoff
        ).all()
        
        stats = {
            "total_sent": 0,
            "total_delivered": 0,
            "total_opened": 0,
            "total_clicked": 0,
            "total_bounced": 0,
            "total_complained": 0,
            "categories": {},
        }
        
        for event in events:
            normalized_type = EmailEvent.normalize_event_type(event.event_type)
            if normalized_type == cls.EVENT_SENT:
                stats["total_sent"] += 1
            elif normalized_type == cls.EVENT_DELIVERED:
                stats["total_delivered"] += 1
            elif normalized_type == cls.EVENT_OPENED:
                stats["total_opened"] += 1
            elif normalized_type == cls.EVENT_CLICKED:
                stats["total_clicked"] += 1
            elif normalized_type == cls.EVENT_BOUNCED:
                stats["total_bounced"] += 1
            elif normalized_type == cls.EVENT_COMPLAINED:
                stats["total_complained"] += 1
            
            # Track by category
            if event.email_category not in stats["categories"]:
                stats["categories"][event.email_category] = 0
            stats["categories"][event.email_category] += 1
        
        rates = EmailEvent.compute_rate_metrics(
            stats["total_sent"],
            stats["total_delivered"],
            stats["total_opened"],
            stats["total_clicked"],
            stats["total_bounced"],
            stats["total_complained"],
            engagement_basis="delivered",
        )
        stats.update(rates)
        
        return stats


# Convenience functions for common operations
def record_email_sent(email: str, category: str, resend_id: Optional[str] = None, 
                      subject: Optional[str] = None, **kwargs) -> Optional[EmailEvent]:
    """Convenience function to record a sent email."""
    return EmailAnalytics.record_send(email, category, resend_id, subject, **kwargs)


def process_webhook(payload: Dict[str, Any]) -> Optional[EmailEvent]:
    """Convenience function to process a webhook payload."""
    return EmailAnalytics.record_from_webhook(payload)
