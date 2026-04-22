"""
Daily Civic Question models.

DailyQuestion — the Wordle-style daily participation prompt, linked to
a source Discussion/Statement/TrendingTopic and optionally to a
Polymarket market for consensus-divergence analysis.
DailyQuestionResponse — individual user votes (agree/disagree/unsure)
with optional reason, confidence, and reason-tag metadata.
DailyQuestionResponseFlag — community moderation for responses.
DailyQuestionSubscriber — email-only subscribers with magic-link and
signed-token auth, timezone-aware weekly/monthly digest scheduling,
and participation streaks.
DailyQuestionSelection — history of content used as question source to
prevent near-term repetition.

Moved here from app/models.py as part of the models-split refactor.
Cross-domain relationships (User, Discussion, Statement, TrendingTopic)
use string references. PolymarketMarket is imported lazily inside
market_divergence() to avoid pulling the polymarket submodule into
this module's import graph at load time.
"""

from datetime import timedelta
from typing import Optional

from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from sqlalchemy.orm import validates

from app import db
from app.lib.time import utcnow_naive


class DailyQuestion(db.Model):
    """
    Daily Civic Question - Wordle-like daily participation ritual.
    Links to existing discussions/statements as question source.
    One question per day, designed for finite, low-friction engagement.
    """
    __tablename__ = 'daily_question'
    __table_args__ = (
        db.Index('idx_daily_question_date', 'question_date'),
        db.Index('idx_daily_question_status', 'status'),
        db.UniqueConstraint('question_date', name='uq_daily_question_date'),
    )

    id = db.Column(db.Integer, primary_key=True)

    question_date = db.Column(db.Date, nullable=False, unique=True)
    question_number = db.Column(db.Integer, nullable=False)

    question_text = db.Column(db.String(500), nullable=False)
    context = db.Column(db.Text)
    why_this_question = db.Column(db.String(300))

    source_type = db.Column(db.String(20), default='discussion')
    source_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    source_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    source_trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)

    topic_category = db.Column(db.String(100))

    status = db.Column(db.String(20), default='scheduled')

    cold_start_threshold = db.Column(db.Integer, default=20)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)

    # Polymarket Integration (optional, for consensus divergence feature)
    polymarket_market_id = db.Column(db.Integer, db.ForeignKey('polymarket_market.id'), nullable=True)

    source_discussion = db.relationship('Discussion', backref='daily_questions')
    source_statement = db.relationship('Statement', backref='daily_questions')
    source_trending_topic = db.relationship('TrendingTopic', backref='daily_questions')
    created_by = db.relationship('User', backref='created_daily_questions')

    @property
    def response_count(self):
        """Total number of responses to this daily question.

        Uses cached count if available (set by batch queries in admin routes)
        to prevent N+1 query issues.
        """
        # Check for cached count (set by admin list routes to prevent N+1)
        if hasattr(self, '_cached_response_count'):
            return self._cached_response_count
        return DailyQuestionResponse.query.filter_by(daily_question_id=self.id).count()

    @property
    def is_cold_start(self):
        """Check if below cold start threshold"""
        return self.response_count < self.cold_start_threshold

    @property
    def vote_percentages(self):
        """Calculate vote percentages"""
        responses = DailyQuestionResponse.query.filter_by(daily_question_id=self.id).all()
        total = len(responses)
        if total == 0:
            return {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0}

        agree = sum(1 for r in responses if r.vote == 1)
        disagree = sum(1 for r in responses if r.vote == -1)
        unsure = sum(1 for r in responses if r.vote == 0)

        return {
            'agree': round((agree / total) * 100),
            'disagree': round((disagree / total) * 100),
            'unsure': round((unsure / total) * 100),
            'total': total
        }

    @property
    def early_signal_message(self):
        """Generate cold start early signal message"""
        stats = self.vote_percentages
        if stats['total'] == 0:
            return "Be the first to respond to today's question."

        if stats['agree'] > stats['disagree'] + 20:
            return "Early responses lean toward agreement."
        elif stats['disagree'] > stats['agree'] + 20:
            return "Early responses lean toward disagreement."
        elif stats['unsure'] > 30:
            return "Early responses show uncertainty on this topic."
        else:
            return "Early responses suggest opinions are still forming."

    @property
    def market_divergence(self) -> Optional[dict]:
        """
        Calculate divergence between user votes and market probability.
        Returns None if no market linked or insufficient data.

        Returns:
            {
                'user_probability': 0.62,  # % of users who voted "agree"
                'market_probability': 0.78,
                'divergence': 0.16,
                'is_significant': True,  # divergence >= 0.15
                'direction': 'lower',  # users are 'higher' or 'lower' than market
                'market_question': "Will X happen?",
                'market_url': "https://polymarket.com/..."
            }
        """
        if not self.polymarket_market_id:
            return None

        # Lazy import: the polymarket submodule is a sibling under app.models,
        # and importing it here (rather than at module top) keeps daily_question's
        # load path free of the cross-submodule dependency.
        from app.models.polymarket import PolymarketMarket
        market = db.session.get(PolymarketMarket, self.polymarket_market_id)
        if not market or market.probability is None:
            return None

        vote_pcts = self.vote_percentages
        if vote_pcts.get('total', 0) < 10:  # Need minimum votes for meaningful comparison
            return None

        # User "agree" percentage as probability estimate
        user_prob = vote_pcts.get('agree', 0) / 100
        market_prob = market.probability
        divergence = abs(user_prob - market_prob)

        return {
            'user_probability': user_prob,
            'market_probability': market_prob,
            'divergence': divergence,
            'is_significant': divergence >= 0.15,  # 15+ points = interesting
            'direction': 'higher' if user_prob > market_prob else 'lower',
            'market_question': market.question,
            'market_url': market.polymarket_url,
            'market_change_24h': market.change_24h_formatted
        }

    @classmethod
    def get_today(cls):
        """Get today's daily question"""
        from datetime import date
        today = date.today()
        return cls.query.filter_by(question_date=today, status='published').first()

    @classmethod
    def get_by_date(cls, question_date):
        """Get daily question for a specific date"""
        return cls.query.filter_by(question_date=question_date, status='published').first()

    @classmethod
    def get_next_question_number(cls):
        """Get the next question number"""
        last = cls.query.order_by(cls.question_number.desc()).first()
        return (last.question_number + 1) if last else 1

    def to_dict(self):
        return {
            'id': self.id,
            'question_date': self.question_date.isoformat(),
            'question_number': self.question_number,
            'question_text': self.question_text,
            'context': self.context,
            'why_this_question': self.why_this_question,
            'topic_category': self.topic_category,
            'status': self.status,
            'response_count': self.response_count,
            'is_cold_start': self.is_cold_start,
            'vote_percentages': self.vote_percentages,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<DailyQuestion #{self.question_number} ({self.question_date})>'


class DailyQuestionResponse(db.Model):
    """
    User response to a daily question.
    Simplified voting with optional reason.
    """
    __tablename__ = 'daily_question_response'
    __table_args__ = (
        db.Index('idx_dqr_question', 'daily_question_id'),
        db.Index('idx_dqr_user', 'user_id'),
        db.Index('idx_dqr_date', 'created_at'),
        db.UniqueConstraint('daily_question_id', 'user_id', name='uq_daily_question_user'),
        db.UniqueConstraint('daily_question_id', 'session_fingerprint', name='uq_daily_question_session'),
    )

    id = db.Column(db.Integer, primary_key=True)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)

    vote = db.Column(db.SmallInteger, nullable=False)

    reason = db.Column(db.String(500), nullable=True)

    # Visibility for reason: 'public_named', 'public_anonymous', 'private'
    # Defaults to 'public_anonymous' for email subscribers, 'public_named' for logged-in users
    reason_visibility = db.Column(db.String(20), default='public_anonymous')

    # Track if vote was submitted via one-click email (no reason prompt shown initially)
    voted_via_email = db.Column(db.Boolean, default=False)

    # Optional structured metadata for richer analytics
    confidence_level = db.Column(db.String(10), nullable=True)  # low | medium | high
    reason_tag = db.Column(db.String(30), nullable=True)  # cost | fairness | evidence | ...
    context_expanded = db.Column(db.Boolean, default=False, nullable=False)
    source_link_click_count = db.Column(db.SmallInteger, default=0, nullable=False)

    # Track which question the email was about (for analytics on vote mismatch patterns)
    # If user clicks old email link, this will differ from daily_question_id
    email_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)

    # Moderation flags
    is_hidden = db.Column(db.Boolean, default=False)  # Hidden by admin or auto-flagged
    flag_count = db.Column(db.Integer, default=0)  # Number of user flags
    reviewed_by_admin = db.Column(db.Boolean, default=False)  # Admin has reviewed
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    daily_question = db.relationship('DailyQuestion', foreign_keys=[daily_question_id], backref='responses')
    email_question = db.relationship('DailyQuestion', foreign_keys=[email_question_id], backref='email_responses')
    user = db.relationship('User', foreign_keys=[user_id], backref='daily_question_responses')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='reviewed_comments')

    @validates('vote')
    def validate_vote(self, key, vote):
        """Ensure vote is -1, 0, or 1"""
        if vote not in [-1, 0, 1]:
            raise ValueError("Vote must be -1 (disagree), 0 (unsure), or 1 (agree)")
        return vote

    @validates('reason')
    def validate_reason(self, key, reason):
        """Validate reason length (280-500 chars if provided)"""
        if reason and len(reason) > 500:
            raise ValueError("Reason must not exceed 500 characters")
        return reason

    @validates('confidence_level')
    def validate_confidence_level(self, key, confidence_level):
        """Validate optional confidence signal."""
        if confidence_level is None:
            return None
        valid = {'low', 'medium', 'high'}
        if confidence_level not in valid:
            raise ValueError("confidence_level must be low, medium, or high")
        return confidence_level

    @validates('reason_tag')
    def validate_reason_tag(self, key, reason_tag):
        """Validate optional structured reason tag."""
        if reason_tag is None:
            return None
        valid = {
            'cost', 'fairness', 'evidence', 'feasibility',
            'rights', 'safety', 'trust', 'long_term_impact', 'other'
        }
        if reason_tag not in valid:
            raise ValueError("Invalid reason_tag")
        return reason_tag

    @property
    def vote_emoji(self):
        """Return emoji block for sharing"""
        emoji_map = {1: '🟦', -1: '🟥', 0: '🟨'}
        return emoji_map.get(self.vote, '⬜')

    @property
    def vote_label(self):
        """Return human-readable vote label"""
        label_map = {1: 'Agree', -1: 'Disagree', 0: 'Unsure'}
        return label_map.get(self.vote, 'Unknown')

    def to_dict(self):
        return {
            'id': self.id,
            'daily_question_id': self.daily_question_id,
            'vote': self.vote,
            'vote_label': self.vote_label,
            'vote_emoji': self.vote_emoji,
            'reason': self.reason,
            'reason_visibility': self.reason_visibility,
            'voted_via_email': self.voted_via_email,
            'confidence_level': self.confidence_level,
            'reason_tag': self.reason_tag,
            'context_expanded': self.context_expanded,
            'source_link_click_count': self.source_link_click_count,
            'created_at': self.created_at.isoformat()
        }

    @property
    def display_name(self):
        """Return display name based on visibility setting"""
        if self.reason_visibility == 'public_named' and self.user:
            return self.user.display_name or self.user.email.split('@')[0]
        elif self.reason_visibility == 'public_anonymous':
            return 'Someone'
        return None

    @property
    def is_reason_public(self):
        """Check if the reason should be publicly visible"""
        return self.reason and self.reason_visibility in ('public_named', 'public_anonymous')

    def __repr__(self):
        return f'<DailyQuestionResponse {self.vote_label} on Q#{self.daily_question_id}>'


