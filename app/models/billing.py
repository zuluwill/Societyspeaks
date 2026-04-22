"""
Billing and subscription models.

PricingPlan, Subscription, and Donation. Moved here from app/models.py
as part of the models-split refactor. User and CompanyProfile are
referenced via string ('User', 'CompanyProfile') so this submodule
does not import them.
"""

from app import db
from app.lib.time import utcnow_naive


class PricingPlan(db.Model):
    """
    Pricing plans for the briefing subscription tiers.
    Pre-seeded with tier metadata and Stripe product/price IDs.
    """
    __tablename__ = 'pricing_plan'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # 'starter', 'professional', 'team', 'enterprise'
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # Pricing
    price_monthly = db.Column(db.Integer, nullable=False)  # In pence (e.g. £4.99 = 499)
    price_yearly = db.Column(db.Integer, nullable=True)    # In pence (e.g. £49 = 4900)
    currency = db.Column(db.String(3), default='GBP')

    # Stripe IDs
    stripe_product_id = db.Column(db.String(255), nullable=True)
    stripe_price_monthly_id = db.Column(db.String(255), nullable=True)
    stripe_price_yearly_id = db.Column(db.String(255), nullable=True)

    # Feature limits
    max_briefs = db.Column(db.Integer, default=1)        # -1 = unlimited
    max_sources = db.Column(db.Integer, default=10)      # -1 = unlimited
    max_recipients = db.Column(db.Integer, default=10)   # -1 = unlimited
    max_editors = db.Column(db.Integer, default=1)       # -1 = unlimited

    # Feature flags
    allow_document_uploads = db.Column(db.Boolean, default=False)
    allow_custom_branding = db.Column(db.Boolean, default=False)
    allow_approval_workflow = db.Column(db.Boolean, default=False)
    allow_slack_integration = db.Column(db.Boolean, default=False)
    allow_api_access = db.Column(db.Boolean, default=False)
    priority_processing = db.Column(db.Boolean, default=False)

    # Display
    is_active = db.Column(db.Boolean, default=True)
    is_organisation = db.Column(db.Boolean, default=False)  # Team/Enterprise plans
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    subscriptions = db.relationship('Subscription', backref='plan', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'price_monthly': self.price_monthly,
            'price_yearly': self.price_yearly,
            'currency': self.currency,
            'max_briefs': self.max_briefs,
            'max_sources': self.max_sources,
            'max_recipients': self.max_recipients,
            'max_editors': self.max_editors,
            'allow_document_uploads': self.allow_document_uploads,
            'allow_custom_branding': self.allow_custom_branding,
            'allow_approval_workflow': self.allow_approval_workflow,
            'allow_slack_integration': self.allow_slack_integration,
            'allow_api_access': self.allow_api_access,
            'priority_processing': self.priority_processing,
            'is_organisation': self.is_organisation,
        }

    def __repr__(self):
        return f'<PricingPlan {self.code}>'


