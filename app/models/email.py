"""
Email event tracking.

EmailEvent records Resend webhook events (sent/delivered/opened/clicked/
bounced/complained) for all outbound email. Moved here from app/models.py
as part of the models-split refactor. All related models (User,
DailyBriefSubscriber, DailyQuestionSubscriber, DailyBrief, DailyQuestion)
are referenced via string, so this submodule has no cross-submodule
imports.
"""

from datetime import timedelta
from typing import Any, Dict, Optional

from app import db
from app.lib.time import utcnow_naive


class EmailEvent(db.Model):
    """
    Unified email event tracking for all email types.
    Tracks opens, clicks, bounces from Resend webhooks.

    Email categories:
    - auth: Password reset, welcome, account activation
    - daily_brief: Daily Brief emails
    - daily_question: Daily Question emails
    - discussion: Discussion notification emails
    - admin: Admin-generated emails
    """
    __tablename__ = 'email_event'
    __table_args__ = (
        db.Index('idx_ee_email', 'recipient_email'),
        db.Index('idx_ee_category', 'email_category'),
        db.Index('idx_ee_event_type', 'event_type'),
        db.Index('idx_ee_created', 'created_at'),
        db.Index('idx_ee_resend_id', 'resend_email_id'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Email identification (generic - works for any email type)
    recipient_email = db.Column(db.String(255), nullable=False)
    resend_email_id = db.Column(db.String(255), index=True)  # Resend's email ID

    # Email categorization
    email_category = db.Column(db.String(30), nullable=False)  # auth, daily_brief, daily_question, discussion, admin
    email_subject = db.Column(db.String(500))  # Store subject for reference

    # Event data from Resend
    event_type = db.Column(db.String(50), nullable=False)  # sent, delivered, opened, clicked, bounced, complained

    # Optional references (for analytics drill-down)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    brief_subscriber_id = db.Column(db.Integer, db.ForeignKey('daily_brief_subscriber.id'), nullable=True)
    question_subscriber_id = db.Column(db.Integer, db.ForeignKey('daily_question_subscriber.id'), nullable=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=True)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)

    # Additional event data
    click_url = db.Column(db.String(500))  # For click events
    bounce_type = db.Column(db.String(50))  # hard, soft
    complaint_type = db.Column(db.String(50))  # spam, abuse
    user_agent = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    user = db.relationship('User', backref='email_events')
    brief_subscriber = db.relationship('DailyBriefSubscriber', backref='email_events')
    question_subscriber = db.relationship('DailyQuestionSubscriber', backref='email_events')
    brief = db.relationship('DailyBrief', backref='email_events')
    daily_question = db.relationship('DailyQuestion', backref='email_events')

    # Class constants for email categories
    CATEGORY_AUTH = 'auth'
    CATEGORY_DAILY_BRIEF = 'daily_brief'
    CATEGORY_DAILY_QUESTION = 'daily_question'
    CATEGORY_DISCUSSION = 'discussion'
    CATEGORY_ADMIN = 'admin'

    # Class constants for event types (without email. prefix for clean storage)
    EVENT_SENT = 'sent'
    EVENT_DELIVERED = 'delivered'
    EVENT_OPENED = 'opened'
    EVENT_CLICKED = 'clicked'
    EVENT_BOUNCED = 'bounced'
    EVENT_COMPLAINED = 'complained'

    @staticmethod
    def normalize_event_type(event_type: Optional[str]) -> str:
        """Normalize event types across legacy and current formats."""
        if not event_type:
            return ''
        normalized = str(event_type).strip().lower()
        if normalized.startswith('email.'):
            normalized = normalized[6:]
        return normalized

    @staticmethod
    def compute_rate_metrics(
        total_sent: int,
        total_delivered: int,
        total_opened: int,
        total_clicked: int,
        total_bounced: int = 0,
        total_complained: int = 0,
        *,
        engagement_basis: str = "delivered",
    ) -> Dict[str, Any]:
        """
        Single source of truth for email performance rates (0–100 or None = N/A).

        Definitions (industry-typical for ESP-backed metrics):
        - **delivery_rate**: delivered / sent, or (sent − hard bounces) / sent when
          `delivered` events are not tracked; None if we cannot estimate.
        - **open_rate** (per delivered message): unique opens are not in this table
          (each open is a row) — we report opens / delivered as a proxy, N/A if no
          delivery cohort. With ``engagement_basis="sent"`` (e.g. briefing runs
          without Resend webhooks) uses opens / sent and CTR = clicks / sent.
        - **click_rate** (CTR): clicks / **delivered** (or / sent with sent-basis).
        - **click_to_open_rate** (CTOR): clicks / opens, N/A if opens = 0.

        None values are intentional: the UI should show N/A, not 0%,
        when the denominator is unknown (e.g. no `email.delivered` webhooks).
        """
        if engagement_basis not in ("delivered", "sent"):
            raise ValueError("engagement_basis must be 'delivered' or 'sent'")

        out: Dict[str, Any] = {
            "delivery_rate": None,
            "delivery_rate_estimated": False,
            "open_rate": None,
            "click_rate": None,
            "click_to_open_rate": None,
            "bounce_rate": None,
            "complaint_rate": None,
        }

        if total_sent <= 0:
            return out

        if engagement_basis == "delivered":
            if total_delivered > 0:
                # total_delivered > 0 implies total_sent > 0 (can't deliver what wasn't sent),
                # so no divide-by-zero guard is needed here.
                out["delivery_rate"] = round(total_delivered / total_sent * 100, 1)
            elif total_bounced > 0:
                out["delivery_rate"] = round(
                    max(total_sent - total_bounced, 0) / total_sent * 100, 1
                )
                out["delivery_rate_estimated"] = True
            # else: None — no delivery signal

            out["bounce_rate"] = round((total_bounced / total_sent) * 100, 1)

            denom = total_delivered
            if denom > 0:
                out["open_rate"] = round((total_opened / denom) * 100, 1)
                out["click_rate"] = round((total_clicked / denom) * 100, 1)
                out["complaint_rate"] = round((total_complained / denom) * 100, 1)
        else:  # engagement_basis == "sent"
            # total_sent > 0 here — the early-return above rules out the zero case.
            out["open_rate"] = round((total_opened / total_sent) * 100, 1)
            out["click_rate"] = round((total_clicked / total_sent) * 100, 1)
            if total_opened > 0:
                out["click_to_open_rate"] = round(
                    (total_clicked / total_opened) * 100, 1
                )
            return out

        if total_opened > 0:
            out["click_to_open_rate"] = round(
                (total_clicked / total_opened) * 100, 1
            )

        return out

    @classmethod
    def record_event(cls, recipient_email: str, event_type: str, email_category: str,
                     resend_email_id: Optional[str] = None, email_subject: Optional[str] = None,
                     user_id: Optional[int] = None, brief_subscriber_id: Optional[int] = None,
                     question_subscriber_id: Optional[int] = None, brief_id: Optional[int] = None,
                     daily_question_id: Optional[int] = None, click_url: Optional[str] = None,
                     bounce_type: Optional[str] = None, complaint_type: Optional[str] = None,
                     user_agent: Optional[str] = None, ip_address: Optional[str] = None):
        """
        Factory method to record an email event.
        DRY: Single point of entry for all event recording.

        Args:
            recipient_email: Required - email address of recipient
            event_type: Required - type of event (sent, delivered, opened, etc.)
            email_category: Required - category (auth, daily_brief, etc.)

        Returns:
            EmailEvent instance or None if validation fails
        """
        if not recipient_email or not event_type or not email_category:
            import logging
            logging.getLogger(__name__).error(
                f"EmailEvent.record_event missing required fields: "
                f"email={recipient_email}, type={event_type}, category={email_category}"
            )
            return None

        # Normalize event_type (supports legacy 'email.*' values)
        event_type = cls.normalize_event_type(event_type)

        event = cls(
            recipient_email=recipient_email,
            resend_email_id=resend_email_id,
            email_category=email_category,
            email_subject=email_subject,
            event_type=event_type,
            user_id=user_id,
            brief_subscriber_id=brief_subscriber_id,
            question_subscriber_id=question_subscriber_id,
            brief_id=brief_id,
            daily_question_id=daily_question_id,
            click_url=click_url,
            bounce_type=bounce_type,
            complaint_type=complaint_type,
            user_agent=user_agent,
            ip_address=ip_address
        )
        db.session.add(event)
        return event

    @classmethod
    def get_stats(cls, email_category: Optional[str] = None, days: int = 7) -> dict:
        """
        Get aggregated statistics for emails.
        DRY: Reusable stats method for any category.
        email_category can be None to get stats for all categories.
        """
        from sqlalchemy import func

        cutoff = utcnow_naive() - timedelta(days=days)
        query = cls.query.filter(cls.created_at >= cutoff)

        if email_category:
            query = query.filter(cls.email_category == email_category)

        # Count by event type
        event_counts = db.session.query(
            cls.event_type,
            func.count(cls.id)
        ).filter(cls.created_at >= cutoff)

        if email_category:
            event_counts = event_counts.filter(cls.email_category == email_category)

        raw_event_counts = dict(event_counts.group_by(cls.event_type).all())

        # Normalize legacy and current event type formats into one rollup.
        event_counts = {}
        for event_type, count in raw_event_counts.items():
            normalized_type = cls.normalize_event_type(event_type)
            event_counts[normalized_type] = event_counts.get(normalized_type, 0) + count

        total_sent = event_counts.get(cls.EVENT_SENT, 0)
        total_delivered = event_counts.get(cls.EVENT_DELIVERED, 0)
        total_opened = event_counts.get(cls.EVENT_OPENED, 0)
        total_clicked = event_counts.get(cls.EVENT_CLICKED, 0)
        total_bounced = event_counts.get(cls.EVENT_BOUNCED, 0)
        total_complained = event_counts.get(cls.EVENT_COMPLAINED, 0)

        rates = cls.compute_rate_metrics(
            total_sent,
            total_delivered,
            total_opened,
            total_clicked,
            total_bounced,
            total_complained,
            engagement_basis="delivered",
        )
        return {
            "total_sent": total_sent,
            "total_delivered": total_delivered,
            "total_opened": total_opened,
            "total_clicked": total_clicked,
            "total_bounced": total_bounced,
            "total_complained": total_complained,
            "delivery_rate": rates["delivery_rate"],
            "delivery_rate_estimated": rates["delivery_rate_estimated"],
            "open_rate": rates["open_rate"],
            "click_rate": rates["click_rate"],
            "click_to_open_rate": rates["click_to_open_rate"],
            "bounce_rate": rates["bounce_rate"],
            "complaint_rate": rates["complaint_rate"],
            "event_counts": event_counts,
        }

    @classmethod
    def get_recent_events(cls, email_category: Optional[str] = None, limit: int = 50):
        """Get recent events, optionally filtered by category."""
        query = cls.query.order_by(cls.created_at.desc())
        if email_category:
            query = query.filter(cls.email_category == email_category)
        return query.limit(limit).all()

    def to_dict(self):
        return {
            'id': self.id,
            'recipient_email': self.recipient_email,
            'email_category': self.email_category,
            'email_subject': self.email_subject,
            'event_type': self.event_type,
            'click_url': self.click_url,
            'bounce_type': self.bounce_type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<EmailEvent {self.event_type} ({self.email_category}) to {self.recipient_email}>'


# Backward compatibility alias
BriefEmailEvent = EmailEvent
