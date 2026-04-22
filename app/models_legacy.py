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
