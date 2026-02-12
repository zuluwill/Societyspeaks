import stripe
from datetime import datetime, timedelta
from flask import current_app
from app import db
from app.models import User, CompanyProfile, PricingPlan, Subscription, OrganizationMember, generate_slug, Partner


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


def resolve_plan_from_stripe_subscription(stripe_subscription):
    """Resolve pricing plan from Stripe subscription metadata or price ID.
    
    Compatible with both Stripe API objects and webhook event data (dict format).
    """
    metadata = stripe_subscription.get('metadata', {}) if isinstance(stripe_subscription, dict) else (stripe_subscription.metadata or {})
    plan_code = metadata.get('plan_code')
    plan = PricingPlan.query.filter_by(code=plan_code).first() if plan_code else None
    
    if not plan:
        items_data = stripe_subscription.get('items', {}).get('data', []) if isinstance(stripe_subscription, dict) else (stripe_subscription.items.data if stripe_subscription.items else [])
        
        if items_data:
            first_item = items_data[0]
            if isinstance(first_item, dict):
                price_id = first_item.get('price', {}).get('id')
            else:
                price_id = first_item.price.id if first_item.price else None
            
            if price_id:
                plan = PricingPlan.query.filter(
                    (PricingPlan.stripe_price_monthly_id == price_id) | 
                    (PricingPlan.stripe_price_yearly_id == price_id)
                ).first()
                
                if not plan:
                    sub_id = stripe_subscription.get('id') if isinstance(stripe_subscription, dict) else stripe_subscription.id
                    current_app.logger.error(
                        f"CRITICAL: Unknown Stripe price ID {price_id} for subscription {sub_id}. "
                        f"This may indicate a missing plan configuration. Check that all Stripe price IDs are in the database."
                    )
                    raise ValueError(
                        f"Unknown Stripe price ID: {price_id}. "
                        f"Please ensure all Stripe price IDs are configured in the database."
                    )

    if not plan:
        sub_id = stripe_subscription.get('id') if isinstance(stripe_subscription, dict) else stripe_subscription.id
        current_app.logger.error(f"Could not resolve plan for subscription {sub_id} - no metadata or price data")
        raise ValueError(f"Could not resolve plan for subscription {sub_id}")

    return plan


def get_or_create_partner_customer(partner):
    s = get_stripe()
    if partner.stripe_customer_id:
        try:
            customer = s.Customer.retrieve(partner.stripe_customer_id)
            if not customer.get('deleted'):
                return customer
        except s.error.InvalidRequestError:
            pass

    customer = s.Customer.create(
        email=partner.contact_email,
        name=partner.name,
        metadata={'partner_id': str(partner.id), 'partner_slug': partner.slug}
    )
    partner.stripe_customer_id = customer.id
    db.session.commit()
    return customer


def create_partner_checkout_session(partner, tier=None, success_url=None, cancel_url=None):
    """Create a Stripe Checkout session for a partner subscription.

    Args:
        partner: Partner model instance.
        tier: 'starter' or 'professional'. Enterprise is handled via manual invoicing.
        success_url / cancel_url: optional overrides.
    """
    s = get_stripe()

    # Resolve the Stripe Price ID for the requested tier
    tier = tier or 'starter'
    if tier not in ('starter', 'professional'):
        raise ValueError(f"Unsupported self-serve tier: {tier}")

    prices = current_app.config.get('PARTNER_STRIPE_PRICES') or {}
    price_id = prices.get(tier)

    # Fallback to legacy single-price config
    if not price_id:
        price_id = current_app.config.get('PARTNER_STRIPE_PRICE_ID')
    if not price_id:
        raise ValueError(f"No Stripe Price ID configured for tier '{tier}'")

    customer = get_or_create_partner_customer(partner)
    base_url = current_app.config.get('APP_BASE_URL', 'https://societyspeaks.io')

    session = s.checkout.Session.create(
        customer=customer.id,
        payment_method_types=['card'],
        mode='subscription',
        line_items=[{
            'price': price_id,
            'quantity': 1,
        }],
        success_url=success_url or f"{base_url}/for-publishers/portal/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=cancel_url or f"{base_url}/for-publishers/portal/dashboard",
        metadata={
            'partner_id': str(partner.id),
            'partner_slug': partner.slug,
            'partner_tier': tier,
            'purpose': 'partner_subscription'
        },
        subscription_data={
            'metadata': {
                'partner_id': str(partner.id),
                'partner_slug': partner.slug,
                'partner_tier': tier,
                'purpose': 'partner_subscription'
            }
        }
    )
    return session