class DailyQuestionResponseFlag(db.Model):
    """
    User flags for inappropriate daily question responses.
    Enables community moderation and admin review.
    """
    __tablename__ = 'daily_question_response_flag'
    __table_args__ = (
        db.Index('idx_dqrf_response', 'response_id'),
        db.Index('idx_dqrf_status', 'status'),
        db.Index('idx_dqrf_created', 'created_at'),
        # Prevent duplicate flags from same user on same response
        db.UniqueConstraint('response_id', 'flagged_by_fingerprint', name='uq_response_flag_fingerprint'),
    )

    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('daily_question_response.id'), nullable=False)

    # Who flagged (can be anonymous via fingerprint)
    flagged_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    flagged_by_fingerprint = db.Column(db.String(64), nullable=True)

    # Flag details
    reason = db.Column(db.String(50), nullable=False)  # 'spam', 'harassment', 'misinformation', 'other'
    details = db.Column(db.String(500), nullable=True)  # Optional explanation

    # Status tracking
    status = db.Column(db.String(20), default='pending')  # 'pending', 'reviewed_valid', 'reviewed_invalid', 'dismissed'
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    review_notes = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    response = db.relationship('DailyQuestionResponse', backref='flags')
    flagged_by = db.relationship('User', foreign_keys=[flagged_by_user_id], backref='daily_response_flags_submitted')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='daily_response_flags_reviewed')

    def to_dict(self):
        return {
            'id': self.id,
            'response_id': self.response_id,
            'reason': self.reason,
            'details': self.details,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }

    def __repr__(self):
        return f'<DailyQuestionResponseFlag {self.reason} on Response#{self.response_id}>'


