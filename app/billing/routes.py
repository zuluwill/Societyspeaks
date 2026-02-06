import stripe
from flask import request, redirect, url_for, jsonify, flash, current_app, session
from flask_login import login_required, current_user
from app.billing import billing_bp
from app.billing.service import (
    create_checkout_session,
    create_portal_session,
    sync_subscription_from_stripe,
    sync_subscription_with_org,
    get_active_subscription,
    get_stripe,
    resolve_plan_from_stripe_subscription,
)
from app.models import User, PricingPlan, Subscription, Partner
from app import db, csrf


@billing_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """Start a Stripe Checkout session for subscription."""
    current_app.logger.info(f"Checkout initiated by user {current_user.id} ({current_user.email})")
    
    plan_code = request.form.get('plan', 'starter')
    billing_interval = request.form.get('interval', 'month')
    
    current_app.logger.info(f"Plan: {plan_code}, Interval: {billing_interval}")

    target_plan = PricingPlan.query.filter_by(code=plan_code).first()
    if not target_plan:
        flash('Invalid plan selected.', 'error')
        return redirect(url_for('briefing.landing'))

    existing_sub = get_active_subscription(current_user)
    manual_sub_to_supersede = None  # Track manual sub to supersede AFTER successful checkout creation

    if existing_sub:
        # Check if existing subscription is manual (admin-granted)
        if existing_sub.stripe_subscription_id is None:
            # Manual subscription - DON'T supersede yet, wait until checkout session is created
            current_app.logger.info(
                f"User {current_user.id} upgrading from manual subscription (plan: {existing_sub.plan.name}) "
                f"to Stripe subscription (plan: {target_plan.name})"
            )
            manual_sub_to_supersede = existing_sub  # Mark for later superseding
            flash(
                f'Your free {existing_sub.plan.name} access will be replaced once you complete payment.',
                'info'
            )
            # Continue to checkout - will supersede manual sub only after checkout session created
        else:
            # Stripe subscription exists
            is_upgrading_to_org = target_plan.is_organisation and not existing_sub.plan.is_organisation
            if is_upgrading_to_org:
                # Upgrading from individual to team/enterprise plan
                # Cancel existing subscription at period end and create new one
                try:
                    s = get_stripe()
                    # Cancel existing subscription at period end (user keeps access until then)
                    s.Subscription.modify(
                        existing_sub.stripe_subscription_id,
                        cancel_at_period_end=True
                    )
                    existing_sub.cancel_at_period_end = True
                    db.session.commit()
                    current_app.logger.info(
                        f"Marked subscription {existing_sub.id} for cancellation due to org plan upgrade"
                    )
                except stripe.error.StripeError as e:
                    current_app.logger.error(f"Failed to cancel existing subscription for upgrade: {e}")
                    flash('Unable to process upgrade. Please contact support.', 'error')
                    return redirect(url_for('briefing.list_briefings'))
            else:
                # Same tier or downgrade - use customer portal
                flash('You already have an active subscription. Use "Manage Billing" to change your plan.', 'info')
                return redirect(url_for('billing.customer_portal'))

    try:
        checkout_session = create_checkout_session(
            user=current_user,
            plan_code=plan_code,
            billing_interval=billing_interval
        )
        
        # Only supersede manual subscription AFTER checkout session is successfully created
        # This ensures user keeps their free access if Stripe checkout creation fails
        if manual_sub_to_supersede:
            manual_sub_to_supersede.status = 'superseded'
            manual_sub_to_supersede.canceled_at = db.func.now()
            db.session.commit()
            current_app.logger.info(
                f"Manual subscription {manual_sub_to_supersede.id} marked superseded after checkout session created"
            )
        
        if not checkout_session.url:
            flash('Payment session error. Please try again.', 'error')
            return redirect(url_for('briefing.landing'))
        try:
            import posthog
            if posthog and getattr(posthog, 'project_api_key', None):
                posthog.capture(
                    distinct_id=str(current_user.id),
                    event='checkout_started',
                    properties={
                        'plan_code': plan_code,
                        'billing_interval': billing_interval,
                        'plan_name': target_plan.name if target_plan else plan_code,
                    }
                )
                posthog.flush()  # Ensure event is sent before redirect
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")
        return redirect(checkout_session.url, code=303)
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
    sync_success = False
    is_org_plan = False

    if session_id:
        try:
            checkout_session = s.checkout.Session.retrieve(session_id)

            # Security: Verify the checkout session belongs to this user
            if checkout_session.customer and current_user.stripe_customer_id:
                if checkout_session.customer != current_user.stripe_customer_id:
                    current_app.logger.warning(
                        f"Checkout session customer mismatch: session={checkout_session.customer}, "
                        f"user={current_user.id} has customer_id={current_user.stripe_customer_id}"
                    )
                    flash('Invalid checkout session.', 'error')
                    return redirect(url_for('briefing.landing'))

            if checkout_session.subscription:
                sub_id = checkout_session.subscription if isinstance(checkout_session.subscription, str) else checkout_session.subscription.id
                stripe_sub = s.Subscription.retrieve(sub_id)
                sub = sync_subscription_with_org(stripe_sub, current_user)
                sync_success = True
                if sub and sub.plan and sub.plan.is_organisation:
                    is_org_plan = True
                # Track paid briefing subscription with PostHog (only when we just synced from this checkout)
                if sub and sub.plan:
                    try:
                        import posthog
                        if posthog and getattr(posthog, 'project_api_key', None):
                            meta = getattr(checkout_session, 'metadata', None) or {}
                            interval = meta.get('billing_interval', 'month')
                            plan = sub.plan
                            price_pence = plan.price_yearly if interval == 'year' else plan.price_monthly
                            price_display = (price_pence / 100.0) if price_pence else None
                            posthog.capture(
                                distinct_id=str(current_user.id),
                                event='paid_briefing_subscribed',
                                properties={
                                    'subscription_tier': 'paid',
                                    'plan_name': plan.name,
                                    'plan_code': plan.code,
                                    'billing_interval': interval,
                                    'price_pence': price_pence,
                                    'price': price_display,
                                }
                            )
                            posthog.flush()  # Critical: ensure subscription event is sent
                            current_app.logger.info(f"PostHog: paid_briefing_subscribed for user {current_user.id}")
                    except Exception as e:
                        current_app.logger.warning(f"PostHog tracking error: {e}")
        except stripe.error.StripeError as e:
            current_app.logger.error(f"Stripe error retrieving checkout session: {e}")
        except ValueError as e:
            current_app.logger.error(f"Plan sync error during checkout success: {e}")
        except Exception as e:
            current_app.logger.error(f"Unexpected error during checkout success for user {current_user.id}: {e}", exc_info=True)
    
    sub = get_active_subscription(current_user)
    if sub or sync_success:
        if is_org_plan:
            flash('Welcome! Your team subscription is now active. You can invite team members from your organization settings.', 'success')
            return redirect(url_for('briefing.organization_settings'))
        else:
            flash('Welcome! Your subscription is now active. You can start creating your first brief!', 'success')
            return redirect(url_for('briefing.list_briefings'))
    else:
        # If we reach here, subscription wasn't synced properly
        # Store a flag to show a helpful onboarding message
        session['pending_subscription_activation'] = True
        flash('Welcome! Your subscription is being activated. This usually takes just a few seconds - you\'ll be able to create briefs momentarily.', 'info')
        return redirect(url_for('briefing.list_briefings'))


