from app import db, cache
from app.lib.time import utcnow_naive
from flask import current_app, g
from datetime import datetime, timedelta
from slugify import slugify as python_slugify
from flask_login import UserMixin
from unidecode import unidecode
from itsdangerous import URLSafeTimedSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional

import re
import time



def generate_slug(name):
    """Generate a URL-friendly slug from a string."""
    if not name:
        return ""

    # Convert to lowercase and normalize unicode characters
    name = str(name).lower()
    name = unidecode(name)

    # Replace non-alphanumeric characters with hyphens
    name = re.sub(r'[^a-z0-9]+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Replace multiple consecutive hyphens with a single hyphen
    name = re.sub(r'-+', '-', name)

    return name


class User(UserMixin, db.Model):
    __table_args__ = (
        db.Index('idx_user_stripe_customer_id', 'stripe_customer_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    # New field to indicate profile type
    profile_type = db.Column(db.String(50))  # 'individual' or 'company'

    # Notification preferences
    email_notifications = db.Column(db.Boolean, default=True)  # Enable email notifications
    discussion_participant_notifications = db.Column(db.Boolean, default=True)  # New participants
    discussion_response_notifications = db.Column(db.Boolean, default=True)  # Activity: statements, replies, votes
    discussion_update_notifications = db.Column(db.Boolean, default=True)  # Organiser/steward "what happened next" updates
    weekly_digest_enabled = db.Column(db.Boolean, default=True)  # Weekly digest emails

    # Language preference — BCP 47 code from SUPPORTED_LANGUAGES (e.g. 'nl', 'fr').
    # NULL means "use browser default / cookie / Accept-Language".
    language = db.Column(db.String(10), nullable=True)

    # Login tracking
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Stripe billing
    stripe_customer_id = db.Column(db.String(255), nullable=True, unique=True)

    # Relationships to profiles
    individual_profile = db.relationship('IndividualProfile', backref='user', uselist=False)
    company_profile = db.relationship('CompanyProfile', backref='user', uselist=False)

    discussions_created = db.relationship('Discussion', backref='creator', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    discussion_follows = db.relationship('DiscussionFollow', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    discussion_updates_authored = db.relationship('DiscussionUpdate', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    programmes_created = db.relationship('Programme', backref='creator', lazy='select', foreign_keys='Programme.creator_id')
    programme_stewardships = db.relationship(
        'ProgrammeSteward',
        backref='user',
        lazy='select',
        foreign_keys='ProgrammeSteward.user_id'
    )

    # Password methods
    def set_password(self, password):
        """Hashes and sets the password."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Verifies the password against the stored hash."""
        return check_password_hash(self.password, password)

    # Token generation and verification methods for password reset
    def get_reset_token(self, expires_sec=1800):
        """Generates a token valid for `expires_sec` seconds (default: 30 minutes)."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id}, salt='password-reset-salt')

    @staticmethod
    def verify_reset_token(token, expiration=1800):
        """Verifies the token and returns the user if valid, otherwise None."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, salt='password-reset-salt', max_age=expiration)['user_id']
        except Exception:
            return None
        return db.session.get(User, user_id)

    # Token generation and verification methods for email verification (separate from password reset)
    def get_email_verification_token(self, expires_sec=86400):
        """Generates an email verification token valid for expires_sec seconds (default: 24 hours)."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id}, salt='email-verification-salt')

    @staticmethod
    def verify_email_verification_token(token, expiration=86400):
        """
        Verifies the email verification token.
        Returns (user, expired) where:
          - user is the User object if the token signature is valid, else None
          - expired is True if the token was valid but has timed out
        """
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, salt='email-verification-salt', max_age=expiration)['user_id']
            return db.session.get(User, user_id), False
        except Exception as e:
            # Distinguish between expired and truly invalid tokens
            try:
                user_id = s.loads(token, salt='email-verification-salt', max_age=None)['user_id']
                return db.session.get(User, user_id), True
            except Exception:
                return None, False

    # Flask-Login required methods
    def is_active(self):
        # Here, we assume all users are active. Adjust if you have inactive users.
        return True

    def get_id(self):
        # Flask-Login needs this to identify users across sessions.
        return str(self.id)

    @property
    def unread_notification_count(self):
        cache_key = f'_unread_notif_count_{self.id}'
        cached = getattr(g, cache_key, None)
        if cached is None:
            cached = Notification.unread_count_for_user(self.id)
            setattr(g, cache_key, cached)
        return cached

    def follows_discussion(self, discussion_id):
        if not discussion_id:
            return False
        return self.discussion_follows.filter_by(discussion_id=discussion_id).first() is not None


class Partner(db.Model):
    __table_args__ = (
        db.Index('idx_partner_status', 'status'),
        db.Index('ix_partner_slug', 'slug', unique=True),
        db.Index('ix_partner_contact_email', 'contact_email', unique=True),
        db.Index('ix_partner_stripe_customer_id', 'stripe_customer_id', unique=True),
        db.Index('ix_partner_stripe_subscription_id', 'stripe_subscription_id', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(80), nullable=False)
    contact_email = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), default='pending', nullable=False)
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    billing_status = db.Column(db.String(30), default='inactive', nullable=False)
    tier = db.Column(db.String(30), default='free', nullable=False)  # free | starter | professional | enterprise
    # When True, embed + public partner ref behave as DISABLED_PARTNER_REFS (ops kill switch without redeploy)
    embed_disabled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    domains = db.relationship('PartnerDomain', backref='partner', lazy='dynamic')
    api_keys = db.relationship('PartnerApiKey', backref='partner', lazy='dynamic')
    members = db.relationship('PartnerMember', backref='partner', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_reset_token(self, expires_sec=1800):
        """Generate a password-reset token valid for expires_sec seconds (default 30 min)."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'partner_id': self.id}, salt='partner-password-reset')

    @staticmethod
    def verify_reset_token(token, expiration=1800):
        """Verify a partner password-reset token. Returns Partner or None."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, salt='partner-password-reset', max_age=expiration)
        except Exception:
            return None
        return db.session.get(Partner, data.get('partner_id'))


class PartnerDomain(db.Model):
    __table_args__ = (
        db.Index('idx_partner_domain', 'domain'),
        db.Index('idx_partner_domain_env', 'env'),
        db.Index('idx_partner_domain_domain_env', 'domain', 'env'),
    )

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    domain = db.Column(db.String(255), nullable=False)
    env = db.Column(db.String(10), default='test', nullable=False)  # test | live
    verification_method = db.Column(db.String(30), default='dns_txt', nullable=False)
    verification_token = db.Column(db.String(200), nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def is_verified(self):
        return self.verified_at is not None


class PartnerApiKey(db.Model):
    __table_args__ = (
        db.Index('idx_partner_key_prefix', 'key_prefix'),
        db.Index('idx_partner_key_hash', 'key_hash'),
        db.Index('idx_partner_key_env', 'env'),
        db.Index('idx_partner_key_status', 'status'),
        db.Index('idx_partner_key_hash_status', 'key_hash', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    key_prefix = db.Column(db.String(32), nullable=False)
    key_hash = db.Column(db.String(128), nullable=False)
    key_last4 = db.Column(db.String(4), nullable=False)
    env = db.Column(db.String(10), default='test', nullable=False)  # test | live
    status = db.Column(db.String(20), default='active', nullable=False)  # active | revoked
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    last_used_at = db.Column(db.DateTime, nullable=True)


class PartnerWebhookEndpoint(db.Model):
    __table_args__ = (
        db.Index('idx_partner_webhook_partner_status', 'partner_id', 'status'),
        db.Index('idx_partner_webhook_event_types', 'event_types'),
    )

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    url = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), default='active', nullable=False)  # active | paused | disabled
    event_types = db.Column(db.JSON, nullable=False, default=list)
    encrypted_signing_secret = db.Column(db.Text, nullable=False)
    secret_last4 = db.Column(db.String(4), nullable=False)
    last_delivery_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)


class PartnerWebhookDelivery(db.Model):
    __table_args__ = (
        db.Index('idx_partner_webhook_delivery_status_next', 'status', 'next_attempt_at'),
        db.Index('idx_partner_webhook_delivery_endpoint_created', 'endpoint_id', 'created_at'),
        db.UniqueConstraint('endpoint_id', 'event_id', name='uq_partner_webhook_delivery_endpoint_event'),
    )

    id = db.Column(db.Integer, primary_key=True)
    endpoint_id = db.Column(db.Integer, db.ForeignKey('partner_webhook_endpoint.id', ondelete='CASCADE'), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    event_id = db.Column(db.String(80), nullable=False)
    event_type = db.Column(db.String(80), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending | retrying | delivered | failed
    attempt_count = db.Column(db.Integer, default=0, nullable=False)
    next_attempt_at = db.Column(db.DateTime, nullable=True)
    last_http_status = db.Column(db.Integer, nullable=True)
    last_response_body = db.Column(db.Text, nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)


class PartnerMember(db.Model):
    __table_args__ = (
        db.Index('ix_partner_member_partner_id', 'partner_id'),
        db.Index('ix_partner_member_email', 'email', unique=True),
        db.Index('ix_partner_member_invite_token', 'invite_token', unique=True),
        db.Index('ix_partner_member_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='member')  # owner | admin | member
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending | active | disabled
    invite_token = db.Column(db.String(255), nullable=True)
    invited_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    permissions_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def generate_invite_token():
        import secrets
        return secrets.token_urlsafe(32)


class PartnerUsageEvent(db.Model):
    __table_args__ = (
        db.Index('idx_partner_usage_event', 'partner_id', 'env', 'event_type'),
    )

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    env = db.Column(db.String(10), default='test', nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)




class ProfileView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Allow the view to be associated with either type of profile
    individual_profile_id = db.Column(db.Integer, db.ForeignKey('individual_profile.id'), nullable=True)
    company_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for anonymous views
    timestamp = db.Column(db.DateTime, default=utcnow_naive)
    ip_address = db.Column(db.String(45))  # Store IP address for analytics


class DiscussionView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for anonymous views
    timestamp = db.Column(db.DateTime, default=utcnow_naive)
    ip_address = db.Column(db.String(45))  # Store IP address for analytics


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'new_participant', 'new_response', etc.
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    email_sent = db.Column(db.Boolean, default=False)

    # Relationships
    discussion = db.relationship('Discussion', backref='notifications')

    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        db.session.commit()

    @classmethod
    def unread_count_for_user(cls, user_id):
        if not user_id:
            return 0
        return cls.query.filter_by(user_id=user_id, is_read=False).count()

    @classmethod
    def mark_all_as_read_for_user(cls, user_id):
        if not user_id:
            return 0
        updated = cls.query.filter_by(user_id=user_id, is_read=False).update(
            {'is_read': True},
            synchronize_session=False,
        )
        db.session.commit()
        return updated


class DiscussionFollow(db.Model):
    __tablename__ = 'discussion_follow'
    __table_args__ = (
        db.Index('idx_discussion_follow_user_created', 'user_id', 'created_at'),
        db.Index('idx_discussion_follow_discussion_created', 'discussion_id', 'created_at'),
        db.UniqueConstraint('user_id', 'discussion_id', name='uq_discussion_follow_user_discussion'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)


class DiscussionUpdate(db.Model):
    __tablename__ = 'discussion_update'
    __table_args__ = (
        db.Index('idx_discussion_update_discussion_created', 'discussion_id', 'created_at'),
        db.Index('idx_discussion_update_user_created', 'user_id', 'created_at'),
    )

    TYPE_UPDATE = 'update'
    TYPE_OUTCOME = 'outcome'
    TYPE_NEXT_STEP = 'next_step'
    VALID_TYPES = {TYPE_UPDATE, TYPE_OUTCOME, TYPE_NEXT_STEP}

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    update_type = db.Column(db.String(20), nullable=False, default=TYPE_UPDATE)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    links = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

    @validates('update_type')
    def validate_update_type(self, key, value):
        normalized = (value or self.TYPE_UPDATE).strip().lower()
        if normalized not in self.VALID_TYPES:
            raise ValueError("Invalid discussion update type")
        return normalized


class DiscussionParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for anonymous
    participant_identifier = db.Column(db.String(255))  # External identifier from Pol.is
    cohort_slug = db.Column(db.String(80), nullable=True)
    viewed_information_at = db.Column(db.DateTime, nullable=True)
    joined_at = db.Column(db.DateTime, default=utcnow_naive)
    last_activity = db.Column(db.DateTime, default=utcnow_naive)
    response_count = db.Column(db.Integer, default=0)

    # Relationships
    discussion = db.relationship('Discussion', backref='participants')
    user = db.relationship('User', backref='discussion_participations')

    @classmethod
    def track_participant(cls, discussion_id, user_id=None, participant_identifier=None, commit=True, return_is_new=False):
        """
        Track a participant in a discussion.

        Args:
            discussion_id: ID of the discussion
            user_id: ID of the user (optional, for authenticated users)
            participant_identifier: External identifier (optional, for anonymous users)
            commit: Whether to commit the transaction (default True)
            return_is_new: If True, returns tuple (participant, is_new) instead of just participant

        Returns:
            DiscussionParticipant instance, or tuple (participant, is_new) if return_is_new=True

        Raises:
            ValueError: If both user_id and participant_identifier are None
        """
        # Validate that at least one identifier is provided
        if user_id is None and participant_identifier is None:
            raise ValueError("Either user_id or participant_identifier must be provided")

        # Check if participant already exists
        existing = cls.query.filter_by(
            discussion_id=discussion_id,
            user_id=user_id,
            participant_identifier=participant_identifier
        ).first()

        is_new = existing is None

        if not existing:
            savepoint = None
            try:
                # Use a savepoint so an IntegrityError here does not wipe
                # unrelated pending work in the caller's transaction
                # (important when commit=False is used in a larger unit of work).
                savepoint = db.session.begin_nested()
                participant = cls(
                    discussion_id=discussion_id,
                    user_id=user_id,
                    participant_identifier=participant_identifier
                )
                db.session.add(participant)
                # Flush to get the ID even if not committing (needed for increment_response_count)
                db.session.flush()
                savepoint.commit()
            except IntegrityError:
                # Concurrent request inserted the same participant first;
                # roll back only to the savepoint, leaving the rest of the
                # session intact, then fetch whichever row won the race.
                if savepoint is not None:
                    savepoint.rollback()
                # The conflict can come from either the user_id unique index
                # or the participant_identifier unique index.  Query by only
                # the relevant key so we always find the winning row even when
                # the other column differs.
                for _ in range(3):
                    if user_id is not None:
                        existing = cls.query.filter_by(
                            discussion_id=discussion_id,
                            user_id=user_id,
                        ).first()
                    else:
                        existing = cls.query.filter_by(
                            discussion_id=discussion_id,
                            participant_identifier=participant_identifier,
                        ).first()
                    if existing:
                        break
                    # Give the winning concurrent transaction a moment to become visible.
                    db.session.expire_all()
                    time.sleep(0.02)

                if existing:
                    existing.last_activity = utcnow_naive()
                    participant = existing
                    is_new = False
                else:
                    # If no winner is visible, try one more insert attempt in a new
                    # savepoint. This handles cases where the competing transaction
                    # rolled back after our initial conflict.
                    retry_savepoint = None
                    try:
                        retry_savepoint = db.session.begin_nested()
                        participant = cls(
                            discussion_id=discussion_id,
                            user_id=user_id,
                            participant_identifier=participant_identifier
                        )
                        db.session.add(participant)
                        db.session.flush()
                        retry_savepoint.commit()
                        is_new = True
                    except IntegrityError:
                        if retry_savepoint is not None:
                            retry_savepoint.rollback()
                        if user_id is not None:
                            existing = cls.query.filter_by(
                                discussion_id=discussion_id,
                                user_id=user_id,
                            ).first()
                        else:
                            existing = cls.query.filter_by(
                                discussion_id=discussion_id,
                                participant_identifier=participant_identifier,
                            ).first()
                        if existing:
                            existing.last_activity = utcnow_naive()
                            participant = existing
                            is_new = False
                        else:
                            # Fail loudly only after both recovery paths are exhausted.
                            raise
        else:
            # Update last activity
            existing.last_activity = utcnow_naive()
            participant = existing

        if commit:
            db.session.commit()

        if return_is_new:
            return participant, is_new
        return participant

    def increment_response_count(self, commit=True):
        """
        Atomically increment the response count for this participant.

        Args:
            commit: Whether to commit the transaction (default True)

        Note:
            This uses a database-level atomic increment to prevent race conditions.
        """
        # Use atomic update to prevent race conditions
        self.__class__.query.filter_by(id=self.id).update({
            'response_count': self.__class__.response_count + 1,
            'last_activity': utcnow_naive()
        }, synchronize_session=False)

        if commit:
            db.session.commit()
            # Refresh to get updated values
            db.session.refresh(self)


class IndividualProfile(db.Model):
    __table_args__ = (
        db.Index('idx_individual_profile_user_id', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    bio = db.Column(db.Text)
    city = db.Column(db.String(100))  # New field for city
    country = db.Column(db.String(100))  # New field for country
    email = db.Column(db.String(150), nullable=True)  # Optional public email
    website = db.Column(db.String(255))  # Optional website link
    profile_image = db.Column(db.String(255))  # Path to profile image
    banner_image = db.Column(db.String(255))  # Path to banner image
    # Individual social media fields
    linkedin_url = db.Column(db.String(255))
    twitter_url = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    instagram_url = db.Column(db.String(255))
    tiktok_url = db.Column(db.String(255))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    discussions = db.relationship('Discussion', backref='individual_profile', lazy='dynamic', foreign_keys='Discussion.individual_profile_id')
    views = db.relationship('ProfileView', 
          foreign_keys=[ProfileView.individual_profile_id],
          backref='individual_profile', 
          lazy='dynamic')

    

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.full_name:
            self.slug = generate_slug(self.full_name)

    def update_slug(self):
        if self.full_name:
            self.slug = generate_slug(self.full_name)

class CompanyProfile(db.Model):
    __table_args__ = (
        db.Index('idx_company_profile_user_id', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    company_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    city = db.Column(db.String(100))  # New field for city
    country = db.Column(db.String(100))  # New field for country
    email = db.Column(db.String(150), nullable=True)  # Optional public email
    website = db.Column(db.String(255))  # Optional website link
    logo = db.Column(db.String(255))  # Path to company logo
    banner_image = db.Column(db.String(255))  # Path to banner image
    # Individual social media fields
    linkedin_url = db.Column(db.String(255))
    twitter_url = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    instagram_url = db.Column(db.String(255))
    tiktok_url = db.Column(db.String(255))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    discussions = db.relationship('Discussion', backref='company_profile', lazy='dynamic', foreign_keys='Discussion.company_profile_id')
    views = db.relationship('ProfileView', 
          foreign_keys=[ProfileView.company_profile_id],
          backref='company_profile', 
          lazy='dynamic')

    

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.company_name:
            self.slug = generate_slug(self.company_name)

    def update_slug(self):
        if self.company_name:
            self.slug = generate_slug(self.company_name)


class OrganizationMember(db.Model):
    """
    Tracks membership of users in organizations (CompanyProfile).
    Used for Team/Enterprise plans to manage team seats.
    """
    __tablename__ = 'organization_member'
    __table_args__ = (
        db.Index('idx_org_member_org', 'org_id'),
        db.Index('idx_org_member_user', 'user_id'),
        db.UniqueConstraint('org_id', 'user_id', name='uq_org_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    # Role: 'owner', 'admin', 'editor', 'viewer'
    role = db.Column(db.String(20), default='editor', nullable=False)

    # Invitation tracking
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    invited_at = db.Column(db.DateTime, default=utcnow_naive)
    joined_at = db.Column(db.DateTime, nullable=True)  # NULL if invite pending

    # Invitation token for email invites
    invite_token = db.Column(db.String(64), unique=True, nullable=True)
    invite_email = db.Column(db.String(255), nullable=True)  # Email for pending invites

    # Status: 'pending', 'active', 'removed'
    status = db.Column(db.String(20), default='pending', nullable=False)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    org = db.relationship('CompanyProfile', backref=db.backref('members', lazy='dynamic'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('org_memberships', lazy='dynamic'))
    invited_by = db.relationship('User', foreign_keys=[invited_by_id])

    @property
    def is_active(self):
        return self.status == 'active'

    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_owner(self):
        return self.role == 'owner'

    @property
    def is_admin(self):
        return self.role in ('owner', 'admin')

    @property
    def can_edit(self):
        return self.role in ('owner', 'admin', 'editor')

    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.org_id,
            'user_id': self.user_id,
            'role': self.role,
            'status': self.status,
            'invited_at': self.invited_at.isoformat() if self.invited_at else None,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
            'invite_email': self.invite_email,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'email': self.user.email,
            } if self.user else None,
        }

    def __repr__(self):
        return f'<OrganizationMember org:{self.org_id} user:{self.user_id} ({self.role})>'


class Programme(db.Model):
    __tablename__ = 'programme'
    __table_args__ = (
        db.Index('ix_programme_slug', 'slug', unique=True),
        db.Index('ix_programme_creator_id', 'creator_id'),
        db.Index('ix_programme_company_profile_id', 'company_profile_id'),
        db.Index('ix_programme_visibility_status', 'visibility', 'status'),
        db.Index('ix_programme_scope_country', 'geographic_scope', 'country'),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(150), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    company_profile_id = db.Column(
        db.Integer,
        db.ForeignKey('company_profile.id', ondelete='RESTRICT'),
        nullable=True
    )
    geographic_scope = db.Column(db.String(20), nullable=False, default='global')
    country = db.Column(db.String(100), nullable=True)
    logo_url = db.Column(db.String(255), nullable=True)
    themes = db.Column(db.JSON, nullable=False, default=list)
    phases = db.Column(db.JSON, nullable=False, default=list)
    cohorts = db.Column(db.JSON, nullable=False, default=list)
    visibility = db.Column(db.String(20), nullable=False, default='public')
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    company_profile = db.relationship('CompanyProfile', backref=db.backref('programmes', lazy='select'))
    discussions = db.relationship('Discussion', backref='programme', lazy='select')
    stewards = db.relationship('ProgrammeSteward', backref='programme', lazy='select')
    access_grants = db.relationship(
        'ProgrammeAccessGrant',
        backref='programme',
        lazy='select',
        cascade='all, delete-orphan'
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.name:
            self.slug = generate_slug(self.name)

    def update_slug(self):
        if self.name:
            self.slug = generate_slug(self.name)


class ProgrammeSteward(db.Model):
    __tablename__ = 'programme_steward'
    __table_args__ = (
        db.Index('ix_programme_steward_programme_id', 'programme_id'),
        db.Index('ix_programme_steward_user_id', 'user_id'),
        db.Index('ix_programme_steward_invite_token', 'invite_token', unique=True),
        db.UniqueConstraint('programme_id', 'user_id', name='uq_programme_steward_programme_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    pending_email = db.Column(db.String(150), nullable=True)  # set when inviting unregistered users
    role = db.Column(db.String(20), nullable=False, default='steward')
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    invite_token = db.Column(db.String(255), nullable=True)
    invited_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    invited_by = db.relationship('User', foreign_keys=[invited_by_id])

    @staticmethod
    def generate_invite_token():
        import secrets
        return secrets.token_urlsafe(32)


class ProgrammeAccessGrant(db.Model):
    __tablename__ = 'programme_access_grant'
    __table_args__ = (
        db.Index('ix_programme_access_programme_id', 'programme_id'),
        db.Index('ix_programme_access_user_id', 'user_id'),
        db.Index('ix_programme_access_status', 'status'),
        db.UniqueConstraint('programme_id', 'user_id', name='uq_programme_access_programme_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    user = db.relationship('User', foreign_keys=[user_id])
    invited_by = db.relationship('User', foreign_keys=[invited_by_id])


class Discussion(db.Model):
    __table_args__ = (
        db.Index('idx_discussion_title_desc', 'title', 'description'),
        db.Index('idx_discussion_created_at', 'created_at'),
        db.Index('idx_discussion_creator_id', 'creator_id'),
        db.Index('idx_discussion_is_featured', 'is_featured'),
        db.Index('idx_discussion_topic', 'topic'),
        db.Index('idx_discussion_partner_article_url', 'partner_article_url'),
        db.Index('idx_discussion_partner_external_id', 'partner_external_id'),
        db.Index('uq_discussion_partner_env_external_id_slug', 'partner_env', 'partner_id', 'partner_external_id', unique=True),
        db.Index('idx_discussion_partner_id', 'partner_id'),
        db.Index('idx_discussion_partner_env_created', 'partner_env', 'created_at'),
        db.Index('idx_discussion_programme_id', 'programme_id'),
        db.Index('idx_discussion_programme_phase', 'programme_id', 'programme_phase'),
        db.Index('idx_discussion_programme_theme', 'programme_id', 'programme_theme'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    embed_code = db.Column(db.String(800), nullable=True)  # Nullable for native discussions
    has_native_statements = db.Column(db.Boolean, default=False)  # Native vs pol.is embed mode
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    keywords = db.Column(db.String(200))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    # Geographic fields and other properties
    geographic_scope = db.Column(db.String(20), nullable=False, default='country')
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    topic = db.Column(db.String(100))
    is_featured = db.Column(db.Boolean, default=False)
    participant_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Foreign keys to link discussions to profiles
    individual_profile_id = db.Column(db.Integer, db.ForeignKey('individual_profile.id'), nullable=True)
    company_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=True)
    programme_phase = db.Column(db.String(50), nullable=True)
    programme_theme = db.Column(db.String(100), nullable=True)
    information_title = db.Column(db.String(200), nullable=True)
    information_body = db.Column(db.Text, nullable=True)
    information_links = db.Column(db.JSON, nullable=False, default=list)
    views = db.relationship('DiscussionView', backref='discussion', lazy='dynamic')
    follows = db.relationship('DiscussionFollow', backref='discussion', lazy='dynamic', cascade='all, delete-orphan')
    updates = db.relationship('DiscussionUpdate', backref='discussion', lazy='dynamic', cascade='all, delete-orphan')

    # Bluesky posting schedule (for staggered posts throughout the day)
    bluesky_scheduled_at = db.Column(db.DateTime, nullable=True)   # When to post to Bluesky
    bluesky_claimed_at = db.Column(db.DateTime, nullable=True)     # Set when a worker claims this post (cleared on completion or failure)
    bluesky_posted_at = db.Column(db.DateTime, nullable=True)      # Set ONLY when the post is confirmed live on Bluesky (has a URI)
    bluesky_post_uri = db.Column(db.String(500), nullable=True)    # Bluesky post URI — the source of truth that posting succeeded
    bluesky_skipped = db.Column(db.Boolean, nullable=False, default=False)  # True if intentionally not posted (too old, off-topic, etc.)

    # X/Twitter posting schedule (mirrors Bluesky pattern)
    x_scheduled_at = db.Column(db.DateTime, nullable=True)         # When to post to X
    x_claimed_at = db.Column(db.DateTime, nullable=True)           # Set when a worker claims this post (cleared on completion or failure)
    x_posted_at = db.Column(db.DateTime, nullable=True)            # Set ONLY when the post is confirmed live on X (has an ID)
    x_post_id = db.Column(db.String(100), nullable=True)           # X tweet ID — the source of truth that posting succeeded
    x_skipped = db.Column(db.Boolean, nullable=False, default=False)  # True if intentionally not posted (disabled tier, too old, etc.)

    # Partner embed integration (Phase 2)
    # For discussions created by partners whose content is not ingested via RSS
    partner_article_url = db.Column(db.String(1000), nullable=True)  # Normalized URL
    partner_external_id = db.Column(db.String(128), nullable=True)  # Partner-defined stable ID for non-article discussions
    # Partner-controlled embed behavior:
    # False = vote/report only, True = allow reader statement submissions from embed.
    embed_statement_submissions_enabled = db.Column(db.Boolean, nullable=False, default=False)
    partner_id = db.Column(db.String(50), nullable=True)  # Partner slug (legacy identifier)
    partner_fk_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=True, index=True)
    partner_env = db.Column(db.String(10), default='live', nullable=False, index=True)  # test | live
    # Audit: which API key (by DB id) was used to create this discussion.
    # Nullable for RSS-ingested and legacy rows. Allows "who created this?" lookups without
    # exposing the raw key — join to PartnerApiKey for key_prefix / key_last4.
    created_by_key_id = db.Column(db.Integer, db.ForeignKey('partner_api_key.id'), nullable=True)

    # Integrity controls (§8)
    # Enable stricter rate limits and monitoring for high-profile or sensitive discussions
    integrity_mode = db.Column(db.Boolean, default=False, nullable=False)

    # Discussion lifecycle
    # Closed discussions remain visible but no longer accept votes (embed or full site)
    is_closed = db.Column(db.Boolean, default=False, nullable=False)

    # Constants for geographic scope
    SCOPE_GLOBAL = 'global'
    SCOPE_COUNTRY = 'country'
    SCOPE_CITY = 'city'

    # Define topics for validation
    TOPICS = [
        'Healthcare', 'Environment', 'Education', 'Technology', 'Economy', 
        'Politics', 'Society', 'Infrastructure', 'Geopolitics', 'Business', 'Culture'
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.title:
            self.slug = generate_slug(self.title)

    def update_slug(self):
        if self.title:
            self.slug = generate_slug(self.title)

    @property
    def location_display(self):
        """Returns formatted location based on geographic scope"""
        if self.geographic_scope == self.SCOPE_GLOBAL:
            return "Global Discussion"
        elif self.geographic_scope == self.SCOPE_COUNTRY:
            return self.country
        else:
            return f"{self.city}, {self.country}"

    def to_dict(self):
        return {
            'id': self.id,
            'embed_code': self.embed_code,  # Store full embed code in dictionary
            'title': self.title,
            'description': self.description,
            'keywords': self.keywords,  # Include keywords here
            'slug': self.slug,
            'geographic_scope': self.geographic_scope,
            'country': self.country,
            'city': self.city,
            'topic': self.topic,
            'is_featured': self.is_featured,
            'participant_count': self.participant_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


    def get_featured(limit=6):
        # Try to get from cache first, fallback to direct query if cache fails
        cache_key = f'featured_discussions_{limit}'
        try:
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
        except Exception as e:
            # Log cache error but continue with database query
            current_app.logger.warning(f"Cache get failed for featured discussions: {e}")
        
        # First get discussions marked as featured, excluding test discussions
        featured = Discussion.query\
            .filter_by(is_featured=True)\
            .filter(Discussion.partner_env != 'test')\
            .filter(~Discussion.title.ilike('%test%'))\
            .filter(~Discussion.description.ilike('%test%'))\
            .order_by(Discussion.created_at.desc())\
            .all()

        # If we have fewer than limit (6), add recent non-featured discussions
        if len(featured) < limit:
            featured_ids = [d.id for d in featured]
            additional = Discussion.query\
                .filter(Discussion.id.notin_(featured_ids))\
                .filter(Discussion.partner_env != 'test')\
                .filter(~Discussion.title.ilike('%test%'))\
                .filter(~Discussion.description.ilike('%test%'))\
                .order_by(Discussion.created_at.desc())\
                .limit(limit - len(featured))\
                .all()
            featured.extend(additional)

        result = featured[:limit]
        
        # Try to cache the result, but don't fail if caching fails
        try:
            cache.set(cache_key, result, timeout=300)  # Cache for 5 minutes
        except Exception as e:
            current_app.logger.warning(f"Cache set failed for featured discussions: {e}")
        
        return result

    @staticmethod
    def feature_discussion(discussion_id, feature=True):
        """Manually feature or unfeature a discussion"""
        discussion = db.get_or_404(Discussion, discussion_id)
        discussion.is_featured = feature
        db.session.commit()
        return discussion

    @classmethod
    def auto_feature_discussions(cls):
        """Automatically feature discussions with balanced criteria"""
        total_count = cls.query.count()

        if total_count <= 6:
            # If we have 6 or fewer discussions total, feature them all
            cls.query.update({cls.is_featured: True})
            db.session.commit()
            return cls.query.all()

        # If we have more than 6 discussions, use the balanced criteria
        cls.query.update({cls.is_featured: False})
        db.session.commit()

        featured = []

        # Get one discussion per topic from the last 30 days
        for topic in cls.TOPICS:
            discussion = cls.query\
                .filter(
                    cls.topic == topic,
                    cls.created_at >= (utcnow_naive() - timedelta(days=30))
                )\
                .order_by(cls.created_at.desc())\
                .first()

            if discussion:
                discussion.is_featured = True
                featured.append(discussion)

        # If we need more to reach 6, add most recent discussions
        if len(featured) < 6:
            additional = cls.query\
                .filter(cls.id.notin_([d.id for d in featured]))\
                .order_by(cls.created_at.desc())\
                .limit(6 - len(featured))\
                .all()

            for discussion in additional:
                discussion.is_featured = True

        db.session.commit()
        return featured


    
    @staticmethod
    def search_discussions(
        search=None,
        country=None,
        city=None,
        topic=None,
        scope=None,
        keywords=None,
        programme_id=None,
        programme_phase=None,
        programme_theme=None,
        page=1,
        per_page=9
    ):
        query = Discussion.query.options(db.joinedload(Discussion.creator)).filter(Discussion.partner_env != 'test')
        query = query.outerjoin(Programme, Discussion.programme_id == Programme.id).filter(
            db.or_(
                Discussion.programme_id.is_(None),
                db.and_(Programme.status == 'active', Programme.visibility == 'public')
            )
        )

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                db.or_(
                    Discussion.title.ilike(search_term),
                    Discussion.description.ilike(search_term)
                )
            )

        if scope:
            query = query.filter(Discussion.geographic_scope == scope)

        if country:
            query = query.filter(Discussion.country.ilike(f"%{country}%"))

        if city:
            query = query.filter(Discussion.city.ilike(f"%{city}%"))

        if topic:
            query = query.filter(Discussion.topic == topic)

        # New keyword filtering
        if keywords:
            query = query.filter(Discussion.keywords.ilike(f"%{keywords}%"))

        if programme_id:
            query = query.filter(Discussion.programme_id == programme_id)

        if programme_phase:
            query = query.filter(Discussion.programme_phase == programme_phase)

        if programme_theme:
            query = query.filter(Discussion.programme_theme == programme_theme)

        return query.order_by(Discussion.created_at.desc())\
                    .paginate(page=page, per_page=per_page, error_out=False)


# ============================================================================
# Native Debate System Models (Phase 1)
# Adapted from pol.is architecture (AGPL-3.0)
# ============================================================================

class Statement(db.Model):
    """
    Core claim/proposition in native debates (analogous to pol.is 'comments')
    
    Based on pol.is data model patterns:
    - Per-discussion auto-incrementing tid (not global id)
    - Content limited to 500 chars (pol.is uses 1000)
    - Unique constraint prevents duplicates per discussion
    """
    __tablename__ = 'statement'
    __table_args__ = (
        db.Index('idx_statement_discussion', 'discussion_id'),
        db.Index('idx_statement_user', 'user_id'),
        db.Index('idx_statement_session', 'session_fingerprint'),
        db.Index('idx_statement_source', 'source'),
        # Read-path indexes for paginated/sorted statement lists.
        db.Index(
            'idx_statement_discussion_visibility_recent',
            'discussion_id',
            'is_deleted',
            'mod_status',
            'created_at',
            'id'
        ),
        db.Index(
            'idx_statement_discussion_visibility_agree',
            'discussion_id',
            'is_deleted',
            'mod_status',
            'vote_count_agree',
            'id'
        ),
        db.UniqueConstraint('discussion_id', 'content', name='uq_discussion_statement'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous users
    session_fingerprint = db.Column(db.String(64), nullable=True)  # For anonymous user tracking
    content = db.Column(db.Text, nullable=False)  # Max 500 chars (validated below)
    statement_type = db.Column(db.String(20), default='claim')  # 'claim' or 'question'
    parent_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    
    # Vote counts (denormalized for performance, like pol.is)
    vote_count_agree = db.Column(db.Integer, default=0)
    vote_count_disagree = db.Column(db.Integer, default=0)
    vote_count_unsure = db.Column(db.Integer, default=0)
    
    # Moderation (like pol.is mod field)
    mod_status = db.Column(db.Integer, default=0)  # -1=reject, 0=no action, 1=accept
    is_deleted = db.Column(db.Boolean, default=False)
    is_seed = db.Column(db.Boolean, default=False)  # Moderator-created seed statement

    # Source tracking for seed statements (§13 AI Attribution)
    # Values: 'ai_generated', 'partner_provided', 'user_submitted'
    source = db.Column(db.String(20), nullable=True)

    # Partner API seed_statements[].position: pro | con | neutral (nullable for non-seeds / legacy)
    seed_stance = db.Column(db.String(20), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    
    # Relationships
    discussion = db.relationship('Discussion', backref='statements')
    user = db.relationship('User', backref='statements')
    parent = db.relationship('Statement', remote_side=[id], backref='replies')
    
    @validates('content')
    def validate_content(self, key, content):
        """Enforce 10-500 character limit"""
        if not content or len(content.strip()) < 10:
            raise ValueError("Statement must be at least 10 characters")
        if len(content) > 500:
            raise ValueError("Statement must not exceed 500 characters")
        return content.strip()
    
    @property
    def total_votes(self):
        """Total number of votes cast on this statement"""
        return self.vote_count_agree + self.vote_count_disagree + self.vote_count_unsure
    
    @property
    def agreement_rate(self):
        """Percentage of agree votes (excluding unsure)"""
        decisive_votes = self.vote_count_agree + self.vote_count_disagree
        if decisive_votes == 0:
            return 0
        return self.vote_count_agree / decisive_votes
    
    @property
    def controversy_score(self):
        """
        Controversy score: 1 - |agree_rate - 0.5| * 2
        High score (close to 1) = controversial (~50/50 split)
        Low score (close to 0) = consensus
        """
        if self.total_votes < 5:
            return 0
        return 1 - abs(self.agreement_rate - 0.5) * 2
    
    def to_dict(self):
        return {
            'id': self.id,
            'discussion_id': self.discussion_id,
            'user_id': self.user_id,
            'content': self.content,
            'statement_type': self.statement_type,
            'parent_statement_id': self.parent_statement_id,
            'vote_count_agree': self.vote_count_agree,
            'vote_count_disagree': self.vote_count_disagree,
            'vote_count_unsure': self.vote_count_unsure,
            'total_votes': self.total_votes,
            'agreement_rate': self.agreement_rate,
            'controversy_score': self.controversy_score,
            'is_seed': self.is_seed,
            'source': self.source,  # ai_generated, partner_provided, user_submitted
            'seed_stance': self.seed_stance,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class StatementVote(db.Model):
    """
    User votes on statements - THE CORE DATA FOR CLUSTERING
    
    Based on pol.is 'votes' table:
    - vote values: -1 (disagree), 0 (unsure), 1 (agree)
    - Users can change votes (history preserved)
    - Supports both authenticated (user_id) and anonymous (session_fingerprint) voting
    - Anonymous votes can be merged to user account on signup/login
    
    Database constraints (created via SQL, not ORM):
    - uq_statement_user_vote: UNIQUE (statement_id, user_id) WHERE user_id IS NOT NULL
    - uq_statement_session_vote: UNIQUE (statement_id, session_fingerprint) WHERE session_fingerprint IS NOT NULL
    """
    __tablename__ = 'statement_vote'
    __table_args__ = (
        db.Index('idx_vote_discussion_user', 'discussion_id', 'user_id'),
        db.Index('idx_vote_discussion_statement', 'discussion_id', 'statement_id'),
        db.Index('idx_vote_session_fingerprint', 'session_fingerprint'),
        db.Index('idx_vote_partner_ref', 'partner_ref'),
        db.Index('idx_vote_discussion_cohort', 'discussion_id', 'cohort_slug'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    
    vote = db.Column(db.SmallInteger, nullable=False)

    confidence = db.Column(db.SmallInteger, nullable=True)

    # Partner attribution for embed votes (e.g., 'observer', 'time', 'ted')
    partner_ref = db.Column(db.String(50), nullable=True)
    cohort_slug = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    
    statement = db.relationship('Statement', backref='votes')
    user = db.relationship('User', backref='statement_votes')
    discussion = db.relationship('Discussion', backref='statement_votes')
    
    @classmethod
    def merge_anonymous_votes(cls, session_fingerprint, user_id):
        """
        Merge anonymous votes to a user account when they sign up or log in.
        If user already voted on a statement, keep their authenticated vote and
        decrement the denormalized counts to avoid inflation.
        """
        from app.models import Statement
        
        anonymous_votes = cls.query.filter_by(session_fingerprint=session_fingerprint, user_id=None).all()
        merged_count = 0
        
        for anon_vote in anonymous_votes:
            existing_user_vote = cls.query.filter_by(
                statement_id=anon_vote.statement_id,
                user_id=user_id
            ).first()
            
            if existing_user_vote:
                statement = db.session.get(Statement, anon_vote.statement_id)
                if statement:
                    if anon_vote.vote == 1:
                        statement.vote_count_agree = max(0, statement.vote_count_agree - 1)
                    elif anon_vote.vote == -1:
                        statement.vote_count_disagree = max(0, statement.vote_count_disagree - 1)
                    elif anon_vote.vote == 0:
                        statement.vote_count_unsure = max(0, statement.vote_count_unsure - 1)
                db.session.delete(anon_vote)
            else:
                anon_vote.user_id = user_id
                anon_vote.session_fingerprint = None
                merged_count += 1
        
        db.session.commit()
        return merged_count
    
    @validates('vote')
    def validate_vote(self, key, vote):
        """Ensure vote is -1, 0, or 1"""
        if vote not in [-1, 0, 1]:
            raise ValueError("Vote must be -1 (disagree), 0 (unsure), or 1 (agree)")
        return vote
    
    @validates('confidence')
    def validate_confidence(self, key, confidence):
        """Ensure confidence is 1-5 if provided"""
        if confidence is not None and (confidence < 1 or confidence > 5):
            raise ValueError("Confidence must be between 1 and 5")
        return confidence




class Response(db.Model):
    """
    Elaborations on why user voted a certain way (our enhancement beyond pol.is)
    Enables threaded discussions with pro/con structure
    """
    __tablename__ = 'response'
    __table_args__ = (
        db.Index('idx_response_statement', 'statement_id'),
        db.Index('idx_response_user', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous
    parent_response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=True)

    # Support for anonymous responses (synced from daily questions)
    session_fingerprint = db.Column(db.String(64), nullable=True)
    is_anonymous = db.Column(db.Boolean, default=False)

    position = db.Column(db.String(20))  # 'pro', 'con', 'neutral'
    content = db.Column(db.Text)  # Optional elaboration
    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    
    # Relationships
    statement = db.relationship('Statement', backref='responses')
    user = db.relationship('User', backref='responses')
    parent = db.relationship('Response', remote_side=[id], backref='replies')


class Evidence(db.Model):
    """
    Supporting evidence for responses (our enhancement beyond pol.is)
    """
    __tablename__ = 'evidence'
    __table_args__ = (
        db.Index('idx_evidence_response', 'response_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    
    source_title = db.Column(db.String(500))
    source_url = db.Column(db.String(1000))
    citation = db.Column(db.Text)
    quality_status = db.Column(db.String(20), default='pending')  # 'pending', 'verified', 'disputed'
    
    # For Replit object storage (Phase 0.6)
    storage_key = db.Column(db.String(500))  # Replit object storage key
    storage_url = db.Column(db.String(1000))  # Public URL
    
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Relationships
    response = db.relationship('Response', backref='evidence')
    added_by = db.relationship('User', backref='added_evidence')




class ProgrammeExportJob(db.Model):
    """Asynchronous programme export job + audit trail."""
    __tablename__ = 'programme_export_job'
    __table_args__ = (
        db.Index('idx_export_job_status_queued_at', 'status', 'queued_at'),
        db.Index('idx_export_job_programme_created', 'programme_id', 'created_at'),
        db.Index('idx_export_job_requested_by', 'requested_by_user_id', 'created_at'),
        db.Index('idx_export_job_dedupe', 'dedupe_key'),
    )

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_STALE = 'stale'
    STATUS_DEAD_LETTER = 'dead_letter'
    ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=False)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    export_format = db.Column(db.String(10), nullable=False, default='csv')
    cohort_slug = db.Column(db.String(80), nullable=True)
    dedupe_key = db.Column(db.String(255), nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_QUEUED)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=900)
    error_message = db.Column(db.Text, nullable=True)

    storage_key = db.Column(db.String(500), nullable=True)
    artifact_filename = db.Column(db.String(255), nullable=True)
    content_type = db.Column(db.String(100), nullable=True)
    artifact_size_bytes = db.Column(db.Integer, nullable=True)

    queued_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    programme = db.relationship('Programme', backref='export_jobs')
    requested_by = db.relationship('User', backref='programme_export_jobs')

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_timed_out(self):
        if self.status != self.STATUS_RUNNING or not self.started_at:
            return False
        return (utcnow_naive() - self.started_at) > timedelta(seconds=max(0, self.timeout_seconds or 0))


class JourneyReminderSubscription(db.Model):
    """
    Tracks a user's cadence preference for guided journey reminder emails.
    Supports both authenticated users (user_id set) and anonymous users (email only).
    Follows the same nullable user_id pattern as DiscussionParticipant.
    """
    __tablename__ = 'journey_reminder_subscription'
    __table_args__ = (
        db.Index('ix_jrs_programme_id', 'programme_id'),
        db.Index('ix_jrs_user_id', 'user_id'),
        db.Index('ix_jrs_next_send_at', 'next_send_at'),
        db.UniqueConstraint('programme_id', 'user_id', name='uq_jrs_programme_user'),
    )

    CADENCE_WEEKLY = 'weekly'
    CADENCE_WEEKEND = 'weekend'
    CADENCE_TWICE_WEEKLY = 'twice_weekly'
    CADENCE_COMMUTE = 'commute'  # legacy alias kept for backward compat
    VALID_CADENCES = (CADENCE_WEEKLY, CADENCE_WEEKEND, CADENCE_TWICE_WEEKLY, CADENCE_COMMUTE)
    MAX_REMINDERS = 8

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    email = db.Column(db.String(150), nullable=False)
    cadence = db.Column(db.String(20), nullable=False)
    timezone = db.Column(db.String(50), default='UTC', nullable=False)
    preferred_hour = db.Column(db.Integer, default=8, nullable=False)
    preferred_minute = db.Column(db.Integer, default=0, nullable=False)
    next_send_at = db.Column(db.DateTime, nullable=True)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_count = db.Column(db.Integer, default=0, nullable=False)
    resume_token = db.Column(db.String(255), nullable=True, unique=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    programme = db.relationship('Programme', backref=db.backref('journey_reminder_subscriptions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('journey_reminder_subscriptions', lazy='dynamic'))

    def generate_resume_token(self, expires_hours=72):
        """Generate a magic-link token so anonymous users can resume their journey.
        Reuses the same secrets.token_urlsafe pattern as DailyQuestionSubscriber."""
        import secrets
        self.resume_token = secrets.token_urlsafe(32)
        self.token_expires_at = utcnow_naive() + timedelta(hours=expires_hours)
        return self.resume_token

    @staticmethod
    def verify_resume_token(token):
        """
        Return the subscription if the token is valid, unexpired, and active.
        Used for magic-link resumption — token freshness is enforced here
        because old resume links should not silently re-authenticate.
        """
        if not token:
            return None
        sub = JourneyReminderSubscription.query.filter_by(resume_token=token).first()
        if not sub:
            return None
        if sub.token_expires_at and utcnow_naive() > sub.token_expires_at:
            return None
        if sub.unsubscribed_at:
            return None
        return sub

    @staticmethod
    def find_by_unsubscribe_token(token):
        """
        Return the subscription matching this token regardless of expiry.
        Used for email unsubscribe links — CAN-SPAM / GDPR require these to
        work indefinitely, not just within the 72-hour resume window.
        Returns None only if the token doesn't match any row.
        """
        if not token:
            return None
        return JourneyReminderSubscription.query.filter_by(resume_token=token).first()

    def set_next_send_at(self, from_dt=None):
        """
        Calculate and store next_send_at based on cadence and the user's local timezone
        and preferred hour.  All scheduling is done in the user's local time and then
        converted back to UTC (naive) for storage.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        from datetime import timezone

        UTC = timezone.utc  # concrete instance, not the class

        from_dt = from_dt or utcnow_naive()
        hour = self.preferred_hour if self.preferred_hour is not None else 8
        minute = self.preferred_minute if self.preferred_minute is not None else 0

        try:
            tz = ZoneInfo(self.timezone or 'UTC')
        except (ZoneInfoNotFoundError, KeyError):
            tz = ZoneInfo('UTC')

        # Work in the user's local timezone so we schedule at the right local time.
        local_dt = from_dt.replace(tzinfo=UTC).astimezone(tz)
        wd = local_dt.weekday()  # 0=Mon … 6=Sun

        if self.cadence == self.CADENCE_WEEKLY:
            next_local = (local_dt + timedelta(days=7)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        elif self.cadence == self.CADENCE_WEEKEND:
            # Next Saturday in the user's local calendar
            days_ahead = (5 - wd) % 7 or 7
            next_local = (local_dt + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        elif self.cadence in (self.CADENCE_TWICE_WEEKLY, self.CADENCE_COMMUTE):
            # Next Tue (1) or Thu (3) — culture-neutral twice-a-week cadence
            twice_weekly_days = {0: 1, 1: 2, 2: 1, 3: 5, 4: 4, 5: 3, 6: 2}
            next_local = (local_dt + timedelta(days=twice_weekly_days[wd])).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        else:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "JourneyReminderSubscription %s has unrecognised cadence %r — next_send_at set to None",
                self.id, self.cadence,
            )
            self.next_send_at = None
            return

        # Convert back to naive UTC for storage (matches utcnow_naive convention)
        self.next_send_at = next_local.astimezone(UTC).replace(tzinfo=None)

    @property
    def is_due(self):
        return self.next_send_at is not None and utcnow_naive() >= self.next_send_at

    @property
    def is_active(self):
        return self.unsubscribed_at is None and self.reminder_count < self.MAX_REMINDERS




class StatementFlag(db.Model):
    """
    Moderation flags for statements (our enhancement)
    Supports both authenticated and anonymous flagging (from embed)
    """
    __tablename__ = 'statement_flag'
    __table_args__ = (
        db.Index('idx_flag_statement', 'statement_id'),
        db.Index('idx_flag_status', 'status'),
        db.Index('idx_flag_fingerprint', 'session_fingerprint'),
    )

    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    flagger_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous
    session_fingerprint = db.Column(db.String(64), nullable=True)  # For anonymous flagging

    flag_reason = db.Column(db.String(50))  # 'spam', 'harassment', 'misinformation', 'off_topic'
    additional_context = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'reviewed', 'dismissed'

    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    statement = db.relationship('Statement', backref='flags')
    flagger = db.relationship('User', foreign_keys=[flagger_user_id], backref='flags_created')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='flags_reviewed')


class UserAPIKey(db.Model):
    """
    User-provided API keys for optional LLM features (Phase 4)
    """
    __tablename__ = 'user_api_key'
    __table_args__ = (
        db.Index('idx_api_key_user', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # 'openai', 'anthropic'
    encrypted_api_key = db.Column(db.Text, nullable=False)  # Fernet encrypted
    is_active = db.Column(db.Boolean, default=True)
    last_validated = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Relationships
    user = db.relationship('User', backref='api_keys')


# =============================================================================
# TRENDING TOPICS SYSTEM (News-to-Deliberation Compiler)
# =============================================================================

class NewsSource(db.Model):
    """
    Curated allowlist of trusted news sources.
    Only fetch from sources on this list.
    """
    __tablename__ = 'news_source'
    __table_args__ = (
        db.Index('idx_news_source_active', 'is_active'),
        db.Index('idx_news_source_slug', 'slug', unique=True),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    feed_url = db.Column(db.String(500), nullable=False)
    source_type = db.Column(db.String(20), default='rss')  # 'rss', 'api', 'guardian', 'nyt'
    country = db.Column(db.String(100))  # Country the source primarily covers (e.g., 'United Kingdom', 'United States')
    
    reputation_score = db.Column(db.Float, default=0.8)  # 0-1 scale
    is_active = db.Column(db.Boolean, default=True)

    # Political leaning for coverage analysis (-3 to +3: left to right, 0 = center)
    political_leaning = db.Column(db.Float)  # -2=Left, -1=Lean Left, 0=Center, 1=Lean Right, 2=Right
    leaning_source = db.Column(db.String(50))  # 'allsides', 'mbfc', 'adfontesmedia', 'manual'
    leaning_updated_at = db.Column(db.DateTime)

    last_fetched_at = db.Column(db.DateTime)
    fetch_error_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Source profile fields
    slug = db.Column(db.String(200), nullable=True)
    source_category = db.Column(db.String(50), default='newspaper')  # 'podcast', 'newspaper', 'magazine', 'broadcaster'

    # Basic branding (for unclaimed sources)
    logo_url = db.Column(db.String(500), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Claiming fields
    claim_status = db.Column(db.String(20), default='unclaimed')  # 'unclaimed', 'pending', 'approved', 'rejected'
    claimed_by_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='SET NULL'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claim_requested_at = db.Column(db.DateTime, nullable=True)
    claim_requested_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    articles = db.relationship('NewsArticle', backref='source', lazy='dynamic')
    claimed_by = db.relationship('CompanyProfile', backref='claimed_sources', foreign_keys=[claimed_by_profile_id])
    claim_requested_by = db.relationship('User', backref='source_claims', foreign_keys=[claim_requested_by_id])

    @property
    def is_claimed(self):
        """Check if source has been claimed and approved."""
        return self.claim_status == 'approved' and self.claimed_by_profile_id is not None

    @property
    def display_logo(self):
        """
        Return logo info as a dict for template rendering.

        Returns:
            dict with 'type' ('profile' or 'url') and 'src' (filename or URL),
            or None if no logo is available.
        """
        if self.is_claimed and self.claimed_by and self.claimed_by.logo:
            return {'type': 'profile', 'src': self.claimed_by.logo}
        if self.logo_url:
            return {'type': 'url', 'src': self.logo_url}
        return None

    @property
    def display_description(self):
        """Return claimed profile description, or basic description."""
        if self.is_claimed and self.claimed_by and self.claimed_by.description:
            return self.claimed_by.description
        return self.description

    @property
    def political_leaning_label(self):
        """Return human-readable political leaning label based on AllSides ratings."""
        if self.political_leaning is None:
            return 'Unknown'
        if self.political_leaning <= -1.5:
            return 'Left'
        elif self.political_leaning <= -0.5:
            return 'Centre-Left'
        elif self.political_leaning <= 0.5:
            return 'Centre'
        elif self.political_leaning <= 1.5:
            return 'Centre-Right'
        else:
            return 'Right'

    def generate_slug(self):
        """Generate URL-friendly slug from name."""
        self.slug = generate_slug(self.name)

    def __repr__(self):
        return f'<NewsSource {self.name}>'


@event.listens_for(NewsSource, 'before_insert')
def auto_generate_source_slug(mapper, connection, target):
    """Auto-generate slug for new NewsSource records if not already set."""
    if not target.slug and target.name:
        base_slug = generate_slug(target.name)
        if not base_slug:
            import uuid
            base_slug = f"source-{uuid.uuid4().hex[:8]}"
        
        slug = base_slug
        suffix = 1
        while db.session.query(NewsSource).filter(NewsSource.slug == slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        target.slug = slug


class NewsArticle(db.Model):
    """
    Individual news articles fetched from sources.
    Stored separately for querying, deduplication, and auditing.

    URL Fields:
    - url: Raw URL from feed (preserved for audit/fallback)
    - normalized_url: Canonical form for partner API lookup (stripped tracking params, forced https, etc.)
    - url_hash: SHA-256 hash of normalized_url for fast indexing (first 32 chars)

    Lookup by article URL should use normalized_url, not url.
    See app/lib/url_normalizer.py for normalization rules.
    """
    __tablename__ = 'news_article'
    __table_args__ = (
        db.Index('idx_article_source', 'source_id'),
        db.Index('idx_article_fetched', 'fetched_at'),
        db.Index('idx_article_external_id', 'external_id'),
        db.Index('idx_article_normalized_url', 'normalized_url'),
        db.Index('idx_article_url_hash', 'url_hash'),
        db.UniqueConstraint('source_id', 'external_id', name='uq_source_article'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('news_source.id'), nullable=False)

    external_id = db.Column(db.String(500))  # Source's unique ID for deduplication
    title = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text)
    url = db.Column(db.String(1000), nullable=False)

    # Partner API lookup fields (see docstring above)
    normalized_url = db.Column(db.String(1000), nullable=True)  # Canonical URL for lookup
    url_hash = db.Column(db.String(32), nullable=True)  # SHA-256 hash for fast indexing
    
    published_at = db.Column(db.DateTime)
    fetched_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Scoring (computed at fetch time)
    sensationalism_score = db.Column(db.Float)  # 0-1: higher = more clickbait
    relevance_score = db.Column(db.Float)  # 0-1: discussion potential (1=policy debate, 0=product review)
    personal_relevance_score = db.Column(db.Float)  # 0-1: direct impact on daily life (economic/health/rights)

    # Geographic scope detection (AI-analyzed from content)
    geographic_scope = db.Column(db.String(20), default='unknown')  # 'global', 'regional', 'national', 'local', 'unknown'
    geographic_countries = db.Column(db.String(500))  # Comma-separated list of countries mentioned (e.g., "UK, US" or "Global")
    
    # Embedding for clustering (stored as JSON array of floats)
    title_embedding = db.Column(db.JSON)
    
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def __repr__(self):
        return f'<NewsArticle {self.title[:50]}...>'

    def set_normalized_url(self):
        """
        Set normalized_url and url_hash from the raw url.
        Called automatically on before_insert and before_update events.
        """
        if self.url:
            from app.lib.url_normalizer import normalize_url, url_hash
            self.normalized_url = normalize_url(self.url)
            self.url_hash = url_hash(self.url) if self.normalized_url else None


@event.listens_for(NewsArticle, 'before_insert')
def news_article_before_insert(mapper, connection, target):
    """Automatically set normalized_url on insert."""
    target.set_normalized_url()


@event.listens_for(NewsArticle, 'before_update')
def news_article_before_update(mapper, connection, target):
    """Automatically update normalized_url if url changed."""
    # Only recalculate if url has changed
    from sqlalchemy.orm import object_session
    from sqlalchemy import inspect
    state = inspect(target)
    if state.attrs.url.history.has_changes():
        target.set_normalized_url()


class TrendingTopic(db.Model):
    """
    A clustered news topic ready for deliberation.
    Multiple articles are grouped into one topic.
    """
    __tablename__ = 'trending_topic'
    __table_args__ = (
        db.Index('idx_topic_status', 'status'),
        db.Index('idx_topic_created', 'created_at'),
        db.Index('idx_topic_hold_until', 'hold_until'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    
    # The neutral framing question for discussion
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    
    # Canonical tags for long-term merging (LLM-derived)
    # e.g., ["uk", "nhs", "junior_doctors", "pay"]
    canonical_tags = db.Column(db.JSON)
    topic_slug = db.Column(db.String(200))  # Normalized slug from tags
    
    # Scoring (separate scores per ChatGPT's advice)
    civic_score = db.Column(db.Float)  # 0-1: Is this worthwhile for civic discussion?
    quality_score = db.Column(db.Float)  # 0-1: Non-clickbait, fact density, multi-source
    audience_score = db.Column(db.Float)  # 0-1: Appeal to target podcast audience
    risk_flag = db.Column(db.Boolean, default=False)  # Culture war / sensitive / defamation risk
    risk_reason = db.Column(db.String(200))  # Why it's flagged as risky
    
    # Primary topic category for the discussion
    primary_topic = db.Column(db.String(50))  # Maps to Discussion.TOPICS
    
    # Geographic scope (derived from source articles)
    geographic_scope = db.Column(db.String(20), default='global')  # 'global', 'country', 'regional'
    geographic_countries = db.Column(db.String(500))  # Comma-separated: "UK, US" or None for global
    
    source_count = db.Column(db.Integer, default=0)  # Number of unique sources
    
    # Embedding for question-level deduplication (last 30 days)
    topic_embedding = db.Column(db.JSON)
    
    # Workflow status
    status = db.Column(db.String(20), default='pending')
    # pending -> held -> pending_review -> approved -> published
    # pending -> held -> pending_review -> discarded
    # pending -> held -> pending_review -> merged
    
    hold_until = db.Column(db.DateTime)  # Cooldown window (30-90 mins)
    
    # If merged into another topic/discussion
    merged_into_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)
    merged_into_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    
    # Generated seed statements (JSON array)
    seed_statements = db.Column(db.JSON)  # [{"content": "...", "position": "pro/con/neutral"}]
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)
    
    # Link to created discussion (if published)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    
    # Relationships
    articles = db.relationship('TrendingTopicArticle', backref='topic', lazy='dynamic')
    merged_into_topic = db.relationship('TrendingTopic', remote_side=[id], backref='merged_topics')
    merged_into_discussion = db.relationship('Discussion', foreign_keys=[merged_into_discussion_id], backref='merged_topics')
    created_discussion = db.relationship('Discussion', foreign_keys=[discussion_id], backref='source_topic')
    reviewer = db.relationship('User', backref='reviewed_topics')
    
    HIGH_TRUST_SOURCES = [
        'bbc news', 'the guardian', 'financial times', 'the economist',
        'foreign affairs', 'the atlantic', 'the new yorker', 'bloomberg',
        'the rest is politics', 'the news agents', 'all-in podcast',
        'triggernometry', 'the tim ferriss show', 'diary of a ceo', 'modern wisdom',
        'unherd', 'politico eu', 'the telegraph', 'the independent', 'techcrunch', 'axios'
    ]
    
    @property
    def is_high_confidence(self):
        """
        High confidence for publishing:
        - From a trusted source
        - Has civic relevance (worth discussing)
        - Not flagged as risky
        """
        return (
            self.has_trusted_source and
            (self.civic_score or 0) >= 0.5 and
            not self.risk_flag
        )
    
    @property
    def has_trusted_source(self):
        """Check if any article is from a high-trust source."""
        for ta in self.articles:
            if ta.article and ta.article.source:
                if ta.article.source.name.lower() in self.HIGH_TRUST_SOURCES:
                    return True
        return False
    
    @property
    def should_auto_publish(self):
        """
        Auto-publish criteria:
        - Has civic relevance (worth discussing)
        - Not flagged as risky
        All curated sources are trusted by default.
        """
        return (
            (self.civic_score or 0) >= 0.5 and
            not self.risk_flag
        )
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'canonical_tags': self.canonical_tags,
            'civic_score': self.civic_score,
            'quality_score': self.quality_score,
            'risk_flag': self.risk_flag,
            'risk_reason': self.risk_reason,
            'source_count': self.source_count,
            'status': self.status,
            'hold_until': self.hold_until.isoformat() if self.hold_until else None,
            'seed_statements': self.seed_statements,
            'is_high_confidence': self.is_high_confidence,
            'created_at': self.created_at.isoformat(),
            'articles': [ta.article.title for ta in self.articles if ta.article]
        }
    
    def __repr__(self):
        return f'<TrendingTopic {self.title[:50]}...>'


class TrendingTopicArticle(db.Model):
    """
    Join table linking TrendingTopic to NewsArticle.
    Allows many-to-many with additional metadata.
    
    Foreign Key Behavior:
    - topic_id: CASCADE - auto-delete when topic is deleted
    - article_id: CASCADE - auto-delete when article is deleted
    """
    __tablename__ = 'trending_topic_article'
    __table_args__ = (
        db.Index('idx_tta_topic', 'topic_id'),
        db.Index('idx_tta_article', 'article_id'),
        db.UniqueConstraint('topic_id', 'article_id', name='uq_topic_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)
    
    # When this article was added to the topic
    added_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Similarity score to the topic centroid
    similarity_score = db.Column(db.Float)
    
    # Relationships
    article = db.relationship('NewsArticle', backref='topic_associations')


class DiscussionSourceArticle(db.Model):
    """
    Join table linking Discussion to NewsArticle for news-based discussions.
    Preserves source attribution when topics are published as discussions.
    
    Foreign Key Behavior:
    - discussion_id: CASCADE - auto-delete when discussion is deleted
    - article_id: SET NULL - preserve link record but clear article reference when article deleted
    """
    __tablename__ = 'discussion_source_article'
    __table_args__ = (
        db.Index('idx_dsa_discussion', 'discussion_id'),
        db.Index('idx_dsa_article', 'article_id'),
        db.UniqueConstraint('discussion_id', 'article_id', name='uq_discussion_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)
    added_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Relationships
    discussion = db.relationship('Discussion', backref='source_article_links')
    article = db.relationship('NewsArticle', backref='discussion_links')


class DailyBrief(db.Model):
    """
    Daily Sense-Making Brief - Evening news summary (6pm).
    Aggregates curated topics with coverage analysis, organised into sections.
    Separate from Daily Question (morning participation prompt).

    Supports two formats:
    - Legacy flat: 3-5 items ordered by position (backward compatible)
    - Sectioned: Items grouped by section (lead, politics, economy, etc.) at variable depth

    Also supports weekly briefs via brief_type='weekly'.
    """
    __tablename__ = 'daily_brief'
    __table_args__ = (
        db.Index('idx_brief_date', 'date'),
        db.Index('idx_brief_status', 'status'),
        db.Index('idx_brief_type_date', 'brief_type', 'date'),
        db.UniqueConstraint('date', 'brief_type', name='uq_daily_brief_date_type'),
    )

    id = db.Column(db.Integer, primary_key=True)

    date = db.Column(db.Date, nullable=False)  # Unique per brief_type (see composite constraint)
    title = db.Column(db.String(200))  # e.g., "Tuesday's Brief: Climate, Tech, Healthcare"
    intro_text = db.Column(db.Text)  # 2-3 sentence calm framing

    status = db.Column(db.String(20), default='draft')  # draft|ready|published|skipped

    # Brief type: daily (default) or weekly
    brief_type = db.Column(db.String(10), default='daily')  # daily|weekly

    # For weekly briefs: which week does this cover?
    week_start_date = db.Column(db.Date, nullable=True)  # Monday of the week
    week_end_date = db.Column(db.Date, nullable=True)    # Sunday of the week

    # Admin override tracking
    auto_selected = db.Column(db.Boolean, default=True)  # False if admin edited
    admin_edited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    admin_notes = db.Column(db.Text)  # Why was this edited/skipped?

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    published_at = db.Column(db.DateTime)

    # "Same Story, Different Lens" cross-perspective analysis
    # Shows how left/centre/right outlets frame the same story differently
    # Generated automatically during brief creation - see app/brief/lens_check.py
    lens_check = db.Column(db.JSON)

    # "The Week Ahead" events data
    # Generated during brief creation - see app/brief/generator.py
    week_ahead = db.Column(db.JSON)  # [{'title': '...', 'date': '...', 'description': '...', 'category': '...'}]

    # "Market Pulse" section data (aggregated from Polymarket)
    # Stored at brief level so it's not tied to individual items
    market_pulse = db.Column(db.JSON)  # [{'question': '...', 'probability': 0.65, ...}]

    # "What the World is Watching" section data (curated geopolitical prediction markets)
    # Same schema as market_pulse but filtered by world events categories + high volume
    world_events = db.Column(db.JSON)  # [{'question': '...', 'probability': 0.65, 'category': '...', ...}]

    # Relationships
    items = db.relationship('BriefItem', backref='brief', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='BriefItem.position')
    admin_editor = db.relationship('User', backref='edited_briefs', foreign_keys=[admin_edited_by])

    @property
    def item_count(self):
        """Number of items in this brief.
        
        Uses cached count if available (set by batch queries in routes)
        to prevent N+1 query issues.
        """
        if hasattr(self, '_cached_item_count'):
            return self._cached_item_count
        # Use count() method if available (for lazy/dynamic relationships)
        # Otherwise fall back to len() for eagerly loaded lists
        if hasattr(self.items, 'count') and callable(self.items.count):
            return self.items.count()
        try:
            return len(self.items)
        except TypeError:
            # Fallback: query the database directly
            return BriefItem.query.filter_by(brief_id=self.id).count()

    @classmethod
    def get_today(cls, brief_type='daily'):
        """Get today's brief (optionally by type)"""
        from datetime import date
        today = date.today()
        return cls.query.filter_by(date=today, status='published', brief_type=brief_type).first() or \
               cls.query.filter_by(date=today, status='ready', brief_type=brief_type).first()

    @classmethod
    def get_by_date(cls, brief_date, brief_type='daily'):
        """Get brief for a specific date (optionally by type)"""
        return cls.query.filter_by(date=brief_date, status='published', brief_type=brief_type).first() or \
               cls.query.filter_by(date=brief_date, status='ready', brief_type=brief_type).first()

    @property
    def is_sectioned(self):
        """Check if this brief uses the sectioned format (vs legacy flat)."""
        from app.brief.sections import is_sectioned_brief
        items = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        return is_sectioned_brief(items)

    @property
    def items_by_section(self):
        """Get items grouped by section for template rendering."""
        from app.brief.sections import group_items_by_section
        items = self.items.order_by(BriefItem.position).all() if hasattr(self.items, 'all') else list(self.items)
        return group_items_by_section(items)

    @property
    def reading_time(self):
        """Estimate reading time in minutes based on word count (~200 WPM).

        Returns 0 for empty briefs, otherwise at least 1 minute.
        """
        word_count = 0
        try:
            items = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        except Exception:
            return 0
        if not items:
            return 0
        for item in items:
            if item.headline:
                word_count += len(item.headline.split())
            if item.summary_bullets:
                for bullet in (item.summary_bullets or []):
                    if bullet:
                        word_count += len(str(bullet).split())
            if item.so_what:
                word_count += len(item.so_what.split())
            if item.personal_impact:
                word_count += len(item.personal_impact.split())
            if item.quick_summary:
                word_count += len(item.quick_summary.split())
        if word_count == 0:
            return 0
        return max(1, round(word_count / 200))

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'intro_text': self.intro_text,
            'status': self.status,
            'brief_type': self.brief_type,
            'item_count': self.item_count,
            'reading_time': self.reading_time,
            'items': [item.to_dict() for item in self.items.order_by(BriefItem.position)],
            'lens_check': self.lens_check,
            'week_ahead': self.week_ahead,
            'market_pulse': self.market_pulse,
            'world_events': self.world_events,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<DailyBrief {self.date} {self.brief_type} ({self.status})>'


class BriefItem(db.Model):
    """
    Individual story in a daily brief.
    References TrendingTopic for DRY principle.

    Items are grouped by section and rendered at different depth levels:
    - full: headline, 4 bullets, personal impact, so what, perspectives, deeper context
    - standard: headline, 2 bullets, so what, coverage bar
    - quick: headline + one-sentence summary (used for global roundup, week ahead)

    For backward compatibility, items without section/depth are treated as
    legacy flat items rendered with full depth.
    """
    __tablename__ = 'brief_item'
    __table_args__ = (
        db.Index('idx_brief_item_brief', 'brief_id'),
        db.Index('idx_brief_item_topic', 'trending_topic_id'),
        db.Index('idx_brief_item_section', 'brief_id', 'section'),
        db.UniqueConstraint('brief_id', 'position', name='uq_brief_position'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Overall display order (1-based)

    # Section and depth (new — nullable for backward compatibility with legacy briefs)
    # Section: which part of the brief this item belongs to (lead, politics, economy, etc.)
    # Depth: how much content to generate (full, standard, quick)
    section = db.Column(db.String(30), nullable=True)   # See app/brief/sections.VALID_SECTIONS
    depth = db.Column(db.String(15), nullable=True)      # 'full', 'standard', 'quick'

    # One-sentence summary for quick-depth items (replaces bullets)
    quick_summary = db.Column(db.Text, nullable=True)

    # Source (DRY - reference existing TrendingTopic)
    # RESTRICT prevents deleting topics that are used in briefs
    # Nullable for items that don't reference topics (e.g., week_ahead, market_pulse)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='RESTRICT'), nullable=True)

    # Generated content (LLM-created for brief context)
    headline = db.Column(db.String(200))  # Shorter, punchier than TrendingTopic title
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    personal_impact = db.Column(db.Text)  # One-sentence personal relevance ("Why This Matters To You")
    so_what = db.Column(db.Text)  # "So what?" analysis paragraph
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}

    # Coverage analysis (computed from TrendingTopic articles)
    coverage_distribution = db.Column(db.JSON)  # {'left': 0.2, 'center': 0.5, 'right': 0.3}
    coverage_imbalance = db.Column(db.Float)  # 0-1 score (0=balanced, 1=single perspective)
    source_count = db.Column(db.Integer)  # Number of unique sources
    sources_by_leaning = db.Column(db.JSON)  # {'left': ['Guardian'], 'center': ['BBC', 'FT'], 'right': []}
    blindspot_explanation = db.Column(db.Text)  # LLM-generated explanation for coverage gaps

    # Sensationalism (from source articles)
    sensationalism_score = db.Column(db.Float)  # Average of article scores
    sensationalism_label = db.Column(db.String(20))  # 'low', 'medium', 'high'

    # Verification links (LLM-extracted + admin additions)
    verification_links = db.Column(db.JSON)  # [{'tier': 'primary', 'url': '...', 'type': '...', 'description': '...', 'is_paywalled': bool}]

    # CTA to discussion
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    cta_text = db.Column(db.String(200))  # Customizable per item

    # Special item types
    is_underreported = db.Column(db.Boolean, default=False)  # "Under the Radar" bonus item

    # Polymarket Integration (optional market signal data)
    # Stored as JSON snapshot at brief generation time for historical accuracy
    # Schema: see PolymarketMarket.to_signal_dict()
    market_signal = db.Column(db.JSON)  # null if no matching market

    # Deeper context for "Want more detail?" feature
    deeper_context = db.Column(db.Text)  # Extended analysis and background

    # Audio/TTS integration (XTTS v2 - open source)
    audio_url = db.Column(db.String(500))  # URL to generated audio file
    audio_voice_id = db.Column(db.String(100))  # XTTS voice ID used
    audio_generated_at = db.Column(db.DateTime)  # When audio was generated

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='brief_items')
    discussion = db.relationship('Discussion', backref='brief_items')

    @property
    def effective_depth(self):
        """Get the rendering depth, defaulting to 'full' for legacy items."""
        return self.depth or 'full'

    @property
    def section_display_name(self):
        """Get the display name for this item's section."""
        from app.brief.sections import SECTIONS
        if self.section and self.section in SECTIONS:
            return SECTIONS[self.section]['display_name']
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'position': self.position,
            'section': self.section,
            'depth': self.depth,
            'quick_summary': self.quick_summary,
            'headline': self.headline,
            'summary_bullets': self.summary_bullets,
            'personal_impact': self.personal_impact,
            'so_what': self.so_what,
            'perspectives': self.perspectives,
            'coverage_distribution': self.coverage_distribution,
            'coverage_imbalance': self.coverage_imbalance,
            'source_count': self.source_count,
            'sources_by_leaning': self.sources_by_leaning,
            'blindspot_explanation': self.blindspot_explanation,
            'sensationalism_score': self.sensationalism_score,
            'sensationalism_label': self.sensationalism_label,
            'verification_links': self.verification_links,
            'discussion_id': self.discussion_id,
            'cta_text': self.cta_text,
            'is_underreported': self.is_underreported,
            'market_signal': self.market_signal,
            'deeper_context': self.deeper_context,
            'audio_url': self.audio_url,
            'audio_voice_id': self.audio_voice_id,
            'trending_topic': self.trending_topic.to_dict() if self.trending_topic else None
        }

    def __repr__(self):
        section_str = f' [{self.section}]' if self.section else ''
        return f'<BriefItem {self.position}.{section_str} {self.headline}>'


class NewsPerspectiveCache(db.Model):
    """
    Cache for perspective analysis generated on news transparency page.

    Separate from BriefItem to avoid coupling. Caches LLM-generated perspectives
    for topics that appear on /news but weren't in the daily brief.
    """
    __tablename__ = 'news_perspective_cache'
    __table_args__ = (
        db.Index('idx_npc_topic_date', 'trending_topic_id', 'generated_date'),
        db.UniqueConstraint('trending_topic_id', 'generated_date', name='uq_npc_topic_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)

    # Generated content (LLM-created)
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}
    so_what = db.Column(db.Text)  # "So what?" analysis
    personal_impact = db.Column(db.Text)  # "Why This Matters To You"

    # Cache metadata
    generated_date = db.Column(db.Date, nullable=False)  # Date generated for (allows re-generation)
    generated_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='news_perspective_cache')

    def to_dict(self):
        return {
            'id': self.id,
            'trending_topic_id': self.trending_topic_id,
            'perspectives': self.perspectives,
            'so_what': self.so_what,
            'personal_impact': self.personal_impact,
            'generated_date': self.generated_date.isoformat() if self.generated_date else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }

    def __repr__(self):
        return f'<NewsPerspectiveCache topic_id={self.trending_topic_id} date={self.generated_date}>'


class AudioGenerationJob(db.Model):
    """
    Tracks batch audio generation jobs for daily briefs.

    Allows generating audio for all items in a brief at once,
    with progress tracking and status updates.

    Optimized for Replit deployment with stale job recovery.
    """
    __tablename__ = 'audio_generation_job'
    __table_args__ = (
        db.Index('idx_audio_job_brief', 'brief_id'),
        db.Index('idx_audio_job_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    
    # Support both DailyBrief and BriefRun (polymorphic)
    brief_type = db.Column(db.String(20), nullable=False, default='daily_brief')  # 'daily_brief' | 'brief_run'
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=True)  # For DailyBrief
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=True)  # For BriefRun
    
    voice_id = db.Column(db.String(100), nullable=True)  # XTTS voice ID

    status = db.Column(db.String(20), nullable=False, default='queued')  # queued, processing, completed, failed
    progress = db.Column(db.Integer, default=0)  # 0-100 percentage
    total_items = db.Column(db.Integer, nullable=False)
    completed_items = db.Column(db.Integer, default=0)
    failed_items = db.Column(db.Integer, default=0)  # Track items that failed to generate
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    brief = db.relationship('DailyBrief', backref='audio_jobs', foreign_keys=[brief_id])
    brief_run = db.relationship('BriefRun', backref='audio_jobs', foreign_keys=[brief_run_id])

    @property
    def progress_percentage(self):
        """Calculate progress percentage based on processed items (completed + failed)."""
        if self.total_items == 0:
            return 0
        processed = (self.completed_items or 0) + (self.failed_items or 0)
        # Cap at 100% to handle edge cases
        return min(int((processed / self.total_items) * 100), 100)

    @property
    def is_stale(self):
        """Check if job is stuck in processing for too long (30 minutes)."""
        if self.status != 'processing' or not self.started_at:
            return False
        return utcnow_naive() - self.started_at > timedelta(minutes=30)

    def to_dict(self):
        return {
            'id': self.id,
            'brief_type': self.brief_type,
            'brief_id': self.brief_id,
            'brief_run_id': self.brief_run_id,
            'voice_id': self.voice_id,
            'status': self.status,
            'progress': self.progress_percentage,
            'total_items': self.total_items,
            'completed_items': self.completed_items or 0,
            'failed_items': self.failed_items or 0,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f'<AudioGenerationJob brief_id={self.brief_id} status={self.status} progress={self.progress_percentage}%>'




class DailyBriefSubscriber(db.Model):
    """
    Subscribers to daily brief (separate from daily question).
    Supports paid tiers and timezone preferences.
    """
    __tablename__ = 'daily_brief_subscriber'
    __table_args__ = (
        db.Index('idx_dbs_email', 'email'),
        db.Index('idx_dbs_token', 'magic_token'),
        db.Index('idx_dbs_team', 'team_id'),
        db.Index('idx_dbs_status', 'status'),
        db.Index('idx_dbs_tier_status', 'tier', 'status'),  # Composite index for tier+status queries
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)

    # Subscription tier
    tier = db.Column(db.String(20), default='trial')  # trial|free|individual|team
    trial_started_at = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)  # 30-day trial

    # Team management
    team_id = db.Column(db.Integer, db.ForeignKey('brief_team.id'), nullable=True)

    # Preferences
    timezone = db.Column(db.String(50), default='UTC')  # e.g., 'Europe/London', 'America/New_York'
    preferred_send_hour = db.Column(db.Integer, default=18)  # 6pm in their timezone (options: 6, 8, 18)

    # Brief cadence: daily (default) or weekly
    cadence = db.Column(db.String(10), default='daily')  # daily|weekly
    preferred_weekly_day = db.Column(db.Integer, default=6)  # Day for weekly delivery (0=Mon, 6=Sun)

    # Status
    status = db.Column(db.String(20), default='active')  # active|unsubscribed|bounced|payment_failed
    unsubscribed_at = db.Column(db.DateTime)

    # Magic link auth (reuse pattern from DailyQuestionSubscriber)
    magic_token = db.Column(db.String(64), unique=True)
    magic_token_expires = db.Column(db.DateTime)

    # Stripe integration
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    subscription_expires_at = db.Column(db.DateTime)  # For grace period

    # Optional: Link to User account
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    last_sent_at = db.Column(db.DateTime)
    last_brief_id_sent = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=True)
    total_briefs_received = db.Column(db.Integer, default=0)
    welcome_email_sent_at = db.Column(db.DateTime)  # Prevents duplicate welcome emails

    # Email analytics
    total_opens = db.Column(db.Integer, default=0)
    total_clicks = db.Column(db.Integer, default=0)
    last_opened_at = db.Column(db.DateTime)
    last_clicked_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref='brief_subscription')
    team = db.relationship('BriefTeam', backref='members')

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.magic_token_expires = utcnow_naive() + timedelta(hours=expires_hours)
        return self.magic_token

    @staticmethod
    def verify_magic_token(token):
        """Verify magic token and return subscriber if valid"""
        subscriber = DailyBriefSubscriber.query.filter_by(
            magic_token=token,
            status='active'
        ).first()

        if not subscriber:
            return None

        if subscriber.magic_token_expires and subscriber.magic_token_expires < utcnow_naive():
            return None

        return subscriber

    def start_trial(self, days=30):
        """Start free trial with specified duration (default 30 days)"""
        self.tier = 'trial'
        self.trial_started_at = utcnow_naive()
        self.trial_ends_at = utcnow_naive() + timedelta(days=days)
        self.status = 'active'

    def extend_trial(self, additional_days=30):
        """Extend trial by specified number of days"""
        if not self.trial_ends_at:
            self.trial_ends_at = utcnow_naive()
        self.trial_ends_at = self.trial_ends_at + timedelta(days=additional_days)
        self.tier = 'trial'

    def grant_free_access(self):
        """Grant permanent free access (admin use only)"""
        self.tier = 'free'
        self.trial_ends_at = None  # No expiration
        self.subscription_expires_at = None
        self.status = 'active'

    @property
    def trial_days_remaining(self):
        """Returns days remaining in trial, or None if not on trial"""
        if self.tier != 'trial' or not self.trial_ends_at:
            return None
        remaining = (self.trial_ends_at - utcnow_naive()).days
        return max(0, remaining)

    @property
    def is_trial_expired(self):
        """Check if trial has expired"""
        if self.tier != 'trial':
            return False
        if not self.trial_ends_at:
            return True
        return utcnow_naive() > self.trial_ends_at

    @property
    def subscription_status_display(self):
        """Human-readable subscription status for admin UI"""
        if self.tier == 'free':
            return 'Free (Admin)'
        elif self.tier == 'trial':
            if self.is_trial_expired:
                return 'Trial Expired'
            days = self.trial_days_remaining
            if days == 0:
                return 'Trial Expires Today'
            elif days == 1:
                return 'Trial: 1 day left'
            else:
                return f'Trial: {days} days left'
        elif self.tier in ['individual', 'team']:
            if self.subscription_expires_at:
                if utcnow_naive() > self.subscription_expires_at:
                    return f'{self.tier.title()} (Expired)'
                return f'{self.tier.title()} (Active)'
            return f'{self.tier.title()} (Pending)'
        return 'Unknown'

    def is_subscribed_eligible(self):
        """Check if subscriber should receive emails.

        The Daily Brief is free for all active subscribers — no tier or
        payment check is required.  Only the status field matters.
        """
        return self.status == 'active'

    def has_received_brief_today(self, brief_date=None):
        """Check if subscriber already received brief for given date (prevents duplicate sends)"""
        from datetime import date as date_type
        if brief_date is None:
            brief_date = date_type.today()

        if not self.last_sent_at:
            return False

        return self.last_sent_at.date() == brief_date

    def has_received_this_brief(self, brief_id):
        """DB-level idempotency: check if this specific brief was already sent"""
        return self.last_brief_id_sent == brief_id

    def can_receive_brief(self, brief_date=None, brief_id=None):
        """Full eligibility check including duplicate prevention"""
        if not self.is_subscribed_eligible():
            return False

        if brief_id is not None and self.has_received_this_brief(brief_id):
            return False

        if self.has_received_brief_today(brief_date):
            return False

        return True

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'tier': self.tier,
            'timezone': self.timezone,
            'preferred_send_hour': self.preferred_send_hour,
            'status': self.status,
            'is_eligible': self.is_subscribed_eligible(),
            'trial_ends_at': self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            'trial_days_remaining': self.trial_days_remaining,
            'is_trial_expired': self.is_trial_expired,
            'subscription_status_display': self.subscription_status_display
        }

    def __repr__(self):
        return f'<DailyBriefSubscriber {self.email} ({self.tier})>'


class BriefTeam(db.Model):
    """
    Multi-seat team subscriptions for daily brief.
    """
    __tablename__ = 'brief_team'
    __table_args__ = (
        db.Index('idx_brief_team_admin', 'admin_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))

    # Billing
    seat_limit = db.Column(db.Integer, default=5)
    price_per_seat = db.Column(db.Integer, default=800)  # $8.00 in cents (team rate)
    base_price = db.Column(db.Integer, default=4000)  # $40/month for 5 seats

    # Stripe
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))

    # Admin contact
    admin_email = db.Column(db.String(255))  # Who manages the team

    # Status
    status = db.Column(db.String(20), default='active')  # active|cancelled|payment_failed

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    @property
    def current_seat_count(self):
        """Number of active members"""
        return DailyBriefSubscriber.query.filter_by(
            team_id=self.id,
            status='active'
        ).count()

    @property
    def has_available_seats(self):
        """Check if team has available seats"""
        return self.current_seat_count < self.seat_limit

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'seat_limit': self.seat_limit,
            'current_seat_count': self.current_seat_count,
            'has_available_seats': self.has_available_seats,
            'admin_email': self.admin_email,
            'status': self.status
        }

    def __repr__(self):
        return f'<BriefTeam {self.name} ({self.current_seat_count}/{self.seat_limit} seats)>'


class UpcomingEvent(db.Model):
    """
    Upcoming events for the "Week Ahead" brief section.

    Events can be:
    - Auto-extracted from news articles (source='article')
    - Admin-curated via the admin panel (source='admin')
    - Imported from external calendars (source='api')

    Events are surfaced in the brief's "The Week Ahead" section,
    showing readers what's coming up in the next 7 days.
    """
    __tablename__ = 'upcoming_event'
    __table_args__ = (
        db.Index('idx_upcoming_event_date', 'event_date'),
        db.Index('idx_upcoming_event_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)  # One-sentence context
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.String(50))  # Optional: "14:00 UTC" or "All day"
    category = db.Column(db.String(50))  # politics, economy, science, society, etc.
    region = db.Column(db.String(50))  # asia_pacific, europe, americas, middle_east_africa, global
    importance = db.Column(db.String(10), default='medium')  # high, medium, low

    # Source tracking
    source = db.Column(db.String(20), default='admin')  # admin, article, api
    source_url = db.Column(db.String(500))  # Link to official page/announcement
    source_article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=True)

    # Status
    status = db.Column(db.String(20), default='active')  # active, used, cancelled, past

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationships
    source_article = db.relationship('NewsArticle', backref='upcoming_events')
    creator = db.relationship('User', backref='created_events')

    @classmethod
    def get_upcoming(cls, days_ahead=7, limit=10):
        """Get upcoming events within the next N days."""
        from datetime import date as date_type
        today = date_type.today()
        cutoff = today + timedelta(days=days_ahead)
        return cls.query.filter(
            cls.event_date >= today,
            cls.event_date <= cutoff,
            cls.status == 'active'
        ).order_by(cls.event_date.asc(), cls.importance.desc()).limit(limit).all()

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'event_date': self.event_date.isoformat(),
            'event_time': self.event_time,
            'category': self.category,
            'region': self.region,
            'importance': self.importance,
            'source': self.source,
            'source_url': self.source_url,
        }

    def __repr__(self):
        return f'<UpcomingEvent {self.event_date}: {self.title[:50]}>'


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

        # Import here to avoid circular import
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


class SocialPostEngagement(db.Model):
    """
    Tracks engagement metrics for social media posts over time.

    Stores likes, retweets/reposts, replies, and impressions for posts
    on X and Bluesky. Updated periodically by scheduler job.
    """
    __tablename__ = 'social_post_engagement'

    id = db.Column(db.Integer, primary_key=True)

    # Link to discussion (nullable for non-discussion posts like daily brief)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True, index=True)
    discussion = db.relationship('Discussion', backref=db.backref('social_engagements', lazy='dynamic'))

    # Platform and post identifier
    platform = db.Column(db.String(20), nullable=False)  # 'x' or 'bluesky'
    post_id = db.Column(db.String(500), nullable=False)  # Tweet ID or Bluesky URI

    # Content type for tracking different post types
    content_type = db.Column(db.String(50), nullable=False, default='discussion')  # 'discussion', 'daily_question', 'daily_brief', 'weekly_insights'

    # Hook variant used (for A/B testing)
    hook_variant = db.Column(db.String(50), nullable=True)

    # Engagement metrics
    likes = db.Column(db.Integer, default=0)
    reposts = db.Column(db.Integer, default=0)  # Retweets on X, reposts on Bluesky
    replies = db.Column(db.Integer, default=0)
    quotes = db.Column(db.Integer, default=0)
    impressions = db.Column(db.Integer, default=0)  # Views/impressions if available
    clicks = db.Column(db.Integer, default=0)  # Link clicks if available

    # Timestamps
    posted_at = db.Column(db.DateTime, nullable=False)
    last_updated = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Unique constraint on platform + post_id
    __table_args__ = (
        db.UniqueConstraint('platform', 'post_id', name='uq_platform_post_id'),
    )

    @property
    def total_engagement(self) -> int:
        """Total engagement (likes + reposts + replies + quotes)."""
        return (self.likes or 0) + (self.reposts or 0) + (self.replies or 0) + (self.quotes or 0)

    @property
    def engagement_rate(self) -> float:
        """Engagement rate as percentage of impressions."""
        if not self.impressions or self.impressions == 0:
            return 0.0
        return (self.total_engagement / self.impressions) * 100

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'platform': self.platform,
            'post_id': self.post_id,
            'content_type': self.content_type,
            'hook_variant': self.hook_variant,
            'likes': self.likes,
            'reposts': self.reposts,
            'replies': self.replies,
            'quotes': self.quotes,
            'impressions': self.impressions,
            'clicks': self.clicks,
            'total_engagement': self.total_engagement,
            'engagement_rate': self.engagement_rate,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }

