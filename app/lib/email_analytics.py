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
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from flask import current_app
from app import db
from app.models import (
    EmailEvent, User, DailyBriefSubscriber, 
    DailyQuestionSubscriber, DailyBrief, DailyQuestion
)

logger = logging.getLogger(__name__)


class EmailAnalytics:
    """
    Unified email analytics service.
    DRY: All email tracking goes through this single service.
    """
    
    # Email categories (mirrors EmailEvent constants)
    CATEGORY_AUTH = 'auth'
    CATEGORY_DAILY_BRIEF = 'daily_brief'
    CATEGORY_DAILY_QUESTION = 'daily_question'
    CATEGORY_DISCUSSION = 'discussion'
    CATEGORY_ADMIN = 'admin'
    
    # Event types
    EVENT_SENT = 'sent'
    EVENT_DELIVERED = 'delivered'
    EVENT_OPENED = 'opened'
    EVENT_CLICKED = 'clicked'
    EVENT_BOUNCED = 'bounced'
    EVENT_COMPLAINED = 'complained'

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
                resend_email_id=data.get('email_id'),
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
        DRY: Centralized logic for email context identification.
        
        Returns:
            tuple: (category, context_dict)
        """
        context = {}
        category = cls.CATEGORY_AUTH  # Default
        
        # Check if it's a brief subscriber
        brief_subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
        if brief_subscriber:
            context['brief_subscriber_id'] = brief_subscriber.id
            # Check subject to distinguish brief from other emails
            subject = data.get('subject', '').lower()
            if 'brief' in subject or 'news' in subject:
                category = cls.CATEGORY_DAILY_BRIEF
        
        # Check if it's a question subscriber
        question_subscriber = DailyQuestionSubscriber.query.filter_by(email=email).first()
        if question_subscriber:
            context['question_subscriber_id'] = question_subscriber.id
            subject = data.get('subject', '').lower()
            if 'question' in subject or 'daily' in subject:
                category = cls.CATEGORY_DAILY_QUESTION
        
        # Check if it's a registered user
        user = User.query.filter_by(email=email).first()
        if user:
            context['user_id'] = user.id
            subject = data.get('subject', '').lower()
            if 'password' in subject or 'reset' in subject:
                category = cls.CATEGORY_AUTH
            elif 'welcome' in subject:
                category = cls.CATEGORY_AUTH
            elif 'discussion' in subject or 'notification' in subject:
                category = cls.CATEGORY_DISCUSSION
        
        return category, context

    @classmethod
    def _handle_deliverability_issue(cls, email: str, event_type: str, bounce_type: Optional[str] = None):
        """
        Handle bounces and complaints by updating subscriber status.
        DRY: Centralized deliverability handling.
        """
        try:
            # Update brief subscriber
            brief_sub = DailyBriefSubscriber.query.filter_by(email=email).first()
            if brief_sub:
                if event_type == cls.EVENT_BOUNCED and bounce_type == 'hard':
                    brief_sub.status = 'bounced'
                    logger.info(f"Marked brief subscriber {email} as bounced")
                elif event_type == cls.EVENT_COMPLAINED:
                    brief_sub.status = 'unsubscribed'
                    brief_sub.unsubscribed_at = datetime.utcnow()
                    logger.info(f"Unsubscribed brief subscriber {email} due to complaint")
            
            # Update question subscriber
            question_sub = DailyQuestionSubscriber.query.filter_by(email=email).first()
            if question_sub:
                if event_type == cls.EVENT_BOUNCED and bounce_type == 'hard':
                    question_sub.is_active = False
                    logger.info(f"Deactivated question subscriber {email} due to bounce")
                elif event_type == cls.EVENT_COMPLAINED:
                    question_sub.is_active = False
                    logger.info(f"Deactivated question subscriber {email} due to complaint")
                    
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
        for cat in [cls.CATEGORY_AUTH, cls.CATEGORY_DAILY_BRIEF, 
                    cls.CATEGORY_DAILY_QUESTION, cls.CATEGORY_DISCUSSION]:
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
    def get_recent_events(cls, category: Optional[str] = None, limit: int = 50) -> List[EmailEvent]:
        """
        Get recent email events for display.
        
        Args:
            category: Filter by category (optional)
            limit: Max events to return
            
        Returns:
            List of EmailEvent objects
        """
        return EmailEvent.get_recent_events(email_category=category, limit=limit)

    @classmethod
    def get_email_performance(cls, email: str, days: int = 30) -> Dict[str, Any]:
        """
        Get performance metrics for a specific email address.
        Useful for subscriber detail views.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        events = EmailEvent.query.filter(
            EmailEvent.recipient_email == email,
            EmailEvent.created_at >= cutoff
        ).all()
        
        stats = {
            'total_sent': 0,
            'total_opened': 0,
            'total_clicked': 0,
            'categories': {}
        }
        
        for event in events:
            if event.event_type == cls.EVENT_SENT:
                stats['total_sent'] += 1
            elif event.event_type == cls.EVENT_OPENED:
                stats['total_opened'] += 1
            elif event.event_type == cls.EVENT_CLICKED:
                stats['total_clicked'] += 1
            
            # Track by category
            if event.email_category not in stats['categories']:
                stats['categories'][event.email_category] = 0
            stats['categories'][event.email_category] += 1
        
        stats['open_rate'] = round((stats['total_opened'] / stats['total_sent'] * 100), 1) if stats['total_sent'] > 0 else 0
        stats['click_rate'] = round((stats['total_clicked'] / stats['total_opened'] * 100), 1) if stats['total_opened'] > 0 else 0
        
        return stats


# Convenience functions for common operations
def record_email_sent(email: str, category: str, resend_id: Optional[str] = None, 
                      subject: Optional[str] = None, **kwargs) -> Optional[EmailEvent]:
    """Convenience function to record a sent email."""
    return EmailAnalytics.record_send(email, category, resend_id, subject, **kwargs)


def process_webhook(payload: Dict[str, Any]) -> Optional[EmailEvent]:
    """Convenience function to process a webhook payload."""
    return EmailAnalytics.record_from_webhook(payload)
