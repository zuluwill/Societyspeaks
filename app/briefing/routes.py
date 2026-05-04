"""
Briefing Routes

CRUD routes for multi-tenant briefing system.
"""

from functools import wraps
from flask import render_template, redirect, url_for, flash, request, jsonify, g, session, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app.lib.time import utcnow_naive
from app.briefing import briefing_bp
from app.briefing.validators import (
    validate_email, validate_briefing_name, validate_rss_url,
    validate_file_upload, validate_timezone, validate_cadence,
    validate_visibility, validate_mode, validate_send_hour, validate_send_minute
)
from app import db, limiter, csrf
from app.models import (
    Briefing, BriefRun, BriefRunItem, BriefTemplate, InputSource, IngestedItem,
    BriefingSource, BriefRecipient, SendingDomain, User, CompanyProfile, NewsSource,
    BriefEmailOpen, BriefLinkClick, OrganizationMember, Subscription
)
from app.models.email import EmailEvent
from app.billing.enforcement import (
    get_subscription_context, check_can_create_brief, enforce_brief_limit,
    check_source_limit, check_recipient_limit, require_feature
)
from app.billing.service import (
    get_active_subscription, get_team_members, invite_team_member,
    remove_team_member, update_member_role, check_team_seat_limit, accept_invitation,
    get_user_organization
)
from sqlalchemy.orm import joinedload, selectinload
import logging
try:
    import posthog
except ImportError:
    posthog = None
from app.lib.posthog_utils import safe_posthog_capture
from flask_babel import gettext as _

logger = logging.getLogger(__name__)


def _track_posthog(event, distinct_id, properties=None, flush=False):
    """Fire a PostHog event silently — never raises."""
    if not distinct_id:
        return
    safe_posthog_capture(
        posthog_client=posthog,
        distinct_id=str(distinct_id),
        event=event,
        properties=properties or {},
        flush=flush,
    )


# =============================================================================
# Constants
# =============================================================================

MAX_RECIPIENTS_PER_BRIEFING = 100  # Limit recipients to prevent spam abuse
MAX_SOURCES_PER_BRIEFING = 20      # Limit sources per briefing


# =============================================================================
# Helper Functions
# =============================================================================

def get_all_timezones():
    """
    Get all available timezones for dropdown (DRY helper).
    
    Returns:
        List of timezone strings, sorted alphabetically
    """
    try:
        import pytz
        return sorted(pytz.all_timezones)
    except (ImportError, AttributeError) as e:
        logger.error(f"Error loading timezones: {e}")
        # Fallback to common timezones if pytz fails
        return [
            'UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 
            'America/Los_Angeles', 'Europe/London', 'Europe/Paris', 'Asia/Tokyo'
        ]


def calculate_next_scheduled_time(briefing):
    """
    Calculate next scheduled time for a briefing (DRY helper).
    
    Args:
        briefing: Briefing instance
    
    Returns:
        datetime or None if calculation fails
    """
    if briefing.status != 'active':
        return None
    
    try:
        from app.briefing.timezone_utils import get_next_scheduled_time, get_weekly_scheduled_time
        preferred_minute = getattr(briefing, 'preferred_send_minute', 0)
        
        if briefing.cadence == 'daily':
            return get_next_scheduled_time(
                briefing.timezone,
                briefing.preferred_send_hour,
                preferred_minute=preferred_minute
            )
        elif briefing.cadence == 'weekly':
            return get_weekly_scheduled_time(
                briefing.timezone,
                briefing.preferred_send_hour,
                preferred_weekday=0,  # Monday
                preferred_minute=preferred_minute
            )
    except Exception as e:
        logger.warning(f"Error calculating next scheduled time for briefing {briefing.id}: {e}")
        return None


def get_available_sources_for_user(user, exclude_source_ids=None):
    """
    Get all available sources for a user (InputSource + NewsSource).
    Returns a list that can be used in templates for source selection.
    
    Args:
        user: Current user
        exclude_source_ids: Set of source IDs to exclude (already added)
    
    Returns:
        List of dicts with source info: {'id', 'name', 'type', 'is_system', 'source_obj'}
    """
    available = []
    exclude_source_ids = exclude_source_ids or set()
    
    # Get user's InputSources
    user_sources = InputSource.query.filter_by(
        owner_type='user',
        owner_id=user.id,
        enabled=True
    ).all()
    
    for source in user_sources:
        if source.id not in exclude_source_ids:
            available.append({
                'id': source.id,
                'name': source.name,
                'type': source.type,
                'is_system': False,
                'is_input_source': True,
                'source_obj': source
            })
    
    # Get org's InputSources if user has company profile
    if user.company_profile:
        org_sources = InputSource.query.filter_by(
            owner_type='org',
            owner_id=user.company_profile.id,
            enabled=True
        ).all()
        for source in org_sources:
            if source.id not in exclude_source_ids:
                available.append({
                    'id': source.id,
                    'name': source.name,
                    'type': source.type,
                    'is_system': False,
                    'is_input_source': True,
                    'source_obj': source
                })
    
    # Get system InputSources (owner_type='system')
    system_input_sources = InputSource.query.filter_by(
        owner_type='system',
        enabled=True
    ).all()
    for source in system_input_sources:
        if source.id not in exclude_source_ids:
            available.append({
                'id': source.id,
                'name': source.name,
                'type': source.type,
                'is_system': True,
                'is_input_source': True,
                'source_obj': source
            })
    
    # Get NewsSource (system curated sources) - convert to InputSource-like format
    # Check which NewsSources already have corresponding InputSource entries
    existing_news_source_names = {s.name for s in system_input_sources}
    
    news_sources = NewsSource.query.filter_by(is_active=True).all()
    for news_source in news_sources:
        # Skip if already converted to InputSource
        if news_source.name in existing_news_source_names:
            continue
            
        # Create a virtual source entry for NewsSource
        # We'll create the InputSource on-the-fly when selected
        available.append({
            'id': f'news_{news_source.id}',  # Use negative or prefixed ID to distinguish
            'name': news_source.name,
            'type': news_source.source_type or 'rss',
            'is_system': True,
            'is_input_source': False,
            'is_news_source': True,
            'news_source_id': news_source.id,
            'feed_url': news_source.feed_url,
            'source_obj': news_source
        })
    
    # Sort by name
    available.sort(key=lambda x: x['name'].lower())
    return available


def create_input_source_from_news_source(news_source_id, user):
    """
    Create an InputSource entry from a NewsSource (on-the-fly conversion).
    This bridges NewsSource to InputSource for the briefing system.
    
    Args:
        news_source_id: NewsSource.id
        user: Current user (for ownership if needed)
    
    Returns:
        InputSource instance (existing or newly created)
    """
    news_source = db.get_or_404(NewsSource, news_source_id)
    
    # Check if InputSource already exists for this NewsSource
    existing = InputSource.query.filter_by(
        owner_type='system',
        name=news_source.name
    ).first()
    
    if existing:
        return existing
    
    # Create new InputSource from NewsSource
    input_source = InputSource(
        owner_type='system',
        owner_id=None,  # System sources have no owner
        name=news_source.name,
        type=news_source.source_type or 'rss',
        config_json={'url': news_source.feed_url},
        enabled=news_source.is_active,
        status='ready',
        last_fetched_at=news_source.last_fetched_at
    )
    
    db.session.add(input_source)
    db.session.flush()  # Use flush instead of commit to keep transaction atomic
    
    return input_source


# =============================================================================
# Permission Helpers (DRY)
# =============================================================================

def can_access_briefing(user, briefing):
    """
    Check if a user can access a briefing.

    Args:
        user: Current user (from flask_login)
        briefing: Briefing model instance

    Returns:
        bool: True if user can access, False otherwise
    """
    if getattr(user, 'is_admin', False):
        return True
    if briefing.owner_type == 'user':
        return briefing.owner_id == user.id
    elif briefing.owner_type == 'org':
        # Check if user owns or is a member of this organization
        user_org = get_user_organization(user)
        return user_org and briefing.owner_id == user_org.id
    return False


def can_access_source(user, source):
    """
    Check if a user can access an input source.

    Args:
        user: Current user (from flask_login)
        source: InputSource model instance

    Returns:
        bool: True if user can access, False otherwise
    """
    if getattr(user, 'is_admin', False):
        return True
    if source.owner_type == 'system':
        return True  # System sources are accessible to all
    elif source.owner_type == 'user':
        return source.owner_id == user.id
    elif source.owner_type == 'org':
        # Check if user owns or is a member of this organization
        user_org = get_user_organization(user)
        return user_org and source.owner_id == user_org.id
    return False


def add_auto_recipient_for_user(briefing, user):
    """
    Add the creator as an active recipient for a briefing.

    Uses username as the persisted recipient name because `User.username` is the
    canonical required identity field in the current schema.
    """
    email = getattr(user, 'email', None)
    username = getattr(user, 'username', None)
    if not email or not username:
        raise ValueError("Cannot add auto recipient without user email and username")

    auto_recipient = BriefRecipient(
        briefing_id=briefing.id,
        email=email,
        name=username,
        status='active'
    )
    auto_recipient.generate_magic_token()
    db.session.add(auto_recipient)
    return auto_recipient


def populate_briefing_sources_from_template(briefing, default_sources, user):
    """
    Populate a briefing with sources from a template's default_sources list.
    
    This is a reusable utility that handles multiple source formats:
    - Dict format: {'name': 'Source Name', 'type': 'rss'}
    - Integer ID: InputSource or NewsSource ID
    - String: NewsSource name
    
    Args:
        briefing: Briefing instance (must be flushed/have an ID)
        default_sources: List of source references from template
        user: Current user for access control
    
    Returns:
        tuple: (sources_added: int, sources_failed: int, missing_sources: list)
    """
    sources_added = 0
    sources_failed = 0
    missing_sources = []
    
    if not default_sources:
        return sources_added, sources_failed, missing_sources
    
    if not isinstance(default_sources, list) or len(default_sources) == 0:
        return sources_added, sources_failed, missing_sources
    
    for source_ref in default_sources:
        try:
            source = None
            source_name_for_log = None

            # Handle dict format {'name': 'Source Name', 'type': 'rss'}
            if isinstance(source_ref, dict):
                source_name = source_ref.get('name')
                source_name_for_log = source_name
                if source_name:
                    # Try exact match first, then case-insensitive
                    news_source = NewsSource.query.filter_by(name=source_name).first()
                    if not news_source:
                        news_source = NewsSource.query.filter(
                            db.func.lower(NewsSource.name) == source_name.lower()
                        ).first()
                    if news_source:
                        source = create_input_source_from_news_source(news_source.id, user)
                    else:
                        missing_sources.append(source_name)
                        logger.warning(f"NewsSource not found for template source: {source_name}")

            # Try as InputSource ID first
            elif isinstance(source_ref, int):
                source_name_for_log = f"ID:{source_ref}"
                source = db.session.get(InputSource,source_ref)
                # Also try as NewsSource ID (convert to InputSource)
                if not source:
                    news_source = db.session.get(NewsSource,source_ref)
                    if news_source:
                        source = create_input_source_from_news_source(news_source.id, user)

            # Try as string (NewsSource name)
            elif isinstance(source_ref, str):
                source_name_for_log = source_ref
                # Try exact match first, then case-insensitive
                news_source = NewsSource.query.filter_by(name=source_ref).first()
                if not news_source:
                    news_source = NewsSource.query.filter(
                        db.func.lower(NewsSource.name) == source_ref.lower()
                    ).first()
                if news_source:
                    source = create_input_source_from_news_source(news_source.id, user)
                else:
                    missing_sources.append(source_ref)
                    logger.warning(f"NewsSource not found for template source: {source_ref}")

            if source and can_access_source(user, source):
                # Check if already added (safety check for duplicates)
                existing = BriefingSource.query.filter_by(
                    briefing_id=briefing.id,
                    source_id=source.id
                ).first()

                if not existing:
                    briefing_source = BriefingSource(
                        briefing_id=briefing.id,
                        source_id=source.id
                    )
                    db.session.add(briefing_source)
                    sources_added += 1
        except Exception as e:
            logger.warning(f"Failed to add source from template: {source_ref}: {e}")
            sources_failed += 1
            continue
    
    # Log summary for monitoring stale template data
    if missing_sources:
        logger.warning(
            f"Template source population: {len(missing_sources)} sources not found in database. "
            f"Missing: {missing_sources[:5]}{'...' if len(missing_sources) > 5 else ''}"
        )
    
    return sources_added, sources_failed, missing_sources


