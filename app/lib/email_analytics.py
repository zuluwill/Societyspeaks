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
from app.models import (
    EmailEvent, User, DailyBriefSubscriber, 
    DailyQuestionSubscriber, DailyBrief, DailyQuestion, BriefRecipient
)

logger = logging.getLogger(__name__)

# First-party click-tracking URL substring. Matches the route registered at
# app/brief/routes.py (`brief.brief_track_click`, `/brief/track/click/<id>`).
# If that blueprint path ever changes, update this constant too — grep for the
# other end by the constant name.
_FIRST_PARTY_CLICK_TRACKER_PATH = "/brief/track/click"


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
            
            # Extract recipient email
            to_list = data.get('to', [])
            recipient_email = to_list[0] if to_list else None
            
            if not recipient_email:
                logger.warning("Webhook payload missing recipient email")
                return None
            
            # Normalize event type (remove 'email.' prefix)
            normalized_type = event_type.replace('email.', '')

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
            
            # Handle status updates for bounces/complaints
            if normalized_type in [cls.EVENT_BOUNCED, cls.EVENT_COMPLAINED]:
                cls._handle_deliverability_issue(recipient_email, normalized_type, bounce_type)
            
            db.session.commit()
            logger.info(f"Recorded webhook event: {normalized_type} for {recipient_email}")
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

        brief_subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
        briefing_recipient = BriefRecipient.query.filter_by(email=email).first()
        question_subscriber = DailyQuestionSubscriber.query.filter_by(email=email).first()
        user = User.query.filter_by(email=email).first()

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

    @classmethod
    def _count_soft_bounces(cls, email: str) -> int:
        """Return the total number of soft-bounce events recorded for *email*."""
        try:
            return EmailEvent.query.filter_by(
                recipient_email=email,
                event_type=cls.EVENT_BOUNCED,
                bounce_type='soft',
            ).count()
        except Exception as e:
            logger.warning(f"Could not count soft bounces for {email}: {e}")
            return 0

    @classmethod
    def _handle_deliverability_issue(cls, email: str, event_type: str, bounce_type: Optional[str] = None):
        """
        Handle bounces and complaints by updating subscriber status.
        DRY: Centralized deliverability handling.

        Hard bounces and complaints suppress immediately.
        Soft bounces are suppressed once SOFT_BOUNCE_SUPPRESS_THRESHOLD is reached
        (counted across all recorded EmailEvent rows for the address).
        """
        try:
            is_hard_bounce = event_type == cls.EVENT_BOUNCED and bounce_type == 'hard'
            is_complaint = event_type == cls.EVENT_COMPLAINED

            # For soft bounces, check whether the threshold has been crossed.
            # The current event has already been written to EmailEvent before this
            # method is called, so the count includes the event we just recorded.
            suppress_soft = False
            if event_type == cls.EVENT_BOUNCED and bounce_type == 'soft':
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

            should_suppress = is_hard_bounce or is_complaint or suppress_soft

            if not should_suppress:
                return

            # Update brief subscriber
            brief_sub = DailyBriefSubscriber.query.filter_by(email=email).first()
            if brief_sub:
                if is_complaint:
                    brief_sub.status = 'unsubscribed'
                    brief_sub.unsubscribed_at = utcnow_naive()
                    logger.info(f"Unsubscribed brief subscriber {email} due to complaint")
                else:
                    brief_sub.status = 'bounced'
                    reason = 'hard bounce' if is_hard_bounce else f'repeated soft bounces'
                    logger.info(f"Marked brief subscriber {email} as bounced ({reason})")

            # Update question subscriber
            question_sub = DailyQuestionSubscriber.query.filter_by(email=email).first()
            if question_sub:
                question_sub.is_active = False
                if is_complaint:
                    logger.info(f"Deactivated question subscriber {email} due to complaint")
                else:
                    reason = 'hard bounce' if is_hard_bounce else 'repeated soft bounces'
                    logger.info(f"Deactivated question subscriber {email} ({reason})")

            # Update briefing recipients (briefing pipeline)
            briefing_recipient = BriefRecipient.query.filter_by(email=email).first()
            if briefing_recipient:
                briefing_recipient.status = 'unsubscribed'
                briefing_recipient.unsubscribed_at = utcnow_naive()
                if is_complaint:
                    logger.info(f"Unsubscribed briefing recipient {email} due to complaint")
                else:
                    reason = 'hard bounce' if is_hard_bounce else 'repeated soft bounces'
                    logger.info(f"Unsubscribed briefing recipient {email} ({reason})")

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