def create_partner_portal_session(partner, return_url=None):
    s = get_stripe()
    if not partner.stripe_customer_id:
        raise ValueError("Partner has no Stripe customer ID")
    base_url = current_app.config.get('APP_BASE_URL', 'https://societyspeaks.io')
    session = s.billing_portal.Session.create(
        customer=partner.stripe_customer_id,
        return_url=return_url or f"{base_url}/for-publishers/portal/dashboard"
    )
    return session


def reconcile_partner_subscriptions():
    """
    Reconcile partner billing status with Stripe.
    """
    import logging
    logger = logging.getLogger(__name__)

    s = get_stripe()
    if not s:
        return 0

    updated = 0
    partners = Partner.query.filter(Partner.stripe_subscription_id.isnot(None)).all()
    for partner in partners:
        try:
            subscription = s.Subscription.retrieve(partner.stripe_subscription_id)
        except Exception as e:
            logger.warning(f"Partner reconciliation: failed to retrieve subscription {partner.stripe_subscription_id} for {partner.slug}: {e}")
            continue
        status = subscription.get('status') if isinstance(subscription, dict) else getattr(subscription, 'status', '')
        # past_due = grace period, keep active; only revoke on terminal states
        active_statuses = ('active', 'trialing', 'past_due')
        new_status = 'active' if status in active_statuses else 'inactive'
        if partner.billing_status != new_status:
            logger.info(f"Partner reconciliation: {partner.slug} billing status {partner.billing_status} -> {new_status}")
            partner.billing_status = new_status
            updated += 1

        # Sync tier from subscription metadata
        metadata = subscription.get('metadata', {}) if isinstance(subscription, dict) else (subscription.metadata or {})
        tier_from_meta = metadata.get('partner_tier')
        if tier_from_meta in ('starter', 'professional', 'enterprise') and partner.tier != tier_from_meta:
            logger.info(f"Partner reconciliation: {partner.slug} tier {partner.tier} -> {tier_from_meta}")
            partner.tier = tier_from_meta
            updated += 1

        # Revert to free on terminal states
        if status in ('canceled', 'unpaid', 'incomplete_expired') and partner.tier != 'free':
            logger.info(f"Partner reconciliation: {partner.slug} subscription {status}, reverting tier to free")
            partner.tier = 'free'
            updated += 1
        if status in ('canceled', 'unpaid', 'incomplete_expired') and partner.stripe_subscription_id is not None:
            logger.info(f"Partner reconciliation: clearing terminal subscription id for {partner.slug}")
            partner.stripe_subscription_id = None
            updated += 1
    if updated:
        db.session.commit()
    return updated


