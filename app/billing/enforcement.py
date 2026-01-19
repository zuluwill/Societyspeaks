"""
Subscription tier enforcement helpers.
Use these in routes to check if users have access to features and are within limits.
"""
from functools import wraps
from flask import flash, redirect, url_for, jsonify, request
from flask_login import current_user
from app.billing.service import get_active_subscription, get_user_plan
from app.models import Briefing


def require_subscription(f):
    """Decorator to require an active subscription to access a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this feature.', 'error')
            return redirect(url_for('auth.login'))
        
        sub = get_active_subscription(current_user)
        if not sub:
            flash('You need an active subscription to access this feature. Start your free trial today!', 'info')
            return redirect(url_for('briefing.landing'))
        
        return f(*args, **kwargs)
    return decorated_function


def require_feature(feature_name):
    """Decorator factory to require a specific feature to be enabled on the user's plan."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this feature.', 'error')
                return redirect(url_for('auth.login'))
            
            sub = get_active_subscription(current_user)
            if not sub:
                flash('You need an active subscription to access this feature.', 'info')
                return redirect(url_for('briefing.landing'))
            
            if not sub.can_use_feature(feature_name):
                feature_display = feature_name.replace('_', ' ').title()
                flash(f'{feature_display} is not available on your current plan. Please upgrade to access this feature.', 'info')
                return redirect(url_for('briefing.landing'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_subscription_context(user):
    """Get subscription context for templates."""
    sub = get_active_subscription(user) if user.is_authenticated else None
    plan = sub.plan if sub else None
    
    brief_count = Briefing.query.filter_by(user_id=user.id).count() if user.is_authenticated else 0
    
    return {
        'has_subscription': sub is not None,
        'subscription': sub,
        'plan': plan,
        'plan_code': plan.code if plan else None,
        'plan_name': plan.name if plan else 'Free',
        'is_trial': sub.is_trial if sub else False,
        'days_remaining': sub.days_remaining if sub else None,
        'brief_count': brief_count,
        'can_create_brief': check_can_create_brief(user),
        'limits': {
            'max_briefs': plan.max_briefs if plan else 0,
            'max_sources': plan.max_sources if plan else 0,
            'max_recipients': plan.max_recipients if plan else 0,
            'max_editors': plan.max_editors if plan else 0,
        } if plan else None,
        'features': {
            'document_uploads': plan.allow_document_uploads if plan else False,
            'custom_branding': plan.allow_custom_branding if plan else False,
            'approval_workflow': plan.allow_approval_workflow if plan else False,
            'slack_integration': plan.allow_slack_integration if plan else False,
            'api_access': plan.allow_api_access if plan else False,
            'priority_processing': plan.priority_processing if plan else False,
        } if plan else None,
    }


def check_can_create_brief(user):
    """Check if user can create a new briefing based on their plan limits."""
    if not user.is_authenticated:
        return False
    
    sub = get_active_subscription(user)
    if not sub:
        return False
    
    plan = sub.plan
    if plan.max_briefs == -1:  # Unlimited
        return True
    
    current_count = Briefing.query.filter_by(user_id=user.id).count()
    return current_count < plan.max_briefs


def check_source_limit(user, additional_sources=0):
    """Check if user can add more sources based on their plan limits."""
    if not user.is_authenticated:
        return False
    
    sub = get_active_subscription(user)
    if not sub:
        return False
    
    plan = sub.plan
    if plan.max_sources == -1:  # Unlimited
        return True
    
    from app.models import BriefingSource
    current_count = BriefingSource.query.join(Briefing).filter(Briefing.user_id == user.id).count()
    return (current_count + additional_sources) <= plan.max_sources


def check_recipient_limit(user, briefing_id, additional_recipients=0):
    """Check if user can add more recipients based on their plan limits."""
    if not user.is_authenticated:
        return False
    
    sub = get_active_subscription(user)
    if not sub:
        return False
    
    plan = sub.plan
    if plan.max_recipients == -1:  # Unlimited
        return True
    
    from app.models import BriefRecipient
    current_count = BriefRecipient.query.filter_by(briefing_id=briefing_id).count()
    return (current_count + additional_recipients) <= plan.max_recipients


def get_usage_stats(user):
    """Get current usage statistics for a user."""
    if not user.is_authenticated:
        return None
    
    from app.models import BriefingSource, BriefRecipient
    
    brief_count = Briefing.query.filter_by(user_id=user.id).count()
    source_count = BriefingSource.query.join(Briefing).filter(Briefing.user_id == user.id).count()
    
    sub = get_active_subscription(user)
    plan = sub.plan if sub else None
    
    return {
        'briefs': {
            'used': brief_count,
            'limit': plan.max_briefs if plan else 0,
            'unlimited': plan.max_briefs == -1 if plan else False,
        },
        'sources': {
            'used': source_count,
            'limit': plan.max_sources if plan else 0,
            'unlimited': plan.max_sources == -1 if plan else False,
        },
    }


def enforce_brief_limit(user):
    """Check brief limit and return error message if exceeded."""
    if not check_can_create_brief(user):
        sub = get_active_subscription(user)
        if not sub:
            return "You need an active subscription to create briefings."
        plan = sub.plan
        return f"You've reached your limit of {plan.max_briefs} briefing(s) on the {plan.name} plan. Please upgrade to create more."
    return None
