"""
Partner (B2B embed customer) models.

Partner — the top-level tenant record with billing and tier state,
password auth, and a kill-switch for the embed + public partner ref.
PartnerDomain — per-env (test | live) domain allowlist with DNS-TXT
or meta-tag verification.
PartnerApiKey — hashed API keys per-env with prefix/last4 for display.
PartnerWebhookEndpoint — outbound webhook configuration with encrypted
signing secret and per-endpoint event-type filter.
PartnerWebhookDelivery — per-event delivery attempts with retry state
and the HTTP response audit trail.
PartnerMember — team members with invite-token onboarding and
role-based permissions.
PartnerUsageEvent — raw usage ledger for billing and analytics.

Moved here from app/models.py as part of the models-split refactor.
No event listeners. No cross-submodule model imports.
"""

from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from app.lib.time import utcnow_naive


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