def sync_subscription_from_stripe(stripe_subscription, user_id=None, org_id=None):
    """Create or update local subscription record from Stripe subscription data.
    
    Preserves existing org_id linkage if already set (important for webhook updates).
    
    Compatible with Stripe API versions where current_period fields may be:
    - At the subscription level (older API versions)
    - Inside items.data[0] (API version 2025-12-15.clover and later)
    
    Also compatible with both Stripe API objects and webhook event data (dict format).
    """
    sub_id = stripe_subscription.get('id') if isinstance(stripe_subscription, dict) else stripe_subscription.id
    customer_id = stripe_subscription.get('customer') if isinstance(stripe_subscription, dict) else stripe_subscription.customer
    
    sub = Subscription.query.filter_by(stripe_subscription_id=sub_id).first()
    
    plan = resolve_plan_from_stripe_subscription(stripe_subscription)
    
    if not sub:
        sub = Subscription(
            stripe_subscription_id=sub_id,
            stripe_customer_id=customer_id,
            user_id=user_id,
            org_id=org_id,
            plan_id=plan.id if plan else None,
        )
        db.session.add(sub)
    else:
        if sub.org_id:
            org_id = sub.org_id
            user_id = None
        elif sub.user_id and not user_id:
            user_id = sub.user_id
    
    sub.status = stripe_subscription.get('status') if isinstance(stripe_subscription, dict) else stripe_subscription.status
    
    if isinstance(stripe_subscription, dict):
        items_data = stripe_subscription.get('items', {}).get('data', [])
    else:
        items_data = stripe_subscription.items.data if stripe_subscription.items else []
    
    first_item = items_data[0] if items_data else {}
    is_dict = isinstance(stripe_subscription, dict)
    is_first_item_dict = isinstance(first_item, dict)
    
    if is_dict:
        period_start = stripe_subscription.get('current_period_start')
        period_end = stripe_subscription.get('current_period_end')
    else:
        period_start = getattr(stripe_subscription, 'current_period_start', None)
        period_end = getattr(stripe_subscription, 'current_period_end', None)
    
    if not period_start and first_item:
        period_start = first_item.get('current_period_start') if is_first_item_dict else getattr(first_item, 'current_period_start', None)
    if not period_end and first_item:
        period_end = first_item.get('current_period_end') if is_first_item_dict else getattr(first_item, 'current_period_end', None)
    
    if not period_start:
        period_start = stripe_subscription.get('start_date') if is_dict else getattr(stripe_subscription, 'start_date', None)
        if not period_start:
            period_start = stripe_subscription.get('trial_start') if is_dict else getattr(stripe_subscription, 'trial_start', None)
    if not period_end:
        period_end = stripe_subscription.get('trial_end') if is_dict else getattr(stripe_subscription, 'trial_end', None)
    
    if period_start:
        sub.current_period_start = datetime.fromtimestamp(period_start)
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end)
    
    sub.cancel_at_period_end = stripe_subscription.get('cancel_at_period_end', False) if is_dict else getattr(stripe_subscription, 'cancel_at_period_end', False)
    
    if first_item:
        if is_first_item_dict:
            recurring = first_item.get('price', {}).get('recurring', {})
            sub.billing_interval = recurring.get('interval', 'month')
        else:
            sub.billing_interval = first_item.price.recurring.interval if first_item.price and first_item.price.recurring else 'month'
    else:
        sub.billing_interval = 'month'
    
    trial_end = stripe_subscription.get('trial_end') if is_dict else getattr(stripe_subscription, 'trial_end', None)
    if trial_end:
        sub.trial_end = datetime.fromtimestamp(trial_end)
    
    canceled_at = stripe_subscription.get('canceled_at') if is_dict else getattr(stripe_subscription, 'canceled_at', None)
    if canceled_at:
        sub.canceled_at = datetime.fromtimestamp(canceled_at)
    
    if plan:
        sub.plan_id = plan.id
    
    db.session.commit()
    return sub