def briefing_owner_required(f):
    """
    Decorator that checks if current user owns the briefing.
    Expects briefing_id as the first URL parameter.
    Stores the briefing in g.briefing for use in the view.
    """
    @wraps(f)
    def decorated_function(briefing_id, *args, **kwargs):
        briefing = db.get_or_404(Briefing, briefing_id)
        if not can_access_briefing(current_user, briefing):
            flash(_('You do not have permission to access this briefing'), 'error')
            return redirect(url_for('briefing.list_briefings'))
        g.briefing = briefing
        return f(briefing_id, *args, **kwargs)
    return decorated_function


def check_briefing_permission(briefing, error_message=None, redirect_to='detail'):
    """
    Helper function to check briefing permission and return appropriate response.
    
    Args:
        briefing: Briefing instance
        error_message: Custom error message (optional)
        redirect_to: Where to redirect on failure ('detail', 'list', or custom route name)
    
    Returns:
        tuple: (is_allowed: bool, redirect_response or None)
    """
    if not can_access_briefing(current_user, briefing):
        msg = error_message or 'You do not have permission to access this briefing'
        flash(msg, 'error')
        
        if redirect_to == 'detail':
            return False, redirect(url_for('briefing.detail', briefing_id=briefing.id))
        elif redirect_to == 'list':
            return False, redirect(url_for('briefing.list_briefings'))
        else:
            return False, redirect(url_for(redirect_to, briefing_id=briefing.id))
    
    return True, None


def source_owner_required(f):
    """
    Decorator that checks if current user owns the source.
    Expects source_id as a URL parameter.
    Stores the source in g.source for use in the view.
    """
    @wraps(f)
    def decorated_function(*args, source_id=None, **kwargs):
        if source_id is None:
            source_id = kwargs.get('source_id') or request.view_args.get('source_id')
        source = db.get_or_404(InputSource, source_id)
        if not can_access_source(current_user, source):
            flash(_('You do not have access to this source'), 'error')
            return redirect(url_for('briefing.list_sources'))
        g.source = source
        return f(*args, source_id=source_id, **kwargs)
    return decorated_function


@briefing_bp.route('/landing')
@limiter.limit("60/minute")
def landing():
    """Public landing page for Briefing System - marketing/sales page.
    Users who already have subscription access (including ``past_due`` grace) go to
    their dashboard. Logged-in users without access still see pricing."""
    if current_user.is_authenticated:
        if get_active_subscription(current_user):
            return redirect(url_for('briefing.list_briefings'))
    # priceValidUntil for SoftwareApplication JSON-LD — rolling 1 year so the schema
    # never advertises a stale/expired price to search engines.
    price_valid_until = (date.today() + timedelta(days=365)).isoformat()
    return render_template('briefing/landing.html', price_valid_until=price_valid_until)


@briefing_bp.route('/')
@login_required
@limiter.limit("60/minute")
def list_briefings():
    """List all briefings for current user/org"""
    # Get user's briefings
    user_briefings = Briefing.query.filter_by(
        owner_type='user',
        owner_id=current_user.id
    ).order_by(Briefing.created_at.desc()).all()

    # Get org briefings if user belongs to an organization (owner or member)
    org_briefings = []
    user_org = get_user_organization(current_user)
    if user_org:
        org_briefings = Briefing.query.filter_by(
            owner_type='org',
            owner_id=user_org.id
        ).order_by(Briefing.created_at.desc()).all()

    # Get featured templates for empty state display
    featured_templates = []
    if not user_briefings and not org_briefings:
        featured_templates = BriefTemplate.query.filter_by(
            is_active=True, 
            is_featured=True
        ).order_by(BriefTemplate.sort_order).limit(6).all()

    active_sub = get_active_subscription(current_user)

    # Resolve subscription activation race: if webhook has now synced, clear the flag
    activation_pending = False
    if session.get('pending_subscription_activation'):
        if active_sub:
            session.pop('pending_subscription_activation', None)
        else:
            activation_pending = True

    # Show in-app trial reminder during the final two weeks of trial (Stripe emails fire ~3 days before end).
    trial_days_remaining = None
    if active_sub and active_sub.status == 'trialing' and active_sub.trial_end:
        days = (active_sub.trial_end - utcnow_naive()).days
        if 0 <= days <= 14:
            trial_days_remaining = days

    # Payment failed (Stripe retry window): still entitled via get_active_subscription.
    is_past_due = bool(
        Subscription.query.filter(
            Subscription.user_id == current_user.id,
            Subscription.status == 'past_due'
        ).first()
        or (user_org and Subscription.query.filter(
            Subscription.org_id == user_org.id,
            Subscription.status == 'past_due'
        ).first())
    )

    return render_template(
        'briefing/list.html',
        user_briefings=user_briefings,
        org_briefings=org_briefings,
        featured_templates=featured_templates,
        active_sub=active_sub,
        activation_pending=activation_pending,
        trial_days_remaining=trial_days_remaining,
        is_past_due=is_past_due,
    )


@briefing_bp.route('/marketplace')
@login_required
@limiter.limit("60/minute")
def marketplace():
    """
    Template marketplace - browse pre-built briefing templates.
    Users can filter by category and audience type.
    """
    category_filter = request.args.get('category')
    audience_filter = request.args.get('audience')
    
    # Define categories for UI
    categories = {
        'core_insight': 'Core Insight',
        'organizational': 'Organizational',
        'personal_interest': 'Personal Interest',
        'lifestyle': 'Lifestyle & Wellbeing',
    }
    
    # Build query for active templates
    query = BriefTemplate.query.filter_by(is_active=True)
    
    if category_filter:
        query = query.filter_by(category=category_filter)
    
    if audience_filter:
        # Filter by audience type (or 'all' which works for everyone)
        query = query.filter(
            db.or_(
                BriefTemplate.audience_type == audience_filter,
                BriefTemplate.audience_type == 'all'
            )
        )
    
    templates = query.order_by(BriefTemplate.sort_order, BriefTemplate.name).all()

    # Separate featured templates - show featured that match category filter (if any)
    featured_templates = [t for t in templates if t.is_featured]
    if category_filter:
        featured_templates = [t for t in featured_templates if t.category == category_filter]

    # Group templates by category (exclude featured to avoid duplication)
    templates_by_category = {}
    for cat_key in categories.keys():
        if category_filter and category_filter != cat_key:
            continue
        cat_templates = [t for t in templates if t.category == cat_key and not t.is_featured]
        if cat_templates:
            templates_by_category[cat_key] = cat_templates
    
    # Check if all categories are empty
    all_empty = not any(templates_by_category.values()) and not featured_templates
    
    return render_template(
        'briefing/marketplace.html',
        templates=templates,
        featured_templates=featured_templates,
        templates_by_category=templates_by_category,
        categories=categories,
        category_filter=category_filter,
        audience_filter=audience_filter,
        all_empty=all_empty
    )


@briefing_bp.route('/template/<int:template_id>/preview')
@limiter.limit("60/minute")
def preview_template(template_id):
    """
    Preview a template - show details, configurable options, and sample output.
    This route is public (no login required) so users can browse before signing up.
    """
    template = db.get_or_404(BriefTemplate, template_id)
    
    if not template.is_active:
        flash(_('This template is no longer available'), 'error')
        return redirect(url_for('briefing.marketplace'))
    
    config_options = template.configurable_options or {}
    guardrails = template.guardrails or {}
    
    return render_template(
        'briefing/preview_template.html',
        template=template,
        config_options=config_options,
        guardrails=guardrails
    )