class DailyQuestionSubscriber(db.Model):
    """
    Email-only subscriber for Daily Civic Questions.
    Supports magic-link voting without requiring a full account.
    """
    __tablename__ = 'daily_question_subscriber'
    __table_args__ = (
        db.Index('idx_dqs_email', 'email'),
        db.Index('idx_dqs_token', 'magic_token'),
        db.Index('idx_dqs_frequency', 'email_frequency', 'is_active'),
        db.Index('idx_dqs_send_day', 'preferred_send_day', 'is_active'),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    is_active = db.Column(db.Boolean, default=True)

    magic_token = db.Column(db.String(64), unique=True)
    token_expires_at = db.Column(db.DateTime)

    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_participation_date = db.Column(db.Date)
    thoughtful_participations = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    last_email_sent = db.Column(db.DateTime)

    # Track unsubscribe reason: 'too_frequent', 'not_interested', 'content_quality', 'other'
    unsubscribe_reason = db.Column(db.String(50), nullable=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Email frequency and send timestamps
    email_frequency = db.Column(db.String(20), default='weekly', nullable=False)  # 'daily'|'weekly'|'monthly'
    last_weekly_email_sent = db.Column(db.DateTime, nullable=True)
    last_monthly_email_sent = db.Column(db.DateTime, nullable=True)
    preferred_send_day = db.Column(db.Integer, default=1, nullable=False)  # 0=Mon, 1=Tue (default), ..., 6=Sun
    preferred_send_hour = db.Column(db.Integer, default=9, nullable=False)  # 0-23, default 9am
    timezone = db.Column(db.String(50), nullable=True)  # e.g., 'Europe/London', 'America/New_York'

    user = db.relationship('User', backref='daily_subscription')

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token for login/authentication"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.token_expires_at = utcnow_naive() + timedelta(hours=expires_hours)
        return self.magic_token

    def generate_vote_token(self, question_id, expires_hours=None):
        """
        Generate a question-specific vote token with longer expiration (7 days default).

        Uses signed tokens that embed the question_id, preventing old email links
        from voting on wrong questions. More secure than reusing magic_token.

        Args:
            question_id: The daily question ID this token is for
            expires_hours: Token expiration in hours (default from constants)

        Returns:
            Signed token string containing subscriber_id and question_id
        """
        from app.daily.constants import VOTE_TOKEN_EXPIRY_HOURS

        if expires_hours is None:
            expires_hours = VOTE_TOKEN_EXPIRY_HOURS

        s = Serializer(current_app.config['SECRET_KEY'])
        token = s.dumps({
            'subscriber_id': self.id,
            'question_id': question_id,
            'type': 'vote'
        })

        current_app.logger.debug(
            f"Generated vote token for subscriber {self.id}, question {question_id} "
            f"(expires in {expires_hours}h)"
        )
        return token

    @staticmethod
    def verify_vote_token(token, max_age=None):
        """
        Verify a question-specific vote token and return (subscriber, question_id, error) tuple.

        Args:
            token: The signed token to verify
            max_age: Maximum token age in seconds (default from constants)

        Returns:
            Tuple of (DailyQuestionSubscriber, question_id, error_code) where:
            - Success: (subscriber, question_id, None)
            - Expired token: (None, None, 'expired')
            - Invalid/tampered token: (None, None, 'invalid')
            - Wrong token type: (None, None, 'invalid_type')
            - Subscriber not found/inactive: (None, None, 'subscriber_not_found')
        """
        from itsdangerous import SignatureExpired, BadSignature
        from app.daily.constants import VOTE_TOKEN_EXPIRY_SECONDS

        if max_age is None:
            max_age = VOTE_TOKEN_EXPIRY_SECONDS

        s = Serializer(current_app.config['SECRET_KEY'])

        try:
            data = s.loads(token, max_age=max_age)
        except SignatureExpired:
            current_app.logger.info(f"Vote token expired")
            return None, None, 'expired'
        except BadSignature:
            current_app.logger.warning(f"Invalid vote token signature")
            return None, None, 'invalid'
        except Exception as e:
            current_app.logger.error(f"Unexpected error verifying vote token: {e}")
            return None, None, 'invalid'

        if data.get('type') != 'vote':
            current_app.logger.warning(f"Token type mismatch: expected 'vote', got '{data.get('type')}'")
            return None, None, 'invalid_type'

        subscriber = DailyQuestionSubscriber.query.filter_by(
            id=data.get('subscriber_id'),
            is_active=True
        ).first()

        if not subscriber:
            current_app.logger.info(f"Subscriber {data.get('subscriber_id')} not found or inactive")
            return None, None, 'subscriber_not_found'

        return subscriber, data.get('question_id'), None

    @staticmethod
    def verify_magic_token(token):
        """Verify magic token and return subscriber if valid"""
        subscriber = DailyQuestionSubscriber.query.filter_by(
            magic_token=token,
            is_active=True
        ).first()

        if not subscriber:
            return None

        if subscriber.token_expires_at and subscriber.token_expires_at < utcnow_naive():
            return None

        return subscriber

    def has_received_email_today(self):
        """Check if subscriber already received daily question email today (prevents duplicate sends)"""
        from datetime import date as date_type
        if not self.last_email_sent:
            return False
        return self.last_email_sent.date() == date_type.today()

    def can_receive_email(self):
        """Full eligibility check including duplicate prevention"""
        if not self.is_active:
            return False
        if self.has_received_email_today():
            return False
        return True

    def update_participation_streak(self, has_reason=False):
        """Update participation streak after a vote"""
        from datetime import date
        today = date.today()

        if self.last_participation_date:
            days_since = (today - self.last_participation_date).days

            if days_since == 0:
                pass
            elif days_since == 1:
                self.current_streak += 1
            else:
                self.current_streak = 1
        else:
            self.current_streak = 1

        if has_reason:
            self.thoughtful_participations += 1

        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        self.last_participation_date = today

    @property
    def is_thoughtful_participant(self):
        """Check if user provides reasons regularly (at least 3 times per week on average)"""
        if self.current_streak < 7:
            return self.thoughtful_participations >= self.current_streak * 0.5
        return self.thoughtful_participations >= self.current_streak * 0.4

    # Weekly digest helper constants
    SEND_DAYS = {
        0: 'Monday',
        1: 'Tuesday',
        2: 'Wednesday',
        3: 'Thursday',
        4: 'Friday',
        5: 'Saturday',
        6: 'Sunday'
    }
    VALID_EMAIL_FREQUENCIES = ['daily', 'weekly', 'monthly']

    def get_send_day_name(self):
        """Return human-readable send day name"""
        return self.SEND_DAYS.get(self.preferred_send_day, 'Tuesday')

    def should_receive_weekly_digest_now(self, utc_now=None):
        """
        Check if this subscriber should receive their weekly digest right now.
        Used by the hourly scheduler job.

        Args:
            utc_now: Current UTC datetime (optional, defaults to now)

        Returns:
            bool: True if it's the right day and hour in the subscriber's timezone
        """
        import pytz
        from flask import current_app

        if utc_now is None:
            utc_now = utcnow_naive()

        # Only applies to weekly subscribers
        if self.email_frequency != 'weekly':
            return False

        # Get subscriber's timezone (default to UTC)
        try:
            tz = pytz.timezone(self.timezone) if self.timezone else pytz.UTC
        except pytz.exceptions.UnknownTimeZoneError:
            # Log timezone error for debugging
            if current_app:
                current_app.logger.warning(
                    f"Invalid timezone '{self.timezone}' for subscriber {self.id}, "
                    f"defaulting to UTC"
                )
            tz = pytz.UTC

        # Convert UTC to subscriber's local time
        try:
            local_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(tz)
        except Exception as e:
            # Fallback to UTC on any timezone conversion error
            if current_app:
                current_app.logger.error(
                    f"Error converting timezone for subscriber {self.id}: {e}, "
                    f"defaulting to UTC"
                )
            local_now = utc_now.replace(tzinfo=pytz.UTC)

        # Check if it's the right day and hour
        return (local_now.weekday() == self.preferred_send_day and
                local_now.hour == self.preferred_send_hour)

    def has_received_weekly_digest_this_week(self):
        """Check if weekly digest was already sent this week (within last 6 days)"""
        if not self.last_weekly_email_sent:
            return False
        week_ago = utcnow_naive() - timedelta(days=6)
        return self.last_weekly_email_sent > week_ago

    def has_received_monthly_digest_this_month(self):
        """Check if a monthly digest was already sent this calendar month."""
        if not self.last_monthly_email_sent:
            return False
        now = utcnow_naive()
        return (
            self.last_monthly_email_sent.year == now.year
            and self.last_monthly_email_sent.month == now.month
        )

    def should_receive_monthly_digest_now(self, utc_now=None):
        """
        Check if this subscriber should receive their monthly digest right now.
        Monthly digests are sent on the 1st of each month at the hour in
        app.daily.constants.MONTHLY_DIGEST_LOCAL_HOUR in the subscriber's timezone.

        Args:
            utc_now: Current UTC datetime (optional, defaults to now)

        Returns:
            bool: True if it's the configured calendar day and local hour in the subscriber's timezone
        """
        import pytz
        from flask import current_app

        if utc_now is None:
            utc_now = utcnow_naive()

        # Only applies to monthly subscribers
        if self.email_frequency != 'monthly':
            return False

        # Get subscriber's timezone (default to UTC)
        try:
            tz = pytz.timezone(self.timezone) if self.timezone else pytz.UTC
        except pytz.exceptions.UnknownTimeZoneError:
            current_app.logger.warning(
                f"Invalid timezone '{self.timezone}' for subscriber {self.id}, defaulting to UTC"
            )
            tz = pytz.UTC

        # Convert UTC to subscriber's local time (ensure tzinfo is set)
        try:
            local_time = utc_now.replace(tzinfo=pytz.UTC).astimezone(tz)
        except Exception as e:
            # Fallback to UTC on any timezone conversion error
            if current_app:
                current_app.logger.error(
                    f"Error converting timezone for subscriber {self.id}: {e}, "
                    f"defaulting to UTC"
                )
            local_time = utc_now.replace(tzinfo=pytz.UTC)

        from app.daily.constants import (
            MONTHLY_DIGEST_DAY_OF_MONTH,
            MONTHLY_DIGEST_LOCAL_HOUR,
        )

        is_digest_day = local_time.day == MONTHLY_DIGEST_DAY_OF_MONTH
        is_digest_hour = local_time.hour == MONTHLY_DIGEST_LOCAL_HOUR

        return is_digest_day and is_digest_hour

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'current_streak': self.current_streak,
            'longest_streak': self.longest_streak,
            'is_active': self.is_active
        }

    def __repr__(self):
        return f'<DailyQuestionSubscriber {self.email}>'


class DailyQuestionSelection(db.Model):
    """
    Track which content has been used for daily questions.
    Prevents repeating questions within a configurable time window.
    """
    __tablename__ = 'daily_question_selection'

    id = db.Column(db.Integer, primary_key=True)

    source_type = db.Column(db.String(20), nullable=False)
    source_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    source_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    source_trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)

    selected_at = db.Column(db.DateTime, default=utcnow_naive)
    question_date = db.Column(db.Date, nullable=False)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)

    @staticmethod
    def is_recently_used(source_type, source_id, days=30):
        """Check if a source has been used in the last N days"""
        cutoff = utcnow_naive() - timedelta(days=days)

        query = DailyQuestionSelection.query.filter(
            DailyQuestionSelection.source_type == source_type,
            DailyQuestionSelection.selected_at >= cutoff
        )

        if source_type == 'discussion':
            query = query.filter(DailyQuestionSelection.source_discussion_id == source_id)
        elif source_type == 'statement':
            query = query.filter(DailyQuestionSelection.source_statement_id == source_id)
        elif source_type == 'trending':
            query = query.filter(DailyQuestionSelection.source_trending_topic_id == source_id)

        return query.first() is not None