@billing_bp.route('/portal')
@login_required
def customer_portal():
    """Redirect to Stripe Customer Portal for billing management."""
    try:
        portal_session = create_portal_session(current_user)
        return redirect(portal_session.url, code=303)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('briefing.list_briefings'))
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe portal error: {e}")
        flash('Unable to access billing portal. Please try again.', 'error')
        return redirect(url_for('briefing.list_briefings'))


@billing_bp.route('/webhook', methods=['POST'])
@csrf.exempt
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
    
    try:
        # Subscription events (require action)
        if event_type == 'customer.subscription.created':
            if _is_partner_subscription(data):
                _handle_partner_subscription(data)
            else:
                handle_subscription_created(data)
        elif event_type == 'customer.subscription.updated':
            if _is_partner_subscription(data):
                _handle_partner_subscription(data)
            else:
                handle_subscription_updated(data)
        elif event_type == 'customer.subscription.deleted':
            if _is_partner_subscription(data):
                _handle_partner_subscription(data)
            else:
                handle_subscription_deleted(data)
        elif event_type == 'customer.subscription.trial_will_end':
            if not _is_partner_subscription(data):
                handle_trial_ending(data)
        elif event_type == 'customer.subscription.paused':
            if _is_partner_subscription(data):
                _handle_partner_subscription(data)
            else:
                handle_subscription_paused(data)
        elif event_type == 'customer.subscription.resumed':
            if _is_partner_subscription(data):
                _handle_partner_subscription(data)
            else:
                handle_subscription_resumed(data)
        elif event_type == 'customer.subscription.pending_update_applied':
            current_app.logger.info(f"Subscription pending update applied: {data.get('id')}")
        elif event_type == 'customer.subscription.pending_update_expired':
            current_app.logger.info(f"Subscription pending update expired: {data.get('id')}")
        
        # Payment events
        elif event_type == 'invoice.payment_failed':
            handle_payment_failed(data)
        
        # Checkout session events
        elif event_type == 'checkout.session.completed':
            current_app.logger.info(f"Checkout session completed: {data.get('id')}")
        elif event_type == 'checkout.session.expired':
            current_app.logger.info(f"Checkout session expired: {data.get('id')}")
        elif event_type == 'checkout.session.async_payment_succeeded':
            current_app.logger.info(f"Checkout async payment succeeded: {data.get('id')}")
        elif event_type == 'checkout.session.async_payment_failed':
            current_app.logger.info(f"Checkout async payment failed: {data.get('id')}")
        
        # Customer events
        elif event_type == 'customer.created':
            current_app.logger.info(f"Customer created: {data.get('id')} - {data.get('email')}")
        elif event_type == 'customer.updated':
            current_app.logger.info(f"Customer updated: {data.get('id')}")
        elif event_type == 'customer.deleted':
            current_app.logger.info(f"Customer deleted: {data.get('id')}")
        
        # Discount events
        elif event_type == 'customer.discount.created':
            current_app.logger.info(f"Customer discount created: {data.get('id')}")
        elif event_type == 'customer.discount.updated':
            current_app.logger.info(f"Customer discount updated: {data.get('id')}")
        elif event_type == 'customer.discount.deleted':
            current_app.logger.info(f"Customer discount deleted: {data.get('id')}")
        
        else:
            current_app.logger.info(f"Unhandled webhook event type: {event_type}")
    except Exception as e:
        current_app.logger.error(f"Error processing webhook {event_type}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
    return jsonify({'status': 'success'}), 200


def handle_subscription_created(subscription_data):
    """Handle new subscription creation."""
    s = get_stripe()
    stripe_sub = s.Subscription.retrieve(subscription_data['id'])
    customer_id = subscription_data['customer']

    existing_sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if existing_sub:
        try:
            sync_subscription_from_stripe(stripe_sub, user_id=existing_sub.user_id, org_id=existing_sub.org_id)
            current_app.logger.info(f"Synced existing subscription {existing_sub.id}")
        except ValueError as e:
            current_app.logger.error(f"Failed to sync subscription {subscription_data['id']}: {e}")
        return

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if user:
        try:
            sync_subscription_with_org(stripe_sub, user)
            current_app.logger.info(f"Created subscription for user {user.id}")
        except ValueError as e:
            current_app.logger.error(f"Failed to create subscription for user {user.id}: {e}")


def handle_subscription_updated(subscription_data):
    """Handle subscription updates (plan changes, status changes)."""
    s = get_stripe()
    stripe_sub = s.Subscription.retrieve(subscription_data['id'])

    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        try:
            sync_subscription_from_stripe(stripe_sub, user_id=sub.user_id, org_id=sub.org_id)
            current_app.logger.info(f"Updated subscription {sub.id}")
        except ValueError as e:
            current_app.logger.error(f"Failed to update subscription {sub.id}: {e}")


def _is_partner_subscription(subscription_data):
    try:
        metadata = subscription_data.get('metadata', {}) if isinstance(subscription_data, dict) else (subscription_data.metadata or {})
    except Exception:
        metadata = {}
    if metadata.get('purpose') == 'partner_subscription':
        return True
    if metadata.get('partner_id'):
        return True
    return False


def _handle_partner_subscription(subscription_data):
    s = get_stripe()
    stripe_sub = s.Subscription.retrieve(subscription_data['id'])
    metadata = stripe_sub.get('metadata', {}) if isinstance(stripe_sub, dict) else (stripe_sub.metadata or {})
    partner_id = metadata.get('partner_id')
    partner = None
    if partner_id:
        try:
            partner = Partner.query.get(int(partner_id))
        except (ValueError, TypeError):
            current_app.logger.warning(f"Non-numeric partner_id in subscription metadata: {partner_id}")
    if not partner:
        customer_id = subscription_data.get('customer')
        partner = Partner.query.filter_by(stripe_customer_id=customer_id).first()
    if not partner:
        current_app.logger.warning("Partner subscription received but partner not found")
        return

    customer_id = stripe_sub.get('customer') if isinstance(stripe_sub, dict) else getattr(stripe_sub, 'customer', None)
    if not partner.stripe_customer_id and customer_id:
        partner.stripe_customer_id = customer_id

    status = stripe_sub.get('status') if isinstance(stripe_sub, dict) else stripe_sub.status
    partner.stripe_subscription_id = stripe_sub.get('id') if isinstance(stripe_sub, dict) else stripe_sub.id
    # past_due = Stripe is still retrying payment; keep access active as a grace period.
    # Only revoke on terminal states (canceled, unpaid, incomplete_expired).
    active_statuses = ('active', 'trialing', 'past_due')
    partner.billing_status = 'active' if status in active_statuses else 'inactive'

    if status == 'past_due':
        current_app.logger.warning(f"Partner {partner.slug} subscription is past_due — grace period active")

    # Persist the tier from checkout metadata (starter / professional)
    tier_from_meta = metadata.get('partner_tier')
    if tier_from_meta in ('starter', 'professional', 'enterprise'):
        partner.tier = tier_from_meta
    elif partner.billing_status == 'active' and partner.tier == 'free':
        # Legacy fallback: if somehow no tier in metadata, default to starter
        partner.tier = 'starter'

    # When subscription reaches a terminal state, revert to free tier
    if status in ('canceled', 'unpaid', 'incomplete_expired'):
        partner.tier = 'free'

    db.session.commit()

    if partner.billing_status == 'active':
        current_app.logger.info(f"Partner subscription active for {partner.slug} (tier={partner.tier})")


def handle_subscription_deleted(subscription_data):
    """Handle subscription cancellation."""
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        user_id = sub.user_id
        plan_name = sub.plan.name if sub.plan else None
        plan_code = sub.plan.code if sub.plan else None
        sub.status = 'canceled'
        sub.canceled_at = db.func.now()
        db.session.commit()
        current_app.logger.info(f"Canceled subscription {sub.id}")
        try:
            import posthog
            if posthog and getattr(posthog, 'project_api_key', None) and user_id:
                posthog.capture(
                    distinct_id=str(user_id),
                    event='paid_briefing_canceled',
                    properties={
                        'subscription_id': sub.id,
                        'plan_name': plan_name,
                        'plan_code': plan_code,
                    }
                )
                posthog.flush()  # Critical: ensure churn event is sent
                current_app.logger.info(f"PostHog: paid_briefing_canceled for user {user_id}")
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")


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


def handle_subscription_paused(subscription_data):
    """Handle subscription paused."""
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        sub.status = 'paused'
        db.session.commit()
        current_app.logger.info(f"Subscription {sub.id} paused")


def handle_subscription_resumed(subscription_data):
    """Handle subscription resumed."""
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    if sub:
        sub.status = 'active'
        db.session.commit()
        current_app.logger.info(f"Subscription {sub.id} resumed")


@billing_bp.route('/pending-checkout')
@login_required
def pending_checkout():
    """Handle pending checkout after registration/login."""
    plan_code = request.args.get('plan', 'starter')
    billing_interval = request.args.get('interval', 'month')
    
    try:
        checkout_session = create_checkout_session(
            user=current_user,
            plan_code=plan_code,
            billing_interval=billing_interval
        )
        if not checkout_session.url:
            flash('Payment session error. Please try again.', 'error')
            return redirect(url_for('briefing.landing'))
        try:
            import posthog
            target_plan = PricingPlan.query.filter_by(code=plan_code).first()
            if posthog and getattr(posthog, 'project_api_key', None):
                posthog.capture(
                    distinct_id=str(current_user.id),
                    event='checkout_started',
                    properties={
                        'plan_code': plan_code,
                        'billing_interval': billing_interval,
                        'plan_name': target_plan.name if target_plan else plan_code,
                        'source': 'pending_checkout',
                    }
                )
                posthog.flush()  # Ensure event is sent before redirect
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")
        return redirect(checkout_session.url, code=303)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('briefing.landing'))
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error in pending checkout: {e}")
        flash('Payment system error. Please try again.', 'error')
        return redirect(url_for('briefing.landing'))


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