@briefing_bp.route('/template/<int:template_id>/use', methods=['GET', 'POST'])
@login_required
@limiter.limit("20/minute")
def use_template(template_id):
    """
    Use a template to create a new briefing.
    Shows configuration wizard with template defaults and allowed customizations.
    """
    if not current_user.is_admin:
        sub = get_active_subscription(current_user)
        if not sub:
            # Check if user just completed payment and subscription is activating
            if session.get('pending_subscription_activation'):
                session.pop('pending_subscription_activation', None)
                flash(_('Your subscription is still activating. Please wait a few seconds and try again. You can also check "Manage Billing" to verify.'), 'info')
                return redirect(url_for('briefing.list_briefings'))
            session['post_checkout_template_id'] = template_id
            flash(_('You need an active subscription to create briefings. Start your free trial today!'), 'info')
            return redirect(url_for('briefing.landing') + '#pricing')
        
        limit_error = enforce_brief_limit(current_user)
        if limit_error:
            flash(limit_error, 'info')
            return redirect(url_for('briefing.list_briefings'))
    
    template = db.get_or_404(BriefTemplate, template_id)
    
    if not template.is_active:
        flash(_('This template is no longer available'), 'error')
        return redirect(url_for('briefing.marketplace'))
    
    # Check audience restrictions
    if template.audience_type == 'organization' and not get_user_organization(current_user):
        flash(_('This template is only available for organizations. You need to be part of an organization to use it.'), 'error')
        return redirect(url_for('briefing.marketplace'))
    
    if request.method == 'POST':
        try:
            # Get form data with template defaults as fallback
            name = request.form.get('name', '').strip()
            if not name:
                name = f"My {template.name}"
            
            description = request.form.get('description', '').strip()
            if not description:
                description = template.description
            
            owner_type = request.form.get('owner_type', 'user')

            # Validate owner_type for organization templates
            if owner_type == 'org':
                user_org = get_user_organization(current_user)
                if not user_org:
                    flash(_('You need to be part of an organization to create organization briefings'), 'error')
                    return redirect(url_for('briefing.use_template', template_id=template_id))
                owner_id = user_org.id
            else:
                owner_id = current_user.id
            
            # Get configurable options from template
            config_options = template.configurable_options or {}
            
            # Get cadence (if configurable)
            cadence = template.default_cadence
            if config_options.get('cadence', True):
                cadence = request.form.get('cadence', template.default_cadence)
                allowed_cadences = config_options.get('cadence_options', ['daily', 'weekly'])
                if cadence not in allowed_cadences:
                    cadence = template.default_cadence
            
            # Get timezone
            timezone = request.form.get('timezone', 'UTC')
            preferred_send_hour = request.form.get('preferred_send_hour', type=int) or 18
            preferred_send_minute = request.form.get('preferred_send_minute', type=int) or 0
            
            # Get visibility (if configurable)
            visibility = 'private'
            guardrails = template.guardrails or {}
            if guardrails.get('visibility_locked'):
                visibility = guardrails['visibility_locked']
            elif config_options.get('visibility', True):
                visibility = request.form.get('visibility', 'private')
            
            # Get mode (if configurable)
            mode = 'auto_send'
            if config_options.get('auto_send', True):
                mode = request.form.get('mode', 'auto_send')
            
            # Create briefing from template with guardrails
            briefing = Briefing(
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                description=description,
                theme_template_id=template.id,
                cadence=cadence,
                timezone=timezone,
                preferred_send_hour=preferred_send_hour,
                preferred_send_minute=preferred_send_minute,
                mode=mode,
                visibility=visibility,
                tone=template.default_tone,
                max_items=guardrails.get('max_items', 10),
                custom_prompt=template.custom_prompt_prefix,
                guardrails=guardrails if guardrails else None,
                accent_color=template.default_accent_color or '#3B82F6',
                status='active'
            )
            
            db.session.add(briefing)
            db.session.flush()  # Get briefing.id for source linking

            # Auto-add the creating user as a recipient
            add_auto_recipient_for_user(briefing, current_user)

            # Auto-populate sources from template using utility function
            sources_added, sources_failed, __ = populate_briefing_sources_from_template(
                briefing, template.default_sources, current_user
            )

            # Increment template usage count
            template.times_used = (template.times_used or 0) + 1

            db.session.commit()

            _track_posthog('briefing_created', current_user.id, {
                'briefing_id': briefing.id,
                'briefing_name': briefing.name or name,
                'owner_type': owner_type,
                'cadence': cadence,
                'from_template': True,
                'template_id': template_id,
                'sources_added': sources_added,
            }, flush=True)

            # Show appropriate success message
            if sources_added > 0:
                msg = f'Briefing "{name}" created from template with {sources_added} sources!'
                if sources_failed > 0:
                    msg += f' ({sources_failed} sources could not be added)'
                flash(msg, 'success')
            else:
                if sources_failed > 0:
                    flash(_('Briefing "%(name)s" created from template, but %(sources_failed)s sources could not be added. Add more sources below to start generating briefs.', name=name, sources_failed=sources_failed), 'warning')
                else:
                    flash(_('Briefing "%(name)s" created from template! Add sources below to start generating briefs.', name=name), 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing.id))
            
        except Exception as e:
            logger.error(f"Error creating briefing from template: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while creating your briefing. Please try again.'), 'error')
            return redirect(url_for('briefing.use_template', template_id=template_id))
    
    # GET request - show configuration form
    config_options = template.configurable_options or {}
    guardrails = template.guardrails or {}
    
    return render_template(
        'briefing/use_template.html',
        template=template,
        config_options=config_options,
        guardrails=guardrails,
        timezones=get_all_timezones(),
        has_company_profile=get_user_organization(current_user) is not None
    )


@briefing_bp.route('/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def create_briefing():
    """Create a new briefing"""
    if not current_user.is_admin:
        sub = get_active_subscription(current_user)
        if not sub:
            # Check if user just completed payment and subscription is activating
            if session.get('pending_subscription_activation'):
                session.pop('pending_subscription_activation', None)
                flash(_('Your subscription is still activating. Please wait a few seconds and try again. You can also check "Manage Billing" to verify.'), 'info')
                return redirect(url_for('briefing.list_briefings'))
            flash(_('You need an active subscription to create briefings. Start your free trial today!'), 'info')
            return redirect(url_for('briefing.landing') + '#pricing')
        
        limit_error = enforce_brief_limit(current_user)
        if limit_error:
            flash(limit_error, 'info')
            return redirect(url_for('briefing.list_briefings'))
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            owner_type = request.form.get('owner_type', 'user')  # 'user' | 'org'
            template_id = request.form.get('template_id', type=int) or None
            cadence = request.form.get('cadence', 'daily')
            timezone = request.form.get('timezone', 'UTC')
            preferred_send_hour = request.form.get('preferred_send_hour', type=int)
            if preferred_send_hour is None:
                preferred_send_hour = 18
            preferred_send_minute = request.form.get('preferred_send_minute', type=int)
            if preferred_send_minute is None:
                preferred_send_minute = 0
            mode = request.form.get('mode', 'auto_send')
            visibility = request.form.get('visibility', 'private')

            # Validate inputs
            is_valid, error = validate_briefing_name(name)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_cadence(cadence)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_timezone(timezone)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_send_hour(preferred_send_hour)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_send_minute(preferred_send_minute)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_mode(mode)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_visibility(visibility)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))

            # Determine owner_id
            owner_id = current_user.id
            if owner_type == 'org':
                user_org = get_user_organization(current_user)
                if not user_org:
                    flash(_('You need to be part of an organization to create org briefings'), 'error')
                    return redirect(url_for('briefing.create_briefing'))
                owner_id = user_org.id

            # Get branding fields (for org briefings)
            from_name = request.form.get('from_name', '').strip() or None
            from_email = request.form.get('from_email', '').strip().lower() or None
            sending_domain_id = request.form.get('sending_domain_id', type=int) or None
            
            # Validate from_email if domain is selected (email is required)
            if sending_domain_id:
                if not from_email:
                    flash(_('Email address is required when a sending domain is selected'), 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                domain = db.session.get(SendingDomain,sending_domain_id)
                if not domain:
                    flash(_('Selected domain not found'), 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                if domain.status != 'verified':
                    flash(_('Selected domain is not verified. Please verify it first.'), 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                # Validate email format
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                # Validate email matches domain
                domain_name = domain.domain
                if not from_email.endswith(f'@{domain_name}'):
                    flash(_('Email must be from verified domain: %(domain_name)s', domain_name=domain_name), 'error')
                    return redirect(url_for('briefing.create_briefing'))
            elif from_email:
                # Email provided but no domain - validate format only
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.create_briefing'))
            
            # Get template defaults if template selected
            template = None
            template_tone = None
            template_max_items = None
            template_custom_prompt = None
            template_guardrails = None
            template_accent_color = None
            
            if template_id:
                template = db.session.get(BriefTemplate,template_id)
                if template:
                    template_tone = template.default_tone
                    template_guardrails = template.guardrails or {}
                    template_max_items = template_guardrails.get('max_items', 10)
                    template_custom_prompt = template.custom_prompt_prefix
                    template_accent_color = template.default_accent_color or '#3B82F6'
            
            # Create briefing with template defaults applied
            briefing = Briefing(
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                description=description,
                theme_template_id=template_id,
                cadence=cadence,
                timezone=timezone,
                preferred_send_hour=preferred_send_hour,
                preferred_send_minute=preferred_send_minute,
                mode=mode,
                visibility=visibility,
                status='active',
                from_name=from_name if owner_type == 'org' else None,
                from_email=from_email if (owner_type == 'org' and sending_domain_id) else None,
                sending_domain_id=sending_domain_id if owner_type == 'org' else None,
                tone=template_tone,
                max_items=template_max_items,
                custom_prompt=template_custom_prompt,
                guardrails=template_guardrails if template_guardrails else None,
                accent_color=template_accent_color
            )

            db.session.add(briefing)
            db.session.flush()  # Get briefing.id

            # Auto-add the creating user as a recipient
            add_auto_recipient_for_user(briefing, current_user)
            
            # Auto-populate sources from template if selected
            sources_added = 0
            sources_failed = 0
            if template and template.default_sources:
                sources_added, sources_failed, __ = populate_briefing_sources_from_template(
                    briefing, template.default_sources, current_user
                )

            # Verify subscription is still active before committing (race condition protection)
            if not current_user.is_admin:
                sub = get_active_subscription(current_user)
                if not sub:
                    db.session.rollback()
                    flash(_('Your subscription expired during this operation. Please renew to continue.'), 'error')
                    return redirect(url_for('briefing.landing'))

            db.session.commit()

            _track_posthog('briefing_created', current_user.id, {
                'briefing_id': briefing.id,
                'briefing_name': briefing.name or name,
                'owner_type': owner_type,
                'cadence': cadence,
                'from_template': bool(template_id),
                'template_id': template_id,
                'sources_added': sources_added,
            }, flush=True)

            if sources_added > 0:
                msg = f'Briefing "{name}" created successfully with {sources_added} sources from template!'
                if sources_failed > 0:
                    msg += f' ({sources_failed} sources could not be added)'
                flash(msg, 'success')
            else:
                if sources_failed > 0:
                    flash(_('Briefing "%(name)s" created successfully, but %(sources_failed)s sources from template could not be added. Add more sources below to start generating briefs.', name=name, sources_failed=sources_failed), 'warning')
                else:
                    flash(_('Briefing "%(name)s" created successfully! Add sources below to start generating briefs.', name=name), 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing.id))

        except Exception as e:
            logger.error(f"Error creating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while creating the briefing'), 'error')
            return redirect(url_for('briefing.create_briefing'))

    # GET: Show create form
    templates = BriefTemplate.query.filter_by(allow_customization=True).all()
    user_org = get_user_organization(current_user)
    has_company_profile = user_org is not None

    # Get available sending domains for org briefings
    available_domains = []
    if user_org:
        available_domains = SendingDomain.query.filter_by(
            org_id=user_org.id
        ).order_by(SendingDomain.created_at.desc()).all()
    
    # Get all timezones for dropdown (DRY - using helper function)
    all_timezones = get_all_timezones()
    
    return render_template(
        'briefing/create.html',
        templates=templates,
        has_company_profile=has_company_profile,
        available_domains=available_domains,
        all_timezones=all_timezones
    )


@briefing_bp.route('/<int:briefing_id>')
@login_required
@limiter.limit("60/minute")
def detail(briefing_id):
    """View briefing details"""
    briefing = (
        Briefing.query.options(
            selectinload(Briefing.sources).joinedload(BriefingSource.source)
        )
        .filter_by(id=briefing_id)
        .first_or_404()
    )

    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to view this briefing',
        redirect_to='list'
    )
    if not is_allowed:
        return redirect_response

    # Get related data with priority info
    sources_with_priority = []
    for bs in briefing.sources:
        source = bs.source
        if source:
            source._priority = getattr(bs, 'priority', 1) or 1
            sources_with_priority.append(source)
    sources = sources_with_priority
    recipients = briefing.recipients.filter_by(status='active').all()
    recent_runs = briefing.runs.limit(10).all()
    
    # Get available sources (InputSource + NewsSource)
    added_source_ids = {s.id for s in sources}
    available_sources_list = get_available_sources_for_user(current_user, exclude_source_ids=added_source_ids)
    
    # Calculate next scheduled time for display (DRY - using helper function)
    next_scheduled_time = calculate_next_scheduled_time(briefing)

    return render_template(
        'briefing/detail.html',
        briefing=briefing,
        sources=sources,
        recipients=recipients,
        recent_runs=recent_runs,
        available_sources=available_sources_list,
        next_scheduled_time=next_scheduled_time
    )


@briefing_bp.route('/<int:briefing_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def edit(briefing_id):
    """Edit briefing configuration"""
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to edit this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response

    if request.method == 'POST':
        try:
            # Get form values
            name = (request.form.get('name') or briefing.name or '').strip()
            description = request.form.get('description', '').strip()
            cadence = request.form.get('cadence') or briefing.cadence or 'daily'
            timezone = request.form.get('timezone') or briefing.timezone or 'UTC'
            preferred_send_hour = request.form.get('preferred_send_hour', type=int)
            if preferred_send_hour is None:
                preferred_send_hour = briefing.preferred_send_hour
            preferred_send_minute = request.form.get('preferred_send_minute', type=int)
            if preferred_send_minute is None:
                preferred_send_minute = getattr(briefing, 'preferred_send_minute', 0)
            mode = request.form.get('mode', briefing.mode)
            visibility = request.form.get('visibility', briefing.visibility)
            status = request.form.get('status', briefing.status)

            # Validate inputs
            is_valid, error = validate_briefing_name(name)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_cadence(cadence)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_timezone(timezone)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_send_hour(preferred_send_hour)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_send_minute(preferred_send_minute)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_mode(mode)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            is_valid, error = validate_visibility(visibility)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            # Validate status
            if status not in ['active', 'paused']:
                flash(_("Status must be 'active' or 'paused'"), 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            # Get branding fields (for org briefings)
            from_name = request.form.get('from_name', '').strip() or None
            from_email = request.form.get('from_email', '').strip().lower() or None
            sending_domain_id = request.form.get('sending_domain_id', type=int) or None
            
            # Validate from_email if domain is selected (email is required)
            if sending_domain_id:
                if not from_email:
                    flash(_('Email address is required when a sending domain is selected'), 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                domain = db.session.get(SendingDomain,sending_domain_id)
                if not domain:
                    flash(_('Selected domain not found'), 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                if domain.status != 'verified':
                    flash(_('Selected domain is not verified. Please verify it first.'), 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                # Validate email format
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                # Validate email matches domain
                domain_name = domain.domain
                if not from_email.endswith(f'@{domain_name}'):
                    flash(_('Email must be from verified domain: %(domain_name)s', domain_name=domain_name), 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
            elif from_email:
                # Email provided but no domain - validate format only
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
            
            # Get AI settings fields
            custom_prompt = request.form.get('custom_prompt', '').strip() or None
            tone = request.form.get('tone', 'calm_neutral')
            max_items = request.form.get('max_items', type=int) or 10
            
            # Get content preferences
            topic_names = request.form.getlist('topic_names[]')
            topic_weights = request.form.getlist('topic_weights[]')
            topic_preferences = {}
            for name, weight in zip(topic_names, topic_weights):
                name = name.strip()
                if name:
                    try:
                        topic_preferences[name] = int(weight)
                    except (ValueError, TypeError):
                        topic_preferences[name] = 2  # Default to medium
            
            # Get content filters
            include_keywords_str = request.form.get('include_keywords', '').strip()
            exclude_keywords_str = request.form.get('exclude_keywords', '').strip()
            
            filters_json = {}
            if include_keywords_str:
                filters_json['include_keywords'] = [k.strip() for k in include_keywords_str.split(',') if k.strip()]
            if exclude_keywords_str:
                filters_json['exclude_keywords'] = [k.strip() for k in exclude_keywords_str.split(',') if k.strip()]
            
            # Get visual branding fields
            logo_url = request.form.get('logo_url', '').strip() or None
            accent_color = request.form.get('accent_color', '#3B82F6').strip()
            header_text = request.form.get('header_text', '').strip() or None
            
            # Capture cadence before update for change detection
            old_cadence = briefing.cadence

            # Update briefing
            briefing.name = name
            briefing.description = description
            briefing.cadence = cadence
            briefing.timezone = timezone
            briefing.preferred_send_hour = preferred_send_hour
            briefing.preferred_send_minute = preferred_send_minute
            briefing.mode = mode
            briefing.visibility = visibility
            briefing.status = status
            
            # Update AI settings
            briefing.custom_prompt = custom_prompt
            briefing.tone = tone
            briefing.max_items = max_items
            
            # Update content preferences
            briefing.topic_preferences = topic_preferences if topic_preferences else None
            briefing.filters_json = filters_json if filters_json else None
            
            # Update visual branding
            briefing.logo_url = logo_url
            briefing.accent_color = accent_color
            briefing.header_text = header_text
            
            # Update email branding (only for org briefings)
            if briefing.owner_type == 'org':
                briefing.from_name = from_name
                briefing.sending_domain_id = sending_domain_id
                
                # If domain removed, clear from_email
                # If domain added/changed, use provided email
                if not sending_domain_id:
                    # Domain removed - clear from_email if it was from a custom domain
                    briefing.from_email = None
                else:
                    # Domain set - use provided email
                    briefing.from_email = from_email

            db.session.commit()

            _track_posthog('briefing_edited', current_user.id, {
                'briefing_id': briefing.id,
                'briefing_name': briefing.name,
                'owner_type': briefing.owner_type,
                'cadence': briefing.cadence,
            })
            if old_cadence != briefing.cadence:
                _track_posthog('daily_brief_cadence_changed', current_user.id, {
                    'briefing_id': briefing.id,
                    'previous_cadence': old_cadence,
                    'new_cadence': briefing.cadence,
                }, flush=True)

            flash(_('Briefing updated successfully'), 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        except Exception as e:
            logger.error(f"Error updating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while updating the briefing'), 'error')
            return redirect(url_for('briefing.edit', briefing_id=briefing_id))
    
    # GET: Show edit form
    # Get available sending domains for org briefings
    available_domains = []
    if briefing.owner_type == 'org' and current_user.company_profile:
        available_domains = SendingDomain.query.filter_by(
            org_id=current_user.company_profile.id
        ).order_by(SendingDomain.created_at.desc()).all()
    
    templates = BriefTemplate.query.all()
    
    # Get all timezones for dropdown (DRY - using helper function)
    all_timezones = get_all_timezones()
    
    return render_template(
        'briefing/edit.html', 
        briefing=briefing, 
        templates=templates,
        available_domains=available_domains,
        all_timezones=all_timezones
    )


@briefing_bp.route('/<int:briefing_id>/delete', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def delete(briefing_id):
    """Delete a briefing"""
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to delete this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response

    try:
        name = briefing.name
        db.session.delete(briefing)
        db.session.commit()
        flash(_('Briefing "%(name)s" deleted successfully', name=name), 'success')
    except Exception as e:
        logger.error(f"Error deleting briefing: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred while deleting the briefing'), 'error')

    return redirect(url_for('briefing.list_briefings'))


@briefing_bp.route('/templates')
@login_required
@limiter.limit("60/minute")
def list_templates():
    """List available brief templates"""
    templates = BriefTemplate.query.all()
    return render_template('briefing/templates.html', templates=templates)


@briefing_bp.route('/api/<int:briefing_id>')
@login_required
@limiter.limit("60/minute")
def api_detail(briefing_id):
    """API endpoint for briefing details (JSON)"""
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check permissions (DRY) - API endpoint returns JSON
    if not can_access_briefing(current_user, briefing):
        return jsonify({'error': _('Permission denied')}), 403

    return jsonify(briefing.to_dict())


# =============================================================================
# Source Management Routes
# =============================================================================

@briefing_bp.route('/sources')
@login_required
@limiter.limit("60/minute")
def list_sources():
    """List user's input sources"""
    # Get user's sources
    user_sources = InputSource.query.filter_by(
        owner_type='user',
        owner_id=current_user.id
    ).order_by(InputSource.created_at.desc()).all()
    
    # Get org sources if user belongs to an organization
    org_sources = []
    user_org = get_user_organization(current_user)
    if user_org:
        org_sources = InputSource.query.filter_by(
            owner_type='org',
            owner_id=user_org.id
        ).order_by(InputSource.created_at.desc()).all()
    
    return render_template(
        'briefing/sources.html',
        user_sources=user_sources,
        org_sources=org_sources
    )


@briefing_bp.route('/sources/<int:source_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit("20/minute")
@source_owner_required
def edit_source(source_id):
    """Edit an input source"""
    source = g.source
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            
            is_valid, error = validate_briefing_name(name)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.edit_source', source_id=source_id))
            
            if source.type == 'rss':
                url = request.form.get('url', '').strip()
                is_valid, error = validate_rss_url(url)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.edit_source', source_id=source_id))
                source.config_json = {'url': url}
            
            source.name = name
            db.session.commit()
            
            flash(_('Source "%(name)s" updated successfully', name=name), 'success')
            return redirect(url_for('briefing.list_sources'))
            
        except Exception as e:
            logger.error(f"Error updating source: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while updating the source'), 'error')
    
    return render_template('briefing/edit_source.html', source=source)


@briefing_bp.route('/sources/<int:source_id>/delete', methods=['POST'])
@login_required
@limiter.limit("10/minute")
@source_owner_required
def delete_source(source_id):
    """Delete an input source"""
    source = g.source
    
    try:
        source_name = source.name
        
        # Check if source is used in any briefings
        linked_briefings = BriefingSource.query.filter_by(source_id=source_id).all()
        if linked_briefings:
            for bs in linked_briefings:
                db.session.delete(bs)
        
        db.session.delete(source)
        db.session.commit()
        
        flash(_('Source "%(source_name)s" has been deleted', source_name=source_name), 'success')
    except Exception as e:
        logger.error(f"Error deleting source: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred while deleting the source'), 'error')
    
    return redirect(url_for('briefing.list_sources'))


@briefing_bp.route('/sources/add/rss', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def add_rss_source():
    """Add RSS feed source"""
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            url = request.form.get('url', '').strip()
            owner_type = request.form.get('owner_type', 'user')
            
            # Validate inputs
            is_valid, error = validate_briefing_name(name)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.add_rss_source'))
            
            is_valid, error = validate_rss_url(url)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.add_rss_source'))
            
            # Determine owner_id
            owner_id = current_user.id
            if owner_type == 'org':
                user_org = get_user_organization(current_user)
                if not user_org:
                    flash(_('You need to be part of an organization to create org sources'), 'error')
                    return redirect(url_for('briefing.add_rss_source'))
                owner_id = user_org.id
            
            # Check for duplicate URL to prevent multi-click duplicates
            existing_source = InputSource.query.filter_by(
                owner_type=owner_type,
                owner_id=owner_id,
                type='rss'
            ).filter(
                InputSource.config_json['url'].astext == url
            ).first()
            
            if existing_source:
                flash(_('A source with this RSS feed URL already exists: "%(name)s"', name=existing_source.name), 'info')
                return redirect(url_for('briefing.list_sources'))
            
            # Check if we already have this URL as a system source or curated news source
            system_source = InputSource.query.filter_by(
                owner_type='system',
                type='rss'
            ).filter(
                InputSource.config_json['url'].astext == url
            ).first()
            
            if not system_source:
                # Also check NewsSource table for curated sources
                news_source = NewsSource.query.filter_by(feed_url=url).first()
                if news_source:
                    flash(_('This feed is already available as a curated source: "%(name)s". You can add it directly from the source library.', name=news_source.name), 'info')
            elif system_source:
                flash(_('This feed is already available as a system source: "%(name)s". You can add it directly from the source library.', name=system_source.name), 'info')
            
            source = InputSource(
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                type='rss',
                config_json={'url': url},
                status='ready',
                enabled=True
            )
            
            db.session.add(source)
            db.session.commit()
            
            flash(_('RSS source "%(name)s" added successfully', name=name), 'success')
            return redirect(url_for('briefing.list_sources'))
            
        except Exception as e:
            logger.error(f"Error adding RSS source: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while adding the source'), 'error')
    
    return render_template('briefing/add_rss_source.html')


@briefing_bp.route('/sources/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit("5/minute")
@require_feature('document_uploads')
def upload_source():
    """Upload PDF/DOCX file as source"""
    # Get briefing_id from query param or form (for redirect after upload)
    briefing_id = request.args.get('briefing_id', type=int) or request.form.get('briefing_id', type=int)
    
    if request.method == 'POST':
        try:
            from replit.object_storage import Client
            from werkzeug.utils import secure_filename
            from app.billing.abuse_guardrails import check_upload_rate_limit, record_upload
            import secrets
            import hashlib
            
            if 'file' not in request.files:
                flash(_('No file provided'), 'error')
                return redirect(url_for('briefing.upload_source'))
            
            file = request.files['file']
            if file.filename == '':
                flash(_('No file selected'), 'error')
                return redirect(url_for('briefing.upload_source'))
            
            filename = secure_filename(file.filename or '')
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset
            
            upload_allowed, upload_error = check_upload_rate_limit(current_user.id, file_size)
            if not upload_allowed:
                flash(upload_error, 'error')
                return redirect(url_for('briefing.upload_source'))
            
            is_valid, error = validate_file_upload(filename, max_size_mb=10)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.upload_source'))

            # Extract file extension
            file_ext = '.' + filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

            # Upload to Replit Object Storage
            client = Client()
            storage_key = f"briefing_uploads/{current_user.id}/{secrets.token_urlsafe(16)}{file_ext}"
            
            file_content = file.read()
            client.upload_from_bytes(storage_key, file_content)
            
            # Create InputSource with status='extracting'
            source = InputSource(
                owner_type='user',
                owner_id=current_user.id,
                name=filename.rsplit('.', 1)[0],  # Name without extension
                type='upload',
                storage_key=storage_key,
                storage_url=None,  # Files are served via the SDK key; no public URL available
                status='extracting',  # Will be processed by background job
                enabled=True
            )
            
            db.session.add(source)
            db.session.commit()
            
            record_upload(current_user.id, file_size)
            
            flash(_('File uploaded successfully. Text extraction in progress...'), 'success')
            
            # Redirect back to briefing if provided, otherwise to sources list
            if briefing_id:
                # Verify user has access to briefing
                briefing = db.session.get(Briefing,briefing_id)
                if briefing and can_access_briefing(current_user, briefing):
                    return redirect(url_for('briefing.detail', briefing_id=briefing_id))
            
            return redirect(url_for('briefing.list_sources'))
            
        except Exception as e:
            logger.error(f"Error uploading source: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while uploading the file'), 'error')
    
    return render_template('briefing/upload_source.html', briefing_id=briefing_id)


@briefing_bp.route('/<int:briefing_id>/sources/add', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def add_source_to_briefing(briefing_id):
    """Add a source to a briefing"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to modify this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    try:
        source_id_str = request.form.get('source_id', '').strip()
        if not source_id_str:
            flash(_('Source ID is required'), 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Handle NewsSource (prefixed with 'news_')
        source = None
        if source_id_str.startswith('news_'):
            news_source_id = int(source_id_str.replace('news_', ''))
            # Create InputSource from NewsSource
            source = create_input_source_from_news_source(news_source_id, current_user)
        else:
            source_id = int(source_id_str)
            source = db.session.get(InputSource,source_id)
            if not source:
                flash(_('Source not found'), 'error')
                return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check ownership (delegates to can_access_source which grants admin bypass)
        if not can_access_source(current_user, source):
            flash(_('You do not have access to this source'), 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check if source is ready (not extracting or failed)
        if source.status == 'extracting':
            flash(_('Source is still being processed. Please wait.'), 'info')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        if source.status == 'failed':
            flash(_('Source processing failed. Please check the source and try again.'), 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        # Check source limit before adding (plan-based enforcement)
        if not current_user.is_admin and not check_source_limit(current_user, additional_sources=1):
            sub = get_active_subscription(current_user)
            plan = sub.plan if sub else None
            if plan:
                limit_msg = "unlimited" if plan.max_sources == -1 else str(plan.max_sources)
                flash(_("You've reached your source limit (%(limit_msg)s) for the %(name)s plan. Please upgrade to add more sources.", limit_msg=limit_msg, name=plan.name), 'error')
            else:
                flash(_('You need an active subscription to add sources.'), 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        # Check if already added
        existing = BriefingSource.query.filter_by(
            briefing_id=briefing_id,
            source_id=source.id
        ).first()
        
        if existing:
            flash(_('Source already added to this briefing'), 'info')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Add source
        briefing_source = BriefingSource(
            briefing_id=briefing_id,
            source_id=source.id
        )
        db.session.add(briefing_source)
        db.session.commit()
        
        flash(_('Source "%(name)s" added to briefing', name=source.name), 'success')
        
    except Exception as e:
        logger.error(f"Error adding source to briefing: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred while adding the source'), 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/sources/<int:source_id>/remove', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def remove_source_from_briefing(briefing_id, source_id):
    """Remove a source from a briefing"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to modify this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    try:
        briefing_source = BriefingSource.query.filter_by(
            briefing_id=briefing_id,
            source_id=source_id
        ).first_or_404()
        
        db.session.delete(briefing_source)
        db.session.commit()
        
        flash(_('Source removed from briefing'), 'success')
        
    except Exception as e:
        logger.error(f"Error removing source from briefing: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred'), 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/sources/<int:source_id>/priority', methods=['POST'])
@login_required
@limiter.limit("30/minute")
def update_source_priority(briefing_id, source_id):
    """Update source priority for a briefing"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to modify this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    try:
        priority = int(request.form.get('priority', 1))
        priority = max(1, min(3, priority))  # Clamp to 1-3
        
        briefing_source = BriefingSource.query.filter_by(
            briefing_id=briefing_id,
            source_id=source_id
        ).first_or_404()
        
        briefing_source.priority = priority
        db.session.commit()
        
        flash(_('Source priority updated'), 'success')
        
    except Exception as e:
        logger.error(f"Error updating source priority: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred'), 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


# =============================================================================
# Recipient Management Routes
# =============================================================================

@briefing_bp.route('/<int:briefing_id>/recipients', methods=['GET', 'POST'])
@login_required
@limiter.limit("30/minute")
def manage_recipients(briefing_id):
    """Manage recipients for a briefing"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to manage recipients',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    if request.method == 'POST':
        try:
            action = request.form.get('action')

            if action == 'add':
                email = request.form.get('email', '').strip().lower()
                name = request.form.get('name', '').strip()

                if not email:
                    flash(_('Email is required'), 'error')
                    return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))

                # Validate email
                is_valid, error = validate_email(email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))

                # Check if already exists
                existing = BriefRecipient.query.filter_by(
                    briefing_id=briefing_id,
                    email=email
                ).first()

                if existing:
                    if existing.status == 'unsubscribed':
                        # Reactivate
                        existing.status = 'active'
                        existing.unsubscribed_at = None
                        existing.generate_magic_token()
                        db.session.commit()
                        flash(_('Recipient %(email)s reactivated', email=email), 'success')
                    else:
                        flash(_('Recipient already exists'), 'info')
                else:
                    # Check recipient limit before adding (plan-based enforcement)
                    if not current_user.is_admin and not check_recipient_limit(current_user, briefing_id, additional_recipients=1):
                        sub = get_active_subscription(current_user)
                        plan = sub.plan if sub else None
                        if plan:
                            limit_msg = "unlimited" if plan.max_recipients == -1 else str(plan.max_recipients)
                            flash(_("You've reached your recipient limit (%(limit_msg)s) for the %(name)s plan. Please upgrade to add more recipients.", limit_msg=limit_msg, name=plan.name), 'error')
                        else:
                            flash(_('You need an active subscription to add recipients.'), 'error')
                        return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))

                    # Create new recipient
                    recipient = BriefRecipient(
                        briefing_id=briefing_id,
                        email=email,
                        name=name or None,
                        status='active'
                    )
                    recipient.generate_magic_token()
                    db.session.add(recipient)
                    db.session.commit()
                    _track_posthog('briefing_recipient_added', current_user.id, {
                        'briefing_id': briefing_id,
                        'briefing_name': briefing.name,
                        'recipient_count': 1,
                        'bulk': False,
                    })
                    flash(_('Recipient %(email)s added successfully', email=email), 'success')

            elif action == 'bulk_add':
                emails_text = request.form.get('emails', '')
                import re
                
                # Parse emails (handle comma, newline, space, semicolon separators)
                emails = re.split(r'[,\n\s;]+', emails_text)
                emails = [e.strip().lower() for e in emails if e.strip() and '@' in e]
                
                if not emails:
                    flash(_('No valid email addresses found.'), 'error')
                    return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))
                
                added = 0
                skipped = 0
                
                for email in emails:
                    # Check limit (plan-based enforcement)
                    if not current_user.is_admin and not check_recipient_limit(current_user, briefing_id, additional_recipients=1):
                        sub = get_active_subscription(current_user)
                        plan = sub.plan if sub else None
                        if plan:
                            limit_msg = "unlimited" if plan.max_recipients == -1 else str(plan.max_recipients)
                            flash(f'Recipient limit ({limit_msg}) reached for the {plan.name} plan. {len(emails) - added - skipped} emails not added. Please upgrade to add more.', 'warning')
                        else:
                            flash(f'{len(emails) - added - skipped} emails not added due to limit.', 'warning')
                        break
                    
                    # Validate email
                    is_valid, error = validate_email(email)
                    if not is_valid:
                        skipped += 1
                        continue
                    
                    # Check if already exists
                    existing = BriefRecipient.query.filter_by(
                        briefing_id=briefing_id,
                        email=email
                    ).first()
                    
                    if existing:
                        if existing.status == 'unsubscribed':
                            # Reactivate
                            existing.status = 'active'
                            existing.unsubscribed_at = None
                            existing.generate_magic_token()
                            added += 1
                        else:
                            skipped += 1
                    else:
                        # Create new recipient
                        recipient = BriefRecipient(
                            briefing_id=briefing_id,
                            email=email,
                            name=None,
                            status='active'
                        )
                        recipient.generate_magic_token()
                        db.session.add(recipient)
                        added += 1
                
                db.session.commit()
                if added > 0:
                    _track_posthog('briefing_recipient_added', current_user.id, {
                        'briefing_id': briefing_id,
                        'briefing_name': briefing.name,
                        'recipient_count': added,
                        'bulk': True,
                    })
                flash(_('Imported %(added)s recipients. %(skipped)s skipped (already exists or invalid).', added=added, skipped=skipped), 'success')
                
            elif action == 'bulk_remove':
                recipient_ids = request.form.getlist('recipient_ids')
                if recipient_ids:
                    count = BriefRecipient.query.filter(
                        BriefRecipient.id.in_([int(rid) for rid in recipient_ids]),
                        BriefRecipient.briefing_id == briefing_id
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    flash(_('%(count)s recipient(s) removed', count=count), 'success')
                else:
                    flash(_('No recipients selected'), 'info')
                    
            elif action == 'toggle':
                recipient_id = request.form.get('recipient_id', type=int)
                if recipient_id:
                    recipient = BriefRecipient.query.filter_by(
                        id=recipient_id,
                        briefing_id=briefing_id
                    ).first()
                    
                    if recipient:
                        if recipient.status == 'active':
                            recipient.status = 'paused'
                            flash(_('%(email)s has been paused.', email=recipient.email), 'success')
                        elif recipient.status in ('paused', 'unsubscribed'):
                            recipient.status = 'active'
                            if recipient.status == 'unsubscribed':
                                recipient.unsubscribed_at = None
                                recipient.generate_magic_token()
                            flash(_('%(email)s has been activated.', email=recipient.email), 'success')
                        db.session.commit()
                        
            elif action == 'remove':
                recipient_id = request.form.get('recipient_id', type=int)
                if recipient_id:
                    recipient = BriefRecipient.query.filter_by(
                        id=recipient_id,
                        briefing_id=briefing_id
                    ).first()

                    if recipient:
                        db.session.delete(recipient)
                        db.session.commit()
                        flash(_('Recipient removed'), 'success')

            return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))

        except Exception as e:
            logger.error(f"Error managing recipients: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred'), 'error')
    
    # GET: Show recipients
    recipients = briefing.recipients.order_by(BriefRecipient.created_at.desc()).all()
    return render_template('briefing/recipients.html', briefing=briefing, recipients=recipients)


@briefing_bp.route('/<int:briefing_id>/unsubscribe/<token>', methods=['GET', 'POST'])
@limiter.limit("60/minute")
def unsubscribe(briefing_id, token):
    """
    Unsubscribe recipient from briefing.

    Accepts both GET (human click) and POST (RFC 8058 one-click, triggered by
    mail clients that honour the paired ``List-Unsubscribe`` +
    ``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` headers — required
    by Gmail for bulk senders from 2024 onward).

    Note: We intentionally do NOT enforce token expiry for unsubscribe.
    CAN-SPAM and GDPR require that unsubscribe links work indefinitely.
    Token expiry is tracked for audit purposes but not enforced here.
    """
    briefing = db.get_or_404(Briefing, briefing_id)

    recipient = BriefRecipient.query.filter_by(
        briefing_id=briefing_id,
        magic_token=token
    ).first()

    if not recipient:
        flash(_('Invalid unsubscribe link'), 'error')
        return redirect(url_for('main.index'))

    if recipient.status == 'unsubscribed':
        flash(_('You are already unsubscribed'), 'info')
    else:
        recipient.status = 'unsubscribed'
        recipient.unsubscribed_at = utcnow_naive()
        # Regenerate token to invalidate any other links (security)
        recipient.generate_magic_token(expires_hours=0)  # Immediately expired
        db.session.commit()
        _track_posthog('briefing_recipient_unsubscribed', recipient.email, {
            'briefing_id': briefing_id,
            'briefing_name': briefing.name,
            'recipient_id': recipient.id,
        }, flush=True)
        flash(_('You have been unsubscribed from this briefing'), 'success')

    return render_template('briefing/unsubscribed.html', briefing=briefing, recipient=recipient)


# =============================================================================
# BriefRun Management Routes
# =============================================================================

@briefing_bp.route('/api/<int:briefing_id>/runs/<int:run_id>/audio/generate', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit("5 per minute")
def generate_brief_run_audio(briefing_id, run_id):
    """
    Audio generation has been disabled (feature deprecated as not worthwhile).
    """
    from app.models import BriefRun

    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({'error': _('Admin access required for audio generation')}), 403

    BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id
    ).first_or_404()

    return jsonify({
        'error': _('Audio generation is disabled'),
        'code': 'AUDIO_DISABLED'
    }), 410


@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>', methods=['GET', 'POST'])
@login_required
@limiter.limit("60/minute")
def view_run(briefing_id, run_id):
    """View a BriefRun (approval workflow requires approval_workflow feature for editing/approving)"""
    briefing = db.get_or_404(Briefing, briefing_id)
    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id
    ).first_or_404()
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to view this run',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    items = sorted(brief_run.items, key=lambda x: x.position or 0)
    
    # Check for existing audio generation job
    from app.models import AudioGenerationJob
    existing_job = AudioGenerationJob.query.filter(
        AudioGenerationJob.brief_run_id == brief_run.id,
        AudioGenerationJob.brief_type == 'brief_run',
        AudioGenerationJob.status.in_(['queued', 'processing'])
    ).first()
    
    return render_template(
        'briefing/run_view.html',
        briefing=briefing,
        brief_run=brief_run,
        items=items,
        existing_audio_job=existing_job
    )


@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def edit_run(briefing_id, run_id):
    """Edit/approve a BriefRun draft"""
    briefing = db.get_or_404(Briefing, briefing_id)
    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id
    ).first_or_404()
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to edit this run',
        redirect_to='detail'
    )
    if not is_allowed:
        # Redirect to view_run instead of detail
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            
            if action == 'approve':
                # Approve and optionally send
                brief_run.approved_markdown = brief_run.draft_markdown
                brief_run.approved_html = brief_run.draft_html
                brief_run.approved_by_user_id = current_user.id
                brief_run.approved_at = utcnow_naive()
                brief_run.status = 'approved'
                
                db.session.commit()
                
                # Send emails if auto-send or manual send requested
                if briefing.mode == 'auto_send' or request.form.get('send_now') == 'true':
                    from app.briefing.email_client import send_brief_run_emails
                    result = send_brief_run_emails(brief_run.id)
                    flash(f'Brief approved and sent to {result["sent"]} recipients', 'success')
                else:
                    flash(_('Brief approved (ready to send)'), 'success')
                
                return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
            
            elif action == 'edit':
                # Update draft content
                brief_run.draft_markdown = request.form.get('content_markdown', brief_run.draft_markdown)
                # Regenerate HTML from markdown (simple)
                draft_md = brief_run.draft_markdown or ''
                brief_run.draft_html = draft_md.replace('\n', '<br>')
                
                # Save edit history
                from app.models import BriefEdit
                edit = BriefEdit(
                    brief_run_id=brief_run.id,
                    edited_by_user_id=current_user.id,
                    content_markdown=brief_run.draft_markdown,
                    content_html=brief_run.draft_html
                )
                db.session.add(edit)
                db.session.commit()
                
                flash(_('Draft updated'), 'success')
                return redirect(url_for('briefing.edit_run', briefing_id=briefing_id, run_id=run_id))
            
        except Exception as e:
            logger.error(f"Error editing BriefRun: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred'), 'error')
    
    items = sorted(brief_run.items, key=lambda x: x.position or 0)
    return render_template(
        'briefing/run_edit.html',
        briefing=briefing,
        brief_run=brief_run,
        items=items
    )


@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>/send', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def send_run(briefing_id, run_id):
    """Manually send an approved BriefRun"""
    briefing = db.get_or_404(Briefing, briefing_id)
    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id
    ).first_or_404()
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to send this run',
        redirect_to='detail'
    )
    if not is_allowed:
        # Redirect to view_run instead of detail
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    if brief_run.status != 'approved':
        flash(_('Brief must be approved before sending'), 'error')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    # Verify subscription is still active before sending (race condition protection)
    if not current_user.is_admin:
        sub = get_active_subscription(current_user)
        if not sub:
            flash(_('Your subscription expired. Please renew to send briefings.'), 'error')
            return redirect(url_for('briefing.landing'))
    
    try:
        from app.briefing.email_client import send_brief_run_emails
        result = send_brief_run_emails(brief_run.id)
        _track_posthog('brief_run_sent', current_user.id, {
            'briefing_id': briefing_id,
            'brief_run_id': brief_run.id,
            'recipients_sent': result.get('sent', 0),
            'recipients_failed': result.get('failed', 0),
        })
        flash(f'Sent to {result["sent"]} recipients ({result["failed"]} failed)', 'success')
    except Exception as e:
        logger.error(f"Error sending BriefRun: {e}", exc_info=True)
        flash(_('An error occurred while sending'), 'error')
    
    return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))


@briefing_bp.route('/approval-queue')
@login_required
@limiter.limit("60/minute")
def approval_queue():
    """List BriefRuns awaiting approval"""
    # Get briefings user has access to
    user_briefings = Briefing.query.filter_by(
        owner_type='user',
        owner_id=current_user.id,
        status='active'
    ).all()
    
    org_briefings = []
    if current_user.company_profile:
        org_briefings = Briefing.query.filter_by(
            owner_type='org',
            owner_id=current_user.company_profile.id,
            status='active'
        ).all()
    
    all_briefings = user_briefings + org_briefings
    briefing_ids = [b.id for b in all_briefings]
    
    # Get runs awaiting approval
    pending_runs = BriefRun.query.filter(
        BriefRun.briefing_id.in_(briefing_ids),
        BriefRun.status.in_(['generated_draft', 'awaiting_approval'])
    ).order_by(BriefRun.scheduled_at.desc()).all()
    
    return render_template('briefing/approval_queue.html', pending_runs=pending_runs)


# =============================================================================
# SendingDomain Management Routes
# =============================================================================

@briefing_bp.route('/domains')
@login_required
@limiter.limit("60/minute")
@require_feature('custom_branding')
def list_domains():
    """List sending domains for user's organization"""
    if not current_user.company_profile:
        flash(_('You need a company profile to manage sending domains'), 'error')
        return redirect(url_for('briefing.list_briefings'))

    domains = SendingDomain.query.filter_by(
        org_id=current_user.company_profile.id
    ).order_by(SendingDomain.created_at.desc()).all()

    return render_template('briefing/domains/list.html', domains=domains)


@briefing_bp.route('/domains/add', methods=['GET', 'POST'])
@login_required
@limiter.limit("5/minute")
@require_feature('custom_branding')
def add_domain():
    """Add a new sending domain"""
    if not current_user.company_profile:
        flash(_('You need a company profile to add sending domains'), 'error')
        return redirect(url_for('briefing.list_briefings'))

    if request.method == 'POST':
        try:
            domain = request.form.get('domain', '').strip().lower()

            # Validate domain format
            if not domain:
                flash(_('Domain is required'), 'error')
                return redirect(url_for('briefing.add_domain'))

            # Basic domain validation
            import re
            domain_pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z]{2,}$'
            if not re.match(domain_pattern, domain):
                flash(_('Invalid domain format'), 'error')
                return redirect(url_for('briefing.add_domain'))

            # Check if domain already exists
            existing = SendingDomain.query.filter_by(domain=domain).first()
            if existing:
                flash(_('This domain is already registered'), 'error')
                return redirect(url_for('briefing.add_domain'))

            # Create domain record
            sending_domain = SendingDomain(
                org_id=current_user.company_profile.id,
                domain=domain,
                status='pending_verification'
            )

            # Try to register with Resend API
            from app.briefing.domains import register_domain_with_resend
            result = register_domain_with_resend(domain)

            if result.get('success'):
                sending_domain.resend_domain_id = result.get('domain_id')
                sending_domain.dns_records_required = result.get('records', [])
                db.session.add(sending_domain)
                db.session.commit()
                flash(_('Domain "%(domain)s" added. Please configure DNS records.', domain=domain), 'success')
                return redirect(url_for('briefing.verify_domain', domain_id=sending_domain.id))
            else:
                flash(f'Failed to register domain: {result.get("error", "Unknown error")}', 'error')
                return redirect(url_for('briefing.add_domain'))

        except Exception as e:
            logger.error(f"Error adding domain: {e}", exc_info=True)
            db.session.rollback()
            flash(_('An error occurred while adding the domain'), 'error')

    return render_template('briefing/domains/add.html')


@briefing_bp.route('/domains/<int:domain_id>')
@login_required
@limiter.limit("60/minute")
def verify_domain(domain_id):
    """View domain details and verification status"""
    if not current_user.company_profile:
        flash(_('You need a company profile to manage domains'), 'error')
        return redirect(url_for('briefing.list_briefings'))

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    return render_template('briefing/domains/verify.html', domain=domain)


@briefing_bp.route('/domains/<int:domain_id>/check', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def check_domain_verification(domain_id):
    """Check/refresh domain verification status"""
    if not current_user.company_profile:
        return jsonify({'error': _('Company profile required')}), 403

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    try:
        if not domain.resend_domain_id:
            flash(_('Domain not yet registered with Resend'), 'error')
            return redirect(url_for('briefing.verify_domain', domain_id=domain_id))
        
        from app.briefing.domains import check_domain_verification_status
        result = check_domain_verification_status(domain.resend_domain_id)

        if not result.get('success'):
            flash(f"Error checking verification: {result.get('error', 'Unknown error')}", 'error')
            return redirect(url_for('briefing.verify_domain', domain_id=domain_id))

        if result.get('status') == 'verified':
            domain.status = 'verified'
            domain.verified_at = utcnow_naive()
            db.session.commit()
            flash(_('Domain verified successfully!'), 'success')
        else:
            domain.status = 'pending_verification'
            db.session.commit()
            flash(_('Domain not yet verified. Please check DNS records.'), 'info')

    except Exception as e:
        logger.error(f"Error checking domain verification: {e}", exc_info=True)
        flash(_('An error occurred while checking verification'), 'error')

    return redirect(url_for('briefing.verify_domain', domain_id=domain_id))


@briefing_bp.route('/domains/<int:domain_id>/status', methods=['GET'])
@login_required
@limiter.limit("30/minute")
def get_domain_status(domain_id):
    """Get domain status as JSON (for AJAX requests)"""
    if not current_user.company_profile:
        return jsonify({'error': _('Company profile required')}), 403

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    try:
        if not domain.resend_domain_id:
            return jsonify({
                'success': False,
                'error': _('Domain not yet registered with Resend'),
                'status': domain.status
            })

        from app.briefing.domains import check_domain_verification_status
        result = check_domain_verification_status(domain.resend_domain_id)

        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'status': domain.status
            })

        # Update domain status in database
        new_status = result.get('status')
        if new_status == 'verified' and domain.status != 'verified':
            domain.status = 'verified'
            domain.verified_at = utcnow_naive()
            db.session.commit()
        elif new_status != 'verified' and domain.status != new_status:
            domain.status = new_status
            db.session.commit()

        return jsonify({
            'success': True,
            'status': new_status,
            'raw_status': result.get('raw_status'),
            'records': result.get('records', [])
        })

    except Exception as e:
        logger.error(f"Error getting domain status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'status': domain.status
        }), 500


@briefing_bp.route('/domains/<int:domain_id>/delete', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def delete_domain(domain_id):
    """Delete a sending domain"""
    if not current_user.company_profile:
        flash(_('You need a company profile to manage domains'), 'error')
        return redirect(url_for('briefing.list_briefings'))

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    try:
        # Check if any active briefings are using this domain
        active_briefings = Briefing.query.filter_by(
            sending_domain_id=domain_id,
            status='active'
        ).count()

        if active_briefings > 0:
            flash(_('Cannot delete domain: %(active_briefings)s active briefing(s) are using it. Please remove the domain from those briefings first.', active_briefings=active_briefings), 'error')
            return redirect(url_for('briefing.list_domains'))

        # Try to remove from Resend first
        if domain.resend_domain_id:
            from app.briefing.domains import delete_domain_from_resend
            result = delete_domain_from_resend(domain.resend_domain_id)
            
            if not result.get('success'):
                # Resend deletion failed - don't delete from DB
                error_msg = result.get('error', 'Unknown error')
                flash(_('Failed to delete domain from Resend: %(error_msg)s. Domain kept in database for manual cleanup.', error_msg=error_msg), 'error')
                return redirect(url_for('briefing.list_domains'))

        # Resend deletion succeeded (or no resend_domain_id) - safe to delete from DB
        domain_name = domain.domain
        db.session.delete(domain)
        db.session.commit()
        flash(_('Domain "%(domain_name)s" deleted successfully', domain_name=domain_name), 'success')

    except Exception as e:
        logger.error(f"Error deleting domain: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred while deleting the domain'), 'error')

    return redirect(url_for('briefing.list_domains'))


# =============================================================================
# Public Archive Routes (No login required for public briefs)
# =============================================================================

@briefing_bp.route('/public/<int:briefing_id>')
@limiter.limit("30/minute")  # More restrictive for unauthenticated public endpoint
def public_briefing(briefing_id):
    """View a public briefing's archive"""
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check if briefing is public
    if briefing.visibility != 'public':
        flash(_('This briefing is not publicly accessible'), 'error')
        return redirect(url_for('main.index'))

    # Get sent runs only
    runs = BriefRun.query.filter_by(
        briefing_id=briefing_id,
        status='sent'
    ).order_by(BriefRun.sent_at.desc()).limit(50).all()

    return render_template(
        'briefing/public/archive.html',
        briefing=briefing,
        runs=runs
    )


@briefing_bp.route('/public/<int:briefing_id>/runs/<int:run_id>')
@limiter.limit("30/minute")  # More restrictive for unauthenticated public endpoint
def public_brief_run(briefing_id, run_id):
    """View a specific public brief run"""
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check if briefing is public
    if briefing.visibility != 'public':
        flash(_('This briefing is not publicly accessible'), 'error')
        return redirect(url_for('main.index'))

    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id,
        status='sent'
    ).first_or_404()

    items = sorted(brief_run.items, key=lambda x: x.position or 0)

    return render_template(
        'briefing/public/run_view.html',
        briefing=briefing,
        brief_run=brief_run,
        items=items
    )


@briefing_bp.route('/public/<int:briefing_id>/runs/<int:run_id>/reader')
@limiter.limit("60/minute")
def public_brief_run_reader(briefing_id, run_id):
    """
    Reader-optimized view for a public brief run.

    Clean, minimal HTML designed for:
    - Reader apps (ElevenReader, Pocket, Instapaper)
    - Browser reader mode
    - Text-to-speech tools
    - Accessibility
    """
    briefing = db.get_or_404(Briefing, briefing_id)

    # Check if briefing is public
    if briefing.visibility != 'public':
        # Check if current user is the owner
        is_owner = False
        if current_user.is_authenticated:
            if briefing.owner_type == 'user' and briefing.owner_id == current_user.id:
                is_owner = True
            elif briefing.owner_type == 'org':
                # Check if user is a member of the org
                from app.models import OrganizationMember
                membership = OrganizationMember.query.filter_by(
                    user_id=current_user.id,
                    org_id=briefing.owner_id
                ).first()
                if membership:
                    is_owner = True
        
        return render_template(
            'briefing/public/not_public.html',
            briefing=briefing,
            is_owner=is_owner
        )

    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id,
        status='sent'
    ).first_or_404()

    items = sorted(brief_run.items, key=lambda x: x.position or 0)

    return render_template(
        'briefing/public/run_reader.html',
        briefing=briefing,
        brief_run=brief_run,
        items=items
    )


# =============================================================================
# Test Generation & Preview Routes
# =============================================================================

@briefing_bp.route('/<int:briefing_id>/test-generate', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def test_generate(briefing_id):
    """Queue a test brief generation job (async)"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing, 
        error_message='You do not have permission to generate test briefs',
        redirect_to='detail'
    )
    if not is_allowed:
        # For AJAX requests, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': _('Permission denied')}), 403
        return redirect_response
    
    # Check if briefing has sources
    if not briefing.sources:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': _('Please add sources to your briefing before generating a test brief')}), 400
        flash(_('Please add sources to your briefing before generating a test brief'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    try:
        from app.briefing.jobs import queue_brief_generation, is_redis_available
        from app.billing.abuse_guardrails import check_generation_rate_limit, check_token_spend_limit, record_generation
        
        allowed, rate_msg = check_generation_rate_limit(current_user.id)
        if not allowed:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': rate_msg}), 429
            flash(rate_msg, 'warning')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        allowed, spend_msg = check_token_spend_limit(current_user.id)
        if not allowed:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': spend_msg}), 429
            flash(spend_msg, 'warning')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        if is_redis_available():
            job_id = queue_brief_generation(briefing_id, current_user.id)
            
            if job_id:
                # For AJAX requests, return job ID for polling
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True,
                        'job_id': job_id,
                        'message': _('Brief generation started'),
                        'status_url': url_for('briefing.generation_status', briefing_id=briefing_id, job_id=job_id)
                    })
                # For regular form submission, redirect to a waiting page
                flash(_('Brief generation started. This may take up to a minute.'), 'info')
                return redirect(url_for('briefing.generation_progress', briefing_id=briefing_id, job_id=job_id))
            else:
                # Queue failed (likely full) - inform user
                logger.warning(f"Job queue full or unavailable for briefing {briefing_id}, falling back to synchronous generation")
                flash(_('System is busy. Brief generation may take longer than usual.'), 'warning')
        
        # Fallback to synchronous generation (Redis not available or queue failed)
        logger.info(f"Falling back to synchronous generation for briefing {briefing_id}")
        from app.briefing.generator import BriefingGenerator
        from datetime import timedelta
        import random
        
        generator = BriefingGenerator()
        test_scheduled_at = utcnow_naive() + timedelta(microseconds=random.randint(1, 999999))
        
        brief_run = generator.generate_brief_run(
            briefing=briefing,
            scheduled_at=test_scheduled_at,
            ingested_items=None
        )
        
        if brief_run is None:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': _('No content available from your sources.')}), 400
            flash(_('No content available from your sources. Try adding more sources or wait for content to be ingested.'), 'warning')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        brief_run.status = 'generated_draft'
        db.session.commit()
        
        record_generation(current_user.id)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'status': 'completed',
                'redirect_url': url_for('briefing.view_run', briefing_id=briefing_id, run_id=brief_run.id)
            })
        flash(_('Test brief generated successfully!'), 'success')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=brief_run.id))
        
    except Exception as e:
        logger.error(f"Error generating test brief: {e}", exc_info=True)
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': str(e)}), 500
        flash(f'Error generating brief: {str(e)}', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/generation-status/<job_id>', methods=['GET'])
@login_required
def generation_status(briefing_id, job_id):
    """Check status of a generation job (for polling)"""
    from app.briefing.jobs import GenerationJob
    
    job = GenerationJob.get(job_id)
    if not job:
        return jsonify({'error': _('Job not found'), 'status': 'failed'}), 404
    
    # Verify this job belongs to the user AND briefing (security check)
    if job.briefing_id != briefing_id or job.user_id != current_user.id:
        return jsonify({'error': _('Job not found'), 'status': 'failed'}), 404
    
    response = {
        'status': job.status,
        'message': job.progress_message,
        'job_id': job.job_id
    }
    
    if job.status == 'completed' and job.brief_run_id:
        response['redirect_url'] = url_for('briefing.view_run', briefing_id=briefing_id, run_id=job.brief_run_id)
    elif job.status == 'failed':
        response['error'] = job.error
    
    return jsonify(response)


@briefing_bp.route('/<int:briefing_id>/generation-progress/<job_id>')
@login_required
def generation_progress(briefing_id, job_id):
    """Show progress page for generation job (fallback for non-JS)"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions
    is_allowed, redirect_response = check_briefing_permission(
        briefing, 
        error_message='You do not have permission to view this briefing',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    from app.briefing.jobs import GenerationJob
    job = GenerationJob.get(job_id)
    
    # If job completed, redirect to result
    if job and job.status == 'completed' and job.brief_run_id:
        flash(_('Brief generated successfully!'), 'success')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=job.brief_run_id))
    
    # If job failed, redirect back with error
    if job and job.status == 'failed':
        flash(_('Generation failed: %(error)s', error=job.error), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    return render_template(
        'briefing/generation_progress.html',
        briefing=briefing,
        job_id=job_id,
        status_url=url_for('briefing.generation_status', briefing_id=briefing_id, job_id=job_id)
    )


@briefing_bp.route('/<int:briefing_id>/test-send', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def test_send(briefing_id):
    """Send test email to user's email"""
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to send test emails',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    email_value = request.form.get('email') or current_user.email or ''
    test_email = email_value.strip().lower()
    
    # Validate email
    if not test_email:
        flash(_('Email is required'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    is_valid, error = validate_email(test_email)
    if not is_valid:
        flash(error, 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Prevent duplicate sends within 30 seconds (backend protection against double-clicks)
    try:
        from app.briefing.jobs import get_redis_client
        redis_client = get_redis_client()
        if redis_client:
            dedup_key = f"test_email_dedup:{briefing_id}:{current_user.id}"
            if redis_client.get(dedup_key):
                flash(_('Test email already sent. Please wait a moment before sending again.'), 'warning')
                return redirect(url_for('briefing.detail', briefing_id=briefing_id))
            # Set lock for 30 seconds
            redis_client.setex(dedup_key, 30, "1")
    except Exception as e:
        logger.warning(f"Redis dedup check failed: {e}")
        # Continue anyway - better to send than block due to Redis issues
    
    # Get most recent run
    recent_run = briefing.runs.order_by(BriefRun.generated_at.desc()).first()
    
    if not recent_run:
        flash(_('No brief runs available. Generate a test brief first.'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Check if run has content (len() works for both InstrumentedList and eager-loaded lists)
    if not len(recent_run.items):
        flash(_('The brief run has no content. Generate a new test brief.'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Check if run is ready to send (has draft or approved content)
    if not recent_run.draft_html and not recent_run.approved_html:
        flash(_('The brief run has no content. Generate a new test brief.'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    try:
        from app.briefing.email_client import BriefingEmailClient
        
        # Create temporary recipient for test
        test_recipient = BriefRecipient.query.filter_by(
            briefing_id=briefing_id,
            email=test_email
        ).first()
        
        if not test_recipient:
            test_recipient = BriefRecipient(
                briefing_id=briefing_id,
                email=test_email,
                name='Test Recipient',
                status='active'
            )
            test_recipient.generate_magic_token()
            db.session.add(test_recipient)
            db.session.commit()
        
        # Send test email (NOTE: parameters are brief_run, recipient - not reversed!)
        email_client = BriefingEmailClient()
        success = email_client.send_brief_run(recent_run, test_recipient)
        
        if success:
            flash(_('Test email sent to %(test_email)s', test_email=test_email), 'success')
        else:
            flash(_('Failed to send test email. Check logs.'), 'error')
            
    except Exception as e:
        logger.error(f"Error sending test email: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Error sending test email: {str(e)}', 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/duplicate', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def duplicate_briefing(briefing_id):
    """Duplicate a briefing with all its sources and recipients"""
    briefing = (
        Briefing.query.options(
            selectinload(Briefing.sources).joinedload(BriefingSource.source)
        )
        .filter_by(id=briefing_id)
        .first_or_404()
    )
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to duplicate this briefing',
        redirect_to='list'
    )
    if not is_allowed:
        return redirect_response
    
    try:
        # Create new briefing
        new_briefing = Briefing(
            owner_type=briefing.owner_type,
            owner_id=briefing.owner_id,
            name=f"{briefing.name} (Copy)",
            description=briefing.description,
            theme_template_id=briefing.theme_template_id,
            cadence=briefing.cadence,
            timezone=briefing.timezone,
            preferred_send_hour=briefing.preferred_send_hour,
            preferred_send_minute=getattr(briefing, 'preferred_send_minute', 0),
            mode=briefing.mode,
            visibility='private',  # Default to private for copies
            status='active'
        )
        db.session.add(new_briefing)
        db.session.flush()  # Get new_briefing.id
        
        # Copy sources (handle case where briefing has no sources)
        sources_copied = 0
        for briefing_source in briefing.sources:
            # Verify source still exists
            source = briefing_source.source
            if source and can_access_source(current_user, source):
                new_source = BriefingSource(
                    briefing_id=new_briefing.id,
                    source_id=briefing_source.source_id
                )
                db.session.add(new_source)
                sources_copied += 1
        
        # Copy recipients (optional - user might not want this)
        # Uncomment if you want to copy recipients:
        # for recipient in briefing.recipients.filter_by(status='active').all():
        #     new_recipient = BriefRecipient(
        #         briefing_id=new_briefing.id,
        #         email=recipient.email,
        #         name=recipient.name,
        #         status='active'
        #     )
        #     new_recipient.generate_magic_token()
        #     db.session.add(new_recipient)
        
        db.session.commit()
        
        msg = f'Briefing duplicated successfully!'
        if sources_copied > 0:
            msg += f' {sources_copied} source(s) copied.'
        flash(msg, 'success')
        return redirect(url_for('briefing.detail', briefing_id=new_briefing.id))
        
    except Exception as e:
        logger.error(f"Error duplicating briefing: {e}", exc_info=True)
        db.session.rollback()
        flash(_('An error occurred while duplicating the briefing'), 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))


# =============================================================================
# Source Browser Route
# =============================================================================

@briefing_bp.route('/sources/browse')
@login_required
@limiter.limit("60/minute")
def browse_sources():
    """Browse and search available sources"""
    search_query = request.args.get('q', '').strip()
    source_type = request.args.get('type', '').strip()
    briefing_id = request.args.get('briefing_id', type=int)
    
    # Get briefing if provided
    briefing = None
    added_source_ids = set()
    if briefing_id:
        briefing = db.session.get(Briefing,briefing_id)
        if briefing:
            if can_access_briefing(current_user, briefing):
                added_source_ids = {bs.source_id for bs in briefing.sources}
            else:
                # User doesn't have access - ignore briefing_id
                briefing = None
                briefing_id = None
    
    # Get all available sources
    all_sources = get_available_sources_for_user(current_user, exclude_source_ids=added_source_ids)
    
    # Filter by search query
    if search_query:
        all_sources = [
            s for s in all_sources
            if search_query.lower() in s['name'].lower()
        ]
    
    # Filter by type
    if source_type:
        all_sources = [
            s for s in all_sources
            if s['type'] == source_type
        ]
    
    # Group sources
    system_sources = [s for s in all_sources if s.get('is_system')]
    user_sources = [s for s in all_sources if not s.get('is_system')]
    
    # Get source types for filter
    source_types = list(set(s['type'] for s in all_sources))
    source_types.sort()
    
    return render_template(
        'briefing/browse_sources.html',
        system_sources=system_sources,
        user_sources=user_sources,
        search_query=search_query,
        source_type=source_type,
        source_types=source_types,
        briefing=briefing,
        briefing_id=briefing_id
    )


# =============================================================================
# Analytics Tracking Routes (Open Pixel & Click Tracking)
# =============================================================================

@briefing_bp.route("/track/open/<int:run_id>.gif")
def track_open(run_id):
    """
    Track email opens via 1x1 transparent GIF pixel.
    Returns a transparent GIF image.
    """
    import base64
    import hashlib
    
    try:
        # Get brief run
        brief_run = db.session.get(BriefRun,run_id)
        if brief_run:
            # Get recipient hash or generate one from IP+UA for deduplication
            recipient_hash = request.args.get("r", "")
            if not recipient_hash:
                # Generate a fingerprint for deduplication when no hash provided
                fingerprint = f"{run_id}:{request.remote_addr}:{request.headers.get('User-Agent', '')}"
                recipient_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
            
            # Check if this is a unique open (dedup by recipient hash per run)
            existing_open = BriefEmailOpen.query.filter_by(
                brief_run_id=run_id,
                recipient_email=recipient_hash
            ).first()
            
            # Log the open (always log for audit trail)
            open_record = BriefEmailOpen(
                brief_run_id=run_id,
                recipient_email=recipient_hash,
                user_agent=request.headers.get("User-Agent", "")[:500],
                ip_address=request.remote_addr
            )
            db.session.add(open_record)
            
            # Update aggregates only for truly unique opens
            if not existing_open:
                brief_run.unique_opens = (brief_run.unique_opens or 0) + 1
            
            db.session.commit()
            logger.debug(f"Tracked email open for brief_run {run_id}")
    except Exception as e:
        logger.warning(f"Error tracking email open for run {run_id}: {e}")
        db.session.rollback()
    
    # Return 1x1 transparent GIF
    gif_data = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
    from flask import Response
    return Response(gif_data, mimetype="image/gif")


@briefing_bp.route("/track/click/<int:run_id>")
def track_click(run_id):
    """
    Track link clicks and redirect to the target URL.

    Security: each tracking URL carries an HMAC-SHA256 signature derived
    from the app SECRET_KEY, the run_id, and the exact target URL.  The
    signature is verified here before any redirect, preventing open-redirect
    abuse without needing a hardcoded domain allow-list (which would block
    internal links such as reader pages, discussion threads, etc.).
    """
    from urllib.parse import urlparse
    from app.briefing.link_tracker import verify_url as _verify_url

    target_url = request.args.get("url", "")
    signature = request.args.get("sig", "")
    r_hash = request.args.get("r", "")
    link_type = request.args.get("t", "article")

    if not target_url:
        return redirect("/")

    # Basic URL format check
    try:
        parsed = urlparse(target_url)
        if parsed.scheme not in ('http', 'https'):
            logger.warning(f"Invalid URL scheme in click tracking: {target_url[:100]}")
            return redirect("/")
    except Exception:
        logger.warning(f"Malformed URL in click tracking: {target_url[:100]}")
        return redirect("/")

    # HMAC verification — reject any URL that wasn't signed by us at send time
    secret = current_app.config.get('SECRET_KEY', '')
    if not _verify_url(run_id, target_url, signature, secret):
        logger.warning(f"Invalid click-tracking signature for run {run_id}: {target_url[:100]}")
        return redirect("/")

    # Record the click (best-effort — never block the redirect on DB errors)
    try:
        click_record = BriefLinkClick(
            brief_run_id=run_id,
            recipient_email=r_hash or None,
            target_url=target_url[:2000],
            link_type=link_type[:50] if link_type else None,
            user_agent=request.headers.get("User-Agent", "")[:500],
        )
        db.session.add(click_record)

        brief_run = db.session.get(BriefRun, run_id)
        if brief_run:
            brief_run.total_clicks = (brief_run.total_clicks or 0) + 1

        db.session.commit()
        logger.debug(f"Tracked click for brief_run {run_id} -> {target_url[:60]}")
    except Exception as e:
        logger.warning(f"Error recording click for run {run_id}: {e}")
        db.session.rollback()

    return redirect(target_url)


@briefing_bp.route("/<int:briefing_id>/analytics")
@login_required
@limiter.limit("30/minute")
def analytics(briefing_id):
    """
    View analytics dashboard for a briefing.
    Shows open rates, click rates, and trends over time.
    """
    briefing = db.get_or_404(Briefing, briefing_id)
    
    # Check access
    if not can_access_briefing(current_user, briefing):
        flash(_("You do not have permission to view this briefing"), "error")
        return redirect(url_for("briefing.list_briefings"))
    
    # Get recent runs with analytics
    runs = BriefRun.query.filter_by(
        briefing_id=briefing_id,
        status="sent"
    ).order_by(BriefRun.sent_at.desc()).limit(30).all()
    
    # Calculate aggregate stats (BriefRun: no per-message delivered events; use sent cohort).
    total_sent = sum(r.emails_sent or 0 for r in runs)
    total_opens = sum(r.unique_opens or 0 for r in runs)
    total_clicks = sum(r.total_clicks or 0 for r in runs)

    _rates = EmailEvent.compute_rate_metrics(
        total_sent,
        0,
        total_opens,
        total_clicks,
        0,
        0,
        engagement_basis="sent",
    )
    open_rate = _rates.get("open_rate")
    click_rate = _rates.get("click_rate")
    click_to_open_rate = _rates.get("click_to_open_rate")
    
    # Prepare chart data — compute per-row rates via the shared helper so the
    # sent-basis definition stays in one place.
    chart_data = []
    for run in reversed(runs):
        run_sent = run.emails_sent or 0
        run_opens = run.unique_opens or 0
        run_clicks = run.total_clicks or 0
        row_rates = EmailEvent.compute_rate_metrics(
            run_sent, 0, run_opens, run_clicks, 0, 0,
            engagement_basis="sent",
        )
        chart_data.append({
            "date": run.sent_at.strftime("%b %d") if run.sent_at else "N/A",
            "sent": run_sent,
            "opens": run_opens,
            "clicks": run_clicks,
            "open_rate": row_rates.get("open_rate"),
        })
    
    return render_template(
        "briefing/analytics.html",
        briefing=briefing,
        runs=runs,
        total_sent=total_sent,
        total_opens=total_opens,
        total_clicks=total_clicks,
        open_rate=open_rate,
        click_rate=click_rate,
        click_to_open_rate=click_to_open_rate,
        chart_data=chart_data
    )


@briefing_bp.route("/organization")
@login_required
def organization_settings():
    """
    Organization settings page for Team/Enterprise subscribers.
    Allows viewing organization details and managing team.
    """
    sub = get_active_subscription(current_user)

    if not sub or not sub.plan or not sub.plan.is_organisation:
        flash(_("Organization settings are only available for Team and Enterprise plans."), "info")
        return redirect(url_for("briefing.list_briefings"))

    org = current_user.company_profile
    if not org:
        org = CompanyProfile.query.filter_by(user_id=current_user.id).first()

    # Also check if user is a member of an org (not just owner)
    if not org:
        membership = OrganizationMember.query.filter_by(
            user_id=current_user.id,
            status='active'
        ).first()
        if membership:
            org = membership.org

    if not org:
        flash(_("No organization found. Please contact support."), "error")
        return redirect(url_for("briefing.list_briefings"))

    # Get team members using the proper function
    team_members = get_team_members(org)

    # Check seat limits
    can_add_member, current_seats, max_seats = check_team_seat_limit(org)

    # Check if current user is admin/owner
    user_membership = OrganizationMember.query.filter_by(
        org_id=org.id,
        user_id=current_user.id,
        status='active'
    ).first()
    is_admin = (user_membership and user_membership.is_admin) or (org.user_id == current_user.id)

    subscription_context = get_subscription_context(current_user)

    return render_template(
        "briefing/organization_settings.html",
        org=org,
        team_members=team_members,
        subscription=sub,
        plan=sub.plan,
        can_add_member=can_add_member,
        current_seats=current_seats,
        max_seats=max_seats,
        is_admin=is_admin,
        **subscription_context
    )


@briefing_bp.route("/organization/update", methods=["POST"])
@login_required
def update_organization():
    """Update organization details."""
    sub = get_active_subscription(current_user)
    
    if not sub or not sub.plan or not sub.plan.is_organisation:
        flash(_("Organization settings are only available for Team and Enterprise plans."), "error")
        return redirect(url_for("briefing.list_briefings"))
    
    org = current_user.company_profile
    if not org or org.user_id != current_user.id:
        flash(_("You don't have permission to edit this organization."), "error")
        return redirect(url_for("briefing.organization_settings"))
    
    org_name = request.form.get("company_name", "").strip()
    if org_name and len(org_name) >= 2:
        org.company_name = org_name
    
    org.description = request.form.get("description", "").strip()
    org.website = request.form.get("website", "").strip()
    
    db.session.commit()
    flash(_("Organization details updated successfully."), "success")
    return redirect(url_for("briefing.organization_settings"))


@briefing_bp.route("/organization/invite", methods=["POST"])
@login_required
def invite_member():
    """Invite a new member to the organization."""
    sub = get_active_subscription(current_user)

    if not sub or not sub.plan or not sub.plan.is_organisation:
        flash(_("Team management is only available for Team and Enterprise plans."), "error")
        return redirect(url_for("briefing.list_briefings"))

    org = current_user.company_profile
    if not org:
        org = CompanyProfile.query.filter_by(user_id=current_user.id).first()

    if not org:
        flash(_("No organization found."), "error")
        return redirect(url_for("briefing.list_briefings"))

    # Check if user has permission to invite (owner or admin)
    membership = OrganizationMember.query.filter_by(
        org_id=org.id,
        user_id=current_user.id,
        status='active'
    ).first()

    is_owner = org.user_id == current_user.id
    is_admin = membership and membership.is_admin

    if not is_owner and not is_admin:
        flash(_("You don't have permission to invite team members."), "error")
        return redirect(url_for("briefing.organization_settings"))

    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "editor")

    if not email or not validate_email(email):
        flash(_("Please enter a valid email address."), "error")
        return redirect(url_for("briefing.organization_settings"))

    try:
        membership = invite_team_member(org, email, role, current_user)
        invite_url = url_for('auth.handle_invitation', token=membership.invite_token, _external=True)
        try:
            from app.resend_client import send_org_invitation_email
            send_org_invitation_email(
                email=email,
                org_name=org.company_name,
                inviter_name=current_user.username,
                invite_url=invite_url,
                role=role,
            )
        except Exception as e:
            logger.warning(f"Invitation email failed for {email}: {e}")
        _track_posthog('organization_invite_sent', current_user.id, {
            'org_id': org.id,
            'org_name': org.company_name,
            'invitee_email': email,
            'role': role,
        })
        flash(_('Invitation sent to %(email)s.', email=email), "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("briefing.organization_settings"))


@briefing_bp.route("/organization/member/<int:member_id>/remove", methods=["POST"])
@login_required
def remove_member(member_id):
    """Remove a member from the organization."""
    sub = get_active_subscription(current_user)

    if not sub or not sub.plan or not sub.plan.is_organisation:
        flash(_("Team management is only available for Team and Enterprise plans."), "error")
        return redirect(url_for("briefing.list_briefings"))

    org = current_user.company_profile
    if not org:
        org = CompanyProfile.query.filter_by(user_id=current_user.id).first()

    if not org:
        flash(_("No organization found."), "error")
        return redirect(url_for("briefing.list_briefings"))

    try:
        remove_team_member(org, member_id, current_user)
        flash(_("Team member removed successfully."), "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("briefing.organization_settings"))


@briefing_bp.route("/organization/member/<int:member_id>/role", methods=["POST"])
@login_required
def change_member_role(member_id):
    """Change a member's role in the organization."""
    sub = get_active_subscription(current_user)

    if not sub or not sub.plan or not sub.plan.is_organisation:
        flash(_("Team management is only available for Team and Enterprise plans."), "error")
        return redirect(url_for("briefing.list_briefings"))

    org = current_user.company_profile
    if not org:
        org = CompanyProfile.query.filter_by(user_id=current_user.id).first()

    if not org:
        flash(_("No organization found."), "error")
        return redirect(url_for("briefing.list_briefings"))

    new_role = request.form.get("role", "editor")

    try:
        update_member_role(org, member_id, new_role, current_user)
        flash(_("Member role updated successfully."), "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("briefing.organization_settings"))


@briefing_bp.route("/join/<token>")
@login_required
def join_organization(token):
    """Accept an organization invitation."""
    try:
        membership = accept_invitation(token, current_user)
        org = membership.org
        flash(_("Welcome to %(company_name)s! You now have access to the team's briefings.", company_name=org.company_name), "success")
        return redirect(url_for("briefing.list_briefings"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("briefing.list_briefings"))