class Subscription(db.Model):
    """
    User or organisation subscription tracking.
    Links to Stripe subscription for billing.
    """
    __tablename__ = 'subscription'
    __table_args__ = (
        db.Index('idx_subscription_user', 'user_id'),
        db.Index('idx_subscription_org', 'org_id'),
        db.Index('idx_subscription_status', 'status'),
        db.Index('idx_subscription_stripe', 'stripe_subscription_id'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Owner (either user or organisation, not both)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=True)

    # Plan
    plan_id = db.Column(db.Integer, db.ForeignKey('pricing_plan.id'), nullable=False)

    # Stripe data
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)

    # Status: 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'incomplete'
    status = db.Column(db.String(30), default='trialing')

    # Billing period
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    trial_end = db.Column(db.DateTime, nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    canceled_at = db.Column(db.DateTime, nullable=True)

    # Billing interval: 'month' or 'year'
    billing_interval = db.Column(db.String(10), default='month')

    # Team seats (for Team/Enterprise plans)
    seat_count = db.Column(db.Integer, default=1)

    # Extra data
    extra_data = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    user = db.relationship('User', backref=db.backref('subscriptions', lazy='dynamic'))
    org = db.relationship('CompanyProfile', backref=db.backref('subscriptions', lazy='dynamic'))

    @property
    def is_active(self):
        """Check if subscription is in an active state (trialing or active)"""
        return self.status in ('trialing', 'active')

    @property
    def is_trial(self):
        """Check if subscription is in trial period"""
        return self.status == 'trialing'

    @property
    def days_remaining(self):
        """Days remaining in trial or current billing period."""
        end_date = self.trial_end if self.status == 'trialing' and self.trial_end else self.current_period_end
        if not end_date:
            return None
        delta = end_date - utcnow_naive()
        return max(0, delta.days)

    def can_use_feature(self, feature):
        """Check if plan allows a specific feature"""
        feature_map = {
            'document_uploads': self.plan.allow_document_uploads,
            'custom_branding': self.plan.allow_custom_branding,
            'approval_workflow': self.plan.allow_approval_workflow,
            'slack_integration': self.plan.allow_slack_integration,
            'api_access': self.plan.allow_api_access,
            'priority_processing': self.plan.priority_processing,
        }
        return feature_map.get(feature, False)

    def check_limit(self, resource, current_count):
        """Check if a resource limit has been reached"""
        limit_map = {
            'briefs': self.plan.max_briefs,
            'sources': self.plan.max_sources,
            'recipients': self.plan.max_recipients,
            'editors': self.plan.max_editors,
        }
        limit = limit_map.get(resource)
        if limit is None or limit == -1:  # -1 means unlimited
            return True
        return current_count < limit

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'org_id': self.org_id,
            'plan': self.plan.to_dict() if self.plan else None,
            'status': self.status,
            'is_active': self.is_active,
            'is_trial': self.is_trial,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
            'trial_end': self.trial_end.isoformat() if self.trial_end else None,
            'cancel_at_period_end': self.cancel_at_period_end,
            'billing_interval': self.billing_interval,
            'seat_count': self.seat_count,
            'days_remaining': self.days_remaining,
        }

    def __repr__(self):
        owner = f'user:{self.user_id}' if self.user_id else f'org:{self.org_id}'
        return f'<Subscription {self.id} {owner} ({self.status})>'


class Donation(db.Model):
    """
    One-time public donations processed via Stripe Checkout.
    """
    __tablename__ = 'donation'
    __table_args__ = (
        db.Index('idx_donation_status', 'status'),
        db.Index('idx_donation_created_at', 'created_at'),
        db.Index('idx_donation_paid_at', 'paid_at'),
        db.Index('idx_donation_email', 'donor_email'),
    )

    id = db.Column(db.Integer, primary_key=True)

    stripe_checkout_session_id = db.Column(db.String(255), unique=True, nullable=False)
    stripe_payment_intent_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_charge_id = db.Column(db.String(255), nullable=True)

    amount_pence = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='gbp')

    # pending | paid | failed | refunded
    status = db.Column(db.String(30), nullable=False, default='pending')
    paid_at = db.Column(db.DateTime, nullable=True)

    donor_email = db.Column(db.String(255), nullable=True)
    donor_name = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=True)
    is_anonymous = db.Column(db.Boolean, nullable=False, default=False)

    metadata_json = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def to_dict(self):
        return {
            'id': self.id,
            'stripe_checkout_session_id': self.stripe_checkout_session_id,
            'stripe_payment_intent_id': self.stripe_payment_intent_id,
            'stripe_charge_id': self.stripe_charge_id,
            'amount_pence': self.amount_pence,
            'currency': self.currency,
            'status': self.status,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'donor_email': self.donor_email,
            'donor_name': self.donor_name,
            'message': self.message,
            'is_anonymous': self.is_anonymous,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Donation {self.id} {self.amount_pence}{self.currency} ({self.status})>'
