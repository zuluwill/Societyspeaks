"""
Account-level models: User (with Flask-Login mixin, password + email
verification tokens, notification preferences) and UserAPIKey (per-user
encrypted LLM API keys for optional Phase 4 features).

Moved here from app/models.py as part of the models-split refactor
(this was the last domain submodule brought over before deleting the
shim / monolith file).

Notification lives in app.models.discussions and is pulled in lazily
inside User.unread_notification_count to avoid depending on a sibling
submodule at import time.
"""

from flask import current_app, g
from flask_login import UserMixin
from itsdangerous import URLSafeTimedSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from app.lib.time import utcnow_naive


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

    # Magic-link login: any signed token whose payload `iat` is earlier than
    # this timestamp is rejected. Bumped on every send (invalidates prior
    # pending tokens — latest-email-wins) and on successful consume
    # (one-shot — consumed link can't be clicked again). NULL = no magic
    # link has ever been issued for this user.
    magic_login_valid_after = db.Column(db.DateTime, nullable=True)

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

    # Token generation and verification methods for magic-link login.
    #
    # A magic-link token is a signed payload {'user_id', 'iat'} with a 15-min
    # itsdangerous max_age. Validity is additionally gated on
    # User.magic_login_valid_after: a token is accepted iff its iat is >= that
    # column. Callers MUST commit the session between get_* (which bumps the
    # column) and dispatching the email — otherwise a concurrent consumer
    # might read stale state. On successful consume, call
    # consume_magic_login_token() and commit to invalidate the link.
    MAGIC_LOGIN_EXPIRES_SEC = 15 * 60  # 15 minutes

    def get_magic_login_token(self, expires_sec=None):
        """Issue a magic-link token and invalidate any previously-pending one.

        Mutates ``self.magic_login_valid_after`` in the session — the caller is
        responsible for committing before sending the email.
        """
        now = utcnow_naive()
        self.magic_login_valid_after = now
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps(
            {'user_id': self.id, 'iat': now.isoformat()},
            salt='magic-login-salt',
        )

    @staticmethod
    def verify_magic_login_token(token, expiration=None):
        """Return the User if the token is signed, unexpired, and not superseded.

        Returns None for any failure mode (bad signature, expired, consumed,
        superseded by a newer send). Callers treat all None outcomes the
        same in user-facing copy.
        """
        from datetime import datetime
        if expiration is None:
            expiration = User.MAGIC_LOGIN_EXPIRES_SEC
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            payload = s.loads(token, salt='magic-login-salt', max_age=expiration)
        except Exception:
            return None
        user_id = payload.get('user_id')
        iat_raw = payload.get('iat')
        if not user_id or not iat_raw:
            return None
        user = db.session.get(User, user_id)
        if user is None or user.magic_login_valid_after is None:
            return None
        try:
            iat = datetime.fromisoformat(iat_raw)
        except (TypeError, ValueError):
            return None
        if iat < user.magic_login_valid_after:
            return None
        return user

    def consume_magic_login_token(self):
        """Invalidate the magic-link token just used. Caller commits."""
        self.magic_login_valid_after = utcnow_naive()

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
        except Exception:
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
        # Lazy import avoids pulling the discussions submodule into users
        # at import time.
        from app.models.discussions import Notification
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
