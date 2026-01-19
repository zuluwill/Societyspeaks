import stripe
from flask import request, redirect, url_for, jsonify, flash, current_app
from flask_login import login_required, current_user
from app.billing import billing_bp
from app.billing.service import (
    create_checkout_session,
    create_portal_session,
    sync_subscription_from_stripe,
    get_active_subscription,
    get_stripe,
)
from app.models import User, PricingPlan, Subscription
from app import db


@billing_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """Start a Stripe Checkout session for subscription."""
    plan_code = request.form.get('plan', 'starter')
    billing_interval = request.form.get('interval', 'month')
    
    try:
        session = create_checkout_session(
            user=current_user,
            plan_code=plan_code,
            billing_interval=billing_interval
        )
        return redirect(session.url, code=303)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('briefing.landing'))
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        flash('Payment system error. Please try again.', 'error')
        return redirect(url_for('briefing.landing'))


@billing_bp.route('/success')
@login_required
def checkout_success():
    """Handle successful checkout redirect."""
    s = get_stripe()
    session_id = request.args.get('session_id')
    
    if session_id:
        try:
            session = s.checkout.Session.retrieve(session_id)
            if session.subscription:
                stripe_sub = s.Subscription.retrieve(session.subscription)
                user_id = int(session.metadata.get('user_id', current_user.id))
                sync_subscription_from_stripe(stripe_sub, user_id=user_id)
        except s.error.StripeError as e:
            current_app.logger.error(f"Error retrieving checkout session: {e}")
    
    flash('Welcome! Your subscription is now active.', 'success')
    return redirect(url_for('briefing.my_briefings'))


@billing_bp.route('/portal')
@login_required
def customer_portal():
    """Redirect to Stripe Customer Portal for billing management."""
    try:
        session = create_portal_session(current_user)
        return redirect(session.url, code=303)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('briefing.my_briefings'))
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe portal error: {e}")
        flash('Unable to access billing portal. Please try again.', 'error')
        return redirect(url_for('briefing.my_briefings'))


@billing_bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe webhook events."""
    s = get_stripe()
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    
    if not webhook_secret:
        current_app.logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({'error': 'Webhook not configured'}), 500
    
    try:
        event = s.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        current_app.logger.error("Invalid webhook payload")
        return jsonify({'error': 'Invalid payload'}), 400
    except s.error.SignatureVerificationError:
        current_app.logger.error("Invalid webhook signature")
        return jsonify({'error': 'Invalid signature'}), 400
    
    event_type = event['type']
    data = event['data']['object']
    
    current_app.logger.info(f"Received Stripe webhook: {event_type}")
    
    if event_type == 'customer.subscription.created':
        handle_subscription_created(data)
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data)
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data)
    elif event_type == 'customer.subscription.trial_will_end':
        handle_trial_ending(data)
    
    return jsonify({'status': 'success'}), 200


def handle_subscription_created(subscription_data):
    """Handle new subscription creation."""
    s = get_stripe()
    stripe_sub = s.Subscription.retrieve(subscription_data['id'])
    customer_id = subscription_data['customer']
    
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if user:
        sync_subscription_from_stripe(stripe_sub, user_id=user.id)
        current_app.logger.info(f"Created subscription for user {user.id}")


def handle_subscription_updated(subscription_data):
    """Handle subscription updates (plan changes, status changes)."""
    s = get_stripe()
    stripe_sub = s.Subscription.retrieve(subscription_data['id'])
    
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        sync_subscription_from_stripe(stripe_sub, user_id=sub.user_id, org_id=sub.org_id)
        current_app.logger.info(f"Updated subscription {sub.id}")


def handle_subscription_deleted(subscription_data):
    """Handle subscription cancellation."""
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        sub.status = 'canceled'
        sub.canceled_at = db.func.now()
        db.session.commit()
        current_app.logger.info(f"Canceled subscription {sub.id}")


def handle_payment_failed(invoice_data):
    """Handle failed payment."""
    subscription_id = invoice_data.get('subscription')
    if subscription_id:
        sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
        if sub:
            sub.status = 'past_due'
            db.session.commit()
            current_app.logger.info(f"Subscription {sub.id} marked past_due")


def handle_trial_ending(subscription_data):
    """Handle trial ending soon notification (3 days before)."""
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub and sub.user:
        current_app.logger.info(f"Trial ending soon for user {sub.user_id}")


@billing_bp.route('/status')
@login_required
def subscription_status():
    """Get current subscription status."""
    sub = get_active_subscription(current_user)
    
    if not sub:
        return jsonify({
            'has_subscription': False,
            'plan': None,
        })
    
    return jsonify({
        'has_subscription': True,
        'subscription': sub.to_dict(),
    })


@billing_bp.route('/plans')
def list_plans():
    """List available pricing plans."""
    plans = PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.display_order).all()
    return jsonify({
        'plans': [p.to_dict() for p in plans]
    })