def get_active_subscription(user):
    """Get the user's active subscription, if any.
    
    Priority order when multiple active subscriptions exist:
    1. Stripe subscriptions (user is paying) - always take precedence
    2. Manual subscriptions (admin-granted free access) - fallback
    
    This ensures paying customers always get their paid plan limits.
    
    Checks in order:
    1. User's direct subscription (Stripe first, then manual)
    2. Subscription for organization user owns (Stripe first, then manual)
    3. Subscription for any organization user is a member of (Stripe first, then manual)
    """
    # Check user's direct subscription - Stripe takes priority
    stripe_sub = Subscription.query.filter(
        Subscription.user_id == user.id,
        Subscription.status.in_(['trialing', 'active']),
        Subscription.stripe_subscription_id.isnot(None)  # Stripe only
    ).order_by(Subscription.created_at.desc()).first()

    if stripe_sub:
        return stripe_sub
    
    # Fall back to manual subscription if no Stripe
    manual_sub = Subscription.query.filter(
        Subscription.user_id == user.id,
        Subscription.status.in_(['trialing', 'active']),
        Subscription.stripe_subscription_id.is_(None)  # Manual only
    ).order_by(Subscription.created_at.desc()).first()
    
    if manual_sub:
        return manual_sub

    # Check organization user owns (via company_profile) - Stripe priority
    if user.company_profile:
        stripe_sub = Subscription.query.filter(
            Subscription.org_id == user.company_profile.id,
            Subscription.status.in_(['trialing', 'active']),
            Subscription.stripe_subscription_id.isnot(None)
        ).order_by(Subscription.created_at.desc()).first()
        if stripe_sub:
            return stripe_sub
        
        manual_sub = Subscription.query.filter(
            Subscription.org_id == user.company_profile.id,
            Subscription.status.in_(['trialing', 'active']),
            Subscription.stripe_subscription_id.is_(None)
        ).order_by(Subscription.created_at.desc()).first()
        if manual_sub:
            return manual_sub

    # Check organizations user is a member of - Stripe priority
    memberships = OrganizationMember.query.filter(
        OrganizationMember.user_id == user.id,
        OrganizationMember.status == 'active'
    ).all()

    for membership in memberships:
        stripe_sub = Subscription.query.filter(
            Subscription.org_id == membership.org_id,
            Subscription.status.in_(['trialing', 'active']),
            Subscription.stripe_subscription_id.isnot(None)
        ).order_by(Subscription.created_at.desc()).first()
        if stripe_sub:
            return stripe_sub
        
        manual_sub = Subscription.query.filter(
            Subscription.org_id == membership.org_id,
            Subscription.status.in_(['trialing', 'active']),
            Subscription.stripe_subscription_id.is_(None)
        ).order_by(Subscription.created_at.desc()).first()
        if manual_sub:
            return manual_sub

    return None


def get_user_organization(user):
    """Get the organization the user belongs to (either as owner or member)."""
    # Check if user owns an org
    if user.company_profile:
        return user.company_profile

    # Check if user is a member of any org
    membership = OrganizationMember.query.filter(
        OrganizationMember.user_id == user.id,
        OrganizationMember.status == 'active'
    ).first()

    if membership:
        return membership.org

    return None


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


def get_or_create_organization(user, plan):
    """Create an organization for Team/Enterprise plans if user doesn't have one.

    Also creates an OrganizationMember record for the owner.
    """
    if not plan.is_organisation:
        return None

    if user.company_profile:
        # Ensure owner membership exists
        _ensure_owner_membership(user.company_profile, user)
        return user.company_profile

    existing_org = CompanyProfile.query.filter_by(user_id=user.id).first()
    if existing_org:
        _ensure_owner_membership(existing_org, user)
        return existing_org

    org_name = f"{user.username}'s Organization"
    slug = generate_slug(org_name)

    existing_slug = CompanyProfile.query.filter_by(slug=slug).first()
    if existing_slug:
        slug = f"{slug}-{user.id}"

    org = CompanyProfile(
        user_id=user.id,
        company_name=org_name,
        slug=slug,
        email=user.email,
    )
    db.session.add(org)
    db.session.flush()  # Get the org.id before creating membership

    # Create owner membership
    owner_membership = OrganizationMember(
        org_id=org.id,
        user_id=user.id,
        role='owner',
        status='active',
        joined_at=datetime.utcnow(),
    )
    db.session.add(owner_membership)
    db.session.commit()

    db.session.expire(user)

    current_app.logger.info(f"Created organization '{org_name}' (id={org.id}) for user {user.id}")
    return org


