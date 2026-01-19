import stripe
from datetime import datetime, timedelta
from flask import current_app
from app import db
from app.models import User, CompanyProfile, PricingPlan, Subscription


def get_stripe():
    """Get configured Stripe module with API key from Flask config."""
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    return stripe


def get_or_create_stripe_customer(user):
    """Get existing Stripe customer or create a new one."""
    s = get_stripe()
    
    if user.stripe_customer_id:
        try:
            customer = s.Customer.retrieve(user.stripe_customer_id)
            if not customer.get('deleted'):
                return customer
        except s.error.InvalidRequestError:
            pass
    
    customer = s.Customer.create(
        email=user.email,
        name=user.username,
        metadata={'user_id': str(user.id)}
    )
    
    user.stripe_customer_id = customer.id
    db.session.commit()
    
    return customer


def create_checkout_session(user, plan_code, billing_interval='month', success_url=None, cancel_url=None):
    """Create a Stripe Checkout session for subscription."""
    s = get_stripe()
    
    plan = PricingPlan.query.filter_by(code=plan_code, is_active=True).first()
    if not plan:
        raise ValueError(f"Plan '{plan_code}' not found")
    
    price_id = plan.stripe_price_yearly_id if billing_interval == 'year' else plan.stripe_price_monthly_id
    if not price_id:
        raise ValueError(f"No Stripe price configured for plan '{plan_code}' ({billing_interval})")
    
    customer = get_or_create_stripe_customer(user)
    
    base_url = current_app.config.get('APP_BASE_URL', 'https://societyspeaks.io')
    
    session = s.checkout.Session.create(
        customer=customer.id,
        payment_method_types=['card'],
        mode='subscription',
        line_items=[{
            'price': price_id,
            'quantity': 1,
        }],
        subscription_data={
            'trial_period_days': 30,
            'metadata': {
                'user_id': str(user.id),
                'plan_code': plan_code,
            }
        },
        success_url=success_url or f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=cancel_url or f"{base_url}/briefings/landing",
        metadata={
            'user_id': str(user.id),
            'plan_code': plan_code,
            'billing_interval': billing_interval,
        }
    )
    
    return session


def create_portal_session(user, return_url=None):
    """Create a Stripe Customer Portal session for self-service billing management."""
    s = get_stripe()
    
    if not user.stripe_customer_id:
        raise ValueError("User has no Stripe customer ID")
    
    base_url = current_app.config.get('APP_BASE_URL', 'https://societyspeaks.io')
    
    session = s.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=return_url or f"{base_url}/briefings"
    )
    
    return session


def sync_subscription_from_stripe(stripe_subscription, user_id=None, org_id=None):
    """Create or update local subscription record from Stripe subscription data."""
    sub = Subscription.query.filter_by(stripe_subscription_id=stripe_subscription.id).first()
    
    plan_code = stripe_subscription.metadata.get('plan_code')
    plan = PricingPlan.query.filter_by(code=plan_code).first() if plan_code else None
    
    if not plan and stripe_subscription.items.data:
        price_id = stripe_subscription.items.data[0].price.id
        plan = PricingPlan.query.filter(
            (PricingPlan.stripe_price_monthly_id == price_id) | 
            (PricingPlan.stripe_price_yearly_id == price_id)
        ).first()
    
    if not plan:
        plan = PricingPlan.query.filter_by(code='starter').first()
        current_app.logger.warning(f"Could not find plan for subscription {stripe_subscription.id}, defaulting to starter")
    
    if not sub:
        sub = Subscription(
            stripe_subscription_id=stripe_subscription.id,
            stripe_customer_id=stripe_subscription.customer,
            user_id=user_id,
            org_id=org_id,
            plan_id=plan.id if plan else None,
        )
        db.session.add(sub)
    
    sub.status = stripe_subscription.status
    sub.current_period_start = datetime.fromtimestamp(stripe_subscription.current_period_start)
    sub.current_period_end = datetime.fromtimestamp(stripe_subscription.current_period_end)
    sub.cancel_at_period_end = stripe_subscription.cancel_at_period_end
    sub.billing_interval = stripe_subscription.items.data[0].price.recurring.interval if stripe_subscription.items.data else 'month'
    
    if stripe_subscription.trial_end:
        sub.trial_end = datetime.fromtimestamp(stripe_subscription.trial_end)
    
    if stripe_subscription.canceled_at:
        sub.canceled_at = datetime.fromtimestamp(stripe_subscription.canceled_at)
    
    if plan:
        sub.plan_id = plan.id
    
    db.session.commit()
    return sub


def get_active_subscription(user):
    """Get the user's active subscription, if any."""
    sub = Subscription.query.filter(
        Subscription.user_id == user.id,
        Subscription.status.in_(['trialing', 'active'])
    ).first()
    
    if sub:
        return sub
    
    if user.company_profile:
        sub = Subscription.query.filter(
            Subscription.org_id == user.company_profile.id,
            Subscription.status.in_(['trialing', 'active'])
        ).first()
    
    return sub


def check_feature_access(user, feature):
    """Check if user has access to a specific feature based on their subscription."""
    sub = get_active_subscription(user)
    if not sub:
        return False
    return sub.can_use_feature(feature)


def check_resource_limit(user, resource, current_count):
    """Check if user is within their resource limits."""
    sub = get_active_subscription(user)
    if not sub:
        return False
    return sub.check_limit(resource, current_count)


def get_user_plan(user):
    """Get the user's current plan, or None if no active subscription."""
    sub = get_active_subscription(user)
    return sub.plan if sub else None