def _ensure_owner_membership(org, user):
    """Ensure the owner has an OrganizationMember record."""
    existing = OrganizationMember.query.filter_by(
        org_id=org.id,
        user_id=user.id
    ).first()

    if not existing:
        owner_membership = OrganizationMember(
            org_id=org.id,
            user_id=user.id,
            role='owner',
            status='active',
            joined_at=datetime.utcnow(),
        )
        db.session.add(owner_membership)
        db.session.commit()
        current_app.logger.info(f"Created owner membership for org {org.id}")


def sync_subscription_with_org(stripe_subscription, user):
    """Sync subscription and handle organization creation for team plans."""
    plan = resolve_plan_from_stripe_subscription(stripe_subscription)
    
    org_id = None
    user_id = user.id
    
    if plan and plan.is_organisation:
        org = get_or_create_organization(user, plan)
        if org:
            org_id = org.id
            user_id = None
    
    return sync_subscription_from_stripe(stripe_subscription, user_id=user_id, org_id=org_id)


# Team member management functions

def invite_team_member(org, email, role, invited_by):
    """Invite a user to join an organization.

    Args:
        org: CompanyProfile organization
        email: Email address to invite
        role: Role to assign ('admin', 'editor', 'viewer')
        invited_by: User sending the invitation

    Returns:
        OrganizationMember instance or raises ValueError
    """
    import secrets

    # Validate role
    if role not in ('admin', 'editor', 'viewer'):
        raise ValueError(f"Invalid role: {role}")

    # Check seat limits
    sub = Subscription.query.filter(
        Subscription.org_id == org.id,
        Subscription.status.in_(['trialing', 'active'])
    ).first()

    if not sub:
        raise ValueError("Organization does not have an active subscription")

    max_editors = sub.plan.max_editors
    if max_editors != -1:  # -1 means unlimited
        current_members = OrganizationMember.query.filter(
            OrganizationMember.org_id == org.id,
            OrganizationMember.status.in_(['pending', 'active'])
        ).count()
        if current_members >= max_editors:
            raise ValueError(f"Team has reached the maximum of {max_editors} members for the {sub.plan.name} plan")

    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()

    # Check for existing membership
    if existing_user:
        existing_membership = OrganizationMember.query.filter_by(
            org_id=org.id,
            user_id=existing_user.id
        ).first()
        if existing_membership:
            if existing_membership.status == 'removed':
                # Re-invite removed member
                existing_membership.status = 'pending'
                existing_membership.role = role
                existing_membership.invite_token = secrets.token_urlsafe(32)
                existing_membership.invite_email = email
                existing_membership.invited_by_id = invited_by.id
                existing_membership.invited_at = datetime.utcnow()
                existing_membership.joined_at = None
                db.session.commit()
                return existing_membership
            else:
                raise ValueError(f"User {email} is already a member of this organization")

    # Check for pending invite with same email
    existing_invite = OrganizationMember.query.filter_by(
        org_id=org.id,
        invite_email=email,
        status='pending'
    ).first()
    if existing_invite:
        raise ValueError(f"An invitation has already been sent to {email}")

    # Create the invitation
    membership = OrganizationMember(
        org_id=org.id,
        user_id=existing_user.id if existing_user else None,
        role=role,
        status='pending',
        invite_token=secrets.token_urlsafe(32),
        invite_email=email,
        invited_by_id=invited_by.id,
        invited_at=datetime.utcnow(),
    )
    db.session.add(membership)
    db.session.commit()

    current_app.logger.info(f"Created invitation for {email} to org {org.id} with role {role}")
    return membership


def accept_invitation(token, user):
    """Accept an organization invitation.

    Args:
        token: Invitation token
        user: User accepting the invitation

    Returns:
        OrganizationMember instance or raises ValueError
    """
    membership = OrganizationMember.query.filter_by(
        invite_token=token,
        status='pending'
    ).first()

    if not membership:
        raise ValueError("Invalid or expired invitation")

    # Verify email matches if specified
    if membership.invite_email and membership.invite_email.lower() != user.email.lower():
        raise ValueError("This invitation was sent to a different email address")

    # Check if user is already a member of this org
    existing = OrganizationMember.query.filter(
        OrganizationMember.org_id == membership.org_id,
        OrganizationMember.user_id == user.id,
        OrganizationMember.status == 'active'
    ).first()
    if existing:
        raise ValueError("You are already a member of this organization")

    membership.user_id = user.id
    membership.status = 'active'
    membership.joined_at = datetime.utcnow()
    membership.invite_token = None  # Clear token after use
    db.session.commit()

    current_app.logger.info(f"User {user.id} accepted invitation to org {membership.org_id}")
    return membership


def remove_team_member(org, member_id, removed_by):
    """Remove a member from an organization.

    Args:
        org: CompanyProfile organization
        member_id: OrganizationMember ID to remove
        removed_by: User performing the removal

    Returns:
        True on success or raises ValueError
    """
    membership = OrganizationMember.query.filter_by(
        id=member_id,
        org_id=org.id
    ).first()

    if not membership:
        raise ValueError("Member not found")

    if membership.role == 'owner':
        raise ValueError("Cannot remove the organization owner")

    # Check permissions - only owner and admin can remove
    remover_membership = OrganizationMember.query.filter_by(
        org_id=org.id,
        user_id=removed_by.id,
        status='active'
    ).first()

    if not remover_membership or not remover_membership.is_admin:
        # Also allow org owner (via user_id on CompanyProfile)
        if org.user_id != removed_by.id:
            raise ValueError("You don't have permission to remove team members")

    membership.status = 'removed'
    db.session.commit()

    current_app.logger.info(f"Member {member_id} removed from org {org.id} by user {removed_by.id}")
    return True


def update_member_role(org, member_id, new_role, updated_by):
    """Update a member's role in an organization.

    Args:
        org: CompanyProfile organization
        member_id: OrganizationMember ID to update
        new_role: New role ('admin', 'editor', 'viewer')
        updated_by: User performing the update

    Returns:
        OrganizationMember instance or raises ValueError
    """
    if new_role not in ('admin', 'editor', 'viewer'):
        raise ValueError(f"Invalid role: {new_role}")

    membership = OrganizationMember.query.filter_by(
        id=member_id,
        org_id=org.id
    ).first()

    if not membership:
        raise ValueError("Member not found")

    if membership.role == 'owner':
        raise ValueError("Cannot change the role of the organization owner")

    # Check permissions - only owner and admin can update roles
    updater_membership = OrganizationMember.query.filter_by(
        org_id=org.id,
        user_id=updated_by.id,
        status='active'
    ).first()

    is_admin = updater_membership and updater_membership.is_admin
    is_owner = org.user_id == updated_by.id

    if not is_admin and not is_owner:
        raise ValueError("You don't have permission to update member roles")

    membership.role = new_role
    db.session.commit()

    current_app.logger.info(f"Member {member_id} role updated to {new_role} in org {org.id}")
    return membership


def get_team_members(org):
    """Get all active and pending members of an organization."""
    return OrganizationMember.query.filter(
        OrganizationMember.org_id == org.id,
        OrganizationMember.status.in_(['active', 'pending'])
    ).order_by(
        OrganizationMember.role.desc(),  # owner first, then admin, etc.
        OrganizationMember.joined_at
    ).all()


def check_team_seat_limit(org):
    """Check if organization can add more team members.

    Returns:
        (can_add: bool, current: int, max: int)
    """
    sub = Subscription.query.filter(
        Subscription.org_id == org.id,
        Subscription.status.in_(['trialing', 'active'])
    ).first()

    if not sub:
        return False, 0, 0

    current = OrganizationMember.query.filter(
        OrganizationMember.org_id == org.id,
        OrganizationMember.status.in_(['pending', 'active'])
    ).count()

    max_editors = sub.plan.max_editors
    if max_editors == -1:
        return True, current, -1

    return current < max_editors, current, max_editors
