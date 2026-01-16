"""
Briefing Routes

CRUD routes for multi-tenant briefing system.
"""

from functools import wraps
from flask import render_template, redirect, url_for, flash, request, jsonify, g
from flask_login import login_required, current_user
from datetime import datetime
from app.briefing import briefing_bp
from app.briefing.validators import (
    validate_email, validate_briefing_name, validate_rss_url,
    validate_file_upload, validate_timezone, validate_cadence,
    validate_visibility, validate_mode, validate_send_hour, validate_send_minute
)
from app import db, limiter
from app.models import (
    Briefing, BriefRun, BriefRunItem, BriefTemplate, InputSource, IngestedItem,
    BriefingSource, BriefRecipient, SendingDomain, User, CompanyProfile, NewsSource
)
import logging

logger = logging.getLogger(__name__)


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
    news_source = NewsSource.query.get_or_404(news_source_id)
    
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
        config_json={'feed_url': news_source.feed_url},
        enabled=news_source.is_active,
        status='ready',
        last_fetched_at=news_source.last_fetched_at
    )
    
    db.session.add(input_source)
    db.session.commit()
    
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
    if briefing.owner_type == 'user':
        return briefing.owner_id == user.id
    elif briefing.owner_type == 'org':
        return user.company_profile and briefing.owner_id == user.company_profile.id
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
    if source.owner_type == 'system':
        return True  # System sources are accessible to all
    elif source.owner_type == 'user':
        return source.owner_id == user.id
    elif source.owner_type == 'org':
        return user.company_profile and source.owner_id == user.company_profile.id
    return False


def briefing_owner_required(f):
    """
    Decorator that checks if current user owns the briefing.
    Expects briefing_id as the first URL parameter.
    Stores the briefing in g.briefing for use in the view.
    """
    @wraps(f)
    def decorated_function(briefing_id, *args, **kwargs):
        briefing = Briefing.query.get_or_404(briefing_id)
        if not can_access_briefing(current_user, briefing):
            flash('You do not have permission to access this briefing', 'error')
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
        source = InputSource.query.get_or_404(source_id)
        if not can_access_source(current_user, source):
            flash('You do not have access to this source', 'error')
            return redirect(url_for('briefing.list_sources'))
        g.source = source
        return f(*args, source_id=source_id, **kwargs)
    return decorated_function


@briefing_bp.route('/landing')
@limiter.limit("60/minute")
def landing():
    """Public landing page for Briefing System - marketing/sales page"""
    return render_template('briefing/landing.html')


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

    # Get org briefings if user has company profile
    org_briefings = []
    if current_user.company_profile:
        org_briefings = Briefing.query.filter_by(
            owner_type='org',
            owner_id=current_user.company_profile.id
        ).order_by(Briefing.created_at.desc()).all()

    return render_template(
        'briefing/list.html',
        user_briefings=user_briefings,
        org_briefings=org_briefings
    )


@briefing_bp.route('/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def create_briefing():
    """Create a new briefing"""
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
                if not current_user.company_profile:
                    flash('You need a company profile to create org briefings', 'error')
                    return redirect(url_for('briefing.create_briefing'))
                owner_id = current_user.company_profile.id

            # Get branding fields (for org briefings)
            from_name = request.form.get('from_name', '').strip() or None
            from_email = request.form.get('from_email', '').strip().lower() or None
            sending_domain_id = request.form.get('sending_domain_id', type=int) or None
            
            # Validate from_email if domain is selected (email is required)
            if sending_domain_id:
                if not from_email:
                    flash('Email address is required when a sending domain is selected', 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                domain = SendingDomain.query.get(sending_domain_id)
                if not domain:
                    flash('Selected domain not found', 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                if domain.status != 'verified':
                    flash('Selected domain is not verified. Please verify it first.', 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                # Validate email format
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.create_briefing'))
                
                # Validate email matches domain
                domain_name = domain.domain
                if not from_email.endswith(f'@{domain_name}'):
                    flash(f'Email must be from verified domain: {domain_name}', 'error')
                    return redirect(url_for('briefing.create_briefing'))
            elif from_email:
                # Email provided but no domain - validate format only
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.create_briefing'))
            
            # Create briefing
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
                sending_domain_id=sending_domain_id if owner_type == 'org' else None
            )

            db.session.add(briefing)
            db.session.flush()  # Get briefing.id
            
            # Auto-populate sources from template if selected
            sources_added = 0
            sources_failed = 0
            if template_id:
                template = BriefTemplate.query.get(template_id)
                if template and template.default_sources:
                    # default_sources can be NewsSource IDs or InputSource IDs
                    # Handle empty list gracefully
                    if isinstance(template.default_sources, list) and len(template.default_sources) > 0:
                        for source_ref in template.default_sources:
                            try:
                                source = None
                                
                                # Try as InputSource ID first
                                if isinstance(source_ref, int):
                                    source = InputSource.query.get(source_ref)
                                
                                # Try as NewsSource ID (convert to InputSource)
                                if not source and isinstance(source_ref, int):
                                    news_source = NewsSource.query.get(source_ref)
                                    if news_source:
                                        source = create_input_source_from_news_source(news_source.id, current_user)
                                
                                # Try as string (NewsSource name)
                                if not source and isinstance(source_ref, str):
                                    news_source = NewsSource.query.filter_by(name=source_ref).first()
                                    if news_source:
                                        source = create_input_source_from_news_source(news_source.id, current_user)
                                
                                if source and can_access_source(current_user, source):
                                    # Check if already added (shouldn't be, but safety check)
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
                                continue  # Continue with other sources

            db.session.commit()
            
            if sources_added > 0:
                msg = f'Briefing "{name}" created successfully with {sources_added} sources from template!'
                if sources_failed > 0:
                    msg += f' ({sources_failed} sources could not be added)'
                flash(msg, 'success')
            else:
                if sources_failed > 0:
                    flash(f'Briefing "{name}" created successfully, but {sources_failed} sources from template could not be added.', 'warning')
                else:
                    flash(f'Briefing "{name}" created successfully!', 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing.id))

        except Exception as e:
            logger.error(f"Error creating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while creating the briefing', 'error')
            return redirect(url_for('briefing.create_briefing'))

    # GET: Show create form
    templates = BriefTemplate.query.filter_by(allow_customization=True).all()
    has_company_profile = current_user.company_profile is not None
    
    # Get available sending domains for org briefings
    available_domains = []
    if has_company_profile:
        available_domains = SendingDomain.query.filter_by(
            org_id=current_user.company_profile.id
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
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing,
        error_message='You do not have permission to view this briefing',
        redirect_to='list'
    )
    if not is_allowed:
        return redirect_response

    # Get related data
    sources = [bs.input_source for bs in briefing.sources]
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
    briefing = Briefing.query.get_or_404(briefing_id)

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
                flash("Status must be 'active' or 'paused'", 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            # Get branding fields (for org briefings)
            from_name = request.form.get('from_name', '').strip() or None
            from_email = request.form.get('from_email', '').strip().lower() or None
            sending_domain_id = request.form.get('sending_domain_id', type=int) or None
            
            # Validate from_email if domain is selected (email is required)
            if sending_domain_id:
                if not from_email:
                    flash('Email address is required when a sending domain is selected', 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                domain = SendingDomain.query.get(sending_domain_id)
                if not domain:
                    flash('Selected domain not found', 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                if domain.status != 'verified':
                    flash('Selected domain is not verified. Please verify it first.', 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                # Validate email format
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
                
                # Validate email matches domain
                domain_name = domain.domain
                if not from_email.endswith(f'@{domain_name}'):
                    flash(f'Email must be from verified domain: {domain_name}', 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
            elif from_email:
                # Email provided but no domain - validate format only
                is_valid, error = validate_email(from_email)
                if not is_valid:
                    flash(error, 'error')
                    return redirect(url_for('briefing.edit', briefing_id=briefing_id))
            
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
            
            # Update branding (only for org briefings)
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
            flash('Briefing updated successfully', 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        except Exception as e:
            logger.error(f"Error updating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while updating the briefing', 'error')
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
    briefing = Briefing.query.get_or_404(briefing_id)

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
        flash(f'Briefing "{name}" deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting briefing: {e}", exc_info=True)
        db.session.rollback()
        flash('An error occurred while deleting the briefing', 'error')

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
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check permissions (DRY) - API endpoint returns JSON
    if not can_access_briefing(current_user, briefing):
        return jsonify({'error': 'Permission denied'}), 403

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
    
    # Get org sources if user has company profile
    org_sources = []
    if current_user.company_profile:
        org_sources = InputSource.query.filter_by(
            owner_type='org',
            owner_id=current_user.company_profile.id
        ).order_by(InputSource.created_at.desc()).all()
    
    return render_template(
        'briefing/sources.html',
        user_sources=user_sources,
        org_sources=org_sources
    )


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
                if not current_user.company_profile:
                    flash('You need a company profile to create org sources', 'error')
                    return redirect(url_for('briefing.add_rss_source'))
                owner_id = current_user.company_profile.id
            
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
            
            flash(f'RSS source "{name}" added successfully', 'success')
            return redirect(url_for('briefing.list_sources'))
            
        except Exception as e:
            logger.error(f"Error adding RSS source: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while adding the source', 'error')
    
    return render_template('briefing/add_rss_source.html')


@briefing_bp.route('/sources/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit("5/minute")
def upload_source():
    """Upload PDF/DOCX file as source"""
    if request.method == 'POST':
        try:
            from replit.object_storage import Client
            from werkzeug.utils import secure_filename
            import secrets
            import hashlib
            
            if 'file' not in request.files:
                flash('No file provided', 'error')
                return redirect(url_for('briefing.upload_source'))
            
            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(url_for('briefing.upload_source'))
            
            # Validate file
            filename = secure_filename(file.filename or '')
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset
            
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
            
            # Get public URL (if available)
            storage_url = f"https://replitstorage.com/{storage_key}"  # Adjust based on actual URL pattern
            
            # Create InputSource with status='extracting'
            source = InputSource(
                owner_type='user',
                owner_id=current_user.id,
                name=filename.rsplit('.', 1)[0],  # Name without extension
                type='upload',
                storage_key=storage_key,
                storage_url=storage_url,
                status='extracting',  # Will be processed by background job
                enabled=True
            )
            
            db.session.add(source)
            db.session.commit()
            
            flash(f'File uploaded successfully. Text extraction in progress...', 'success')
            return redirect(url_for('briefing.list_sources'))
            
        except Exception as e:
            logger.error(f"Error uploading source: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while uploading the file', 'error')
    
    return render_template('briefing/upload_source.html')


@briefing_bp.route('/<int:briefing_id>/sources/add', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def add_source_to_briefing(briefing_id):
    """Add a source to a briefing"""
    briefing = Briefing.query.get_or_404(briefing_id)
    
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
            flash('Source ID is required', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Handle NewsSource (prefixed with 'news_')
        source = None
        if source_id_str.startswith('news_'):
            news_source_id = int(source_id_str.replace('news_', ''))
            # Create InputSource from NewsSource
            source = create_input_source_from_news_source(news_source_id, current_user)
        else:
            source_id = int(source_id_str)
            source = InputSource.query.get(source_id)
            if not source:
                flash('Source not found', 'error')
                return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check ownership (system sources are accessible to all)
        if source.owner_type == 'system':
            pass  # System sources are accessible to all
        elif source.owner_type == 'user' and source.owner_id != current_user.id:
            flash('You do not have access to this source', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        elif source.owner_type == 'org':
            if not current_user.company_profile or source.owner_id != current_user.company_profile.id:
                flash('You do not have access to this source', 'error')
                return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check if source is ready (not extracting or failed)
        if source.status == 'extracting':
            flash('Source is still being processed. Please wait.', 'info')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        if source.status == 'failed':
            flash('Source processing failed. Please check the source and try again.', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        # Check source limit before adding
        current_source_count = len(briefing.sources)
        if current_source_count >= MAX_SOURCES_PER_BRIEFING:
            flash(f'Maximum sources ({MAX_SOURCES_PER_BRIEFING}) reached for this briefing', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        # Check if already added
        existing = BriefingSource.query.filter_by(
            briefing_id=briefing_id,
            source_id=source.id
        ).first()
        
        if existing:
            flash('Source already added to this briefing', 'info')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Add source
        briefing_source = BriefingSource(
            briefing_id=briefing_id,
            source_id=source.id
        )
        db.session.add(briefing_source)
        db.session.commit()
        
        flash(f'Source "{source.name}" added to briefing', 'success')
        
    except Exception as e:
        logger.error(f"Error adding source to briefing: {e}", exc_info=True)
        db.session.rollback()
        flash('An error occurred while adding the source', 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/sources/<int:source_id>/remove', methods=['POST'])
@login_required
@limiter.limit("10/minute")
def remove_source_from_briefing(briefing_id, source_id):
    """Remove a source from a briefing"""
    briefing = Briefing.query.get_or_404(briefing_id)
    
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
        
        flash('Source removed from briefing', 'success')
        
    except Exception as e:
        logger.error(f"Error removing source from briefing: {e}", exc_info=True)
        db.session.rollback()
        flash('An error occurred', 'error')
    
    return redirect(url_for('briefing.detail', briefing_id=briefing_id))


# =============================================================================
# Recipient Management Routes
# =============================================================================

@briefing_bp.route('/<int:briefing_id>/recipients', methods=['GET', 'POST'])
@login_required
@limiter.limit("30/minute")
def manage_recipients(briefing_id):
    """Manage recipients for a briefing"""
    briefing = Briefing.query.get_or_404(briefing_id)
    
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
                    flash('Email is required', 'error')
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
                        flash(f'Recipient {email} reactivated', 'success')
                    else:
                        flash('Recipient already exists', 'info')
                else:
                    # Check recipient limit before adding
                    current_count = BriefRecipient.query.filter_by(
                        briefing_id=briefing_id,
                        status='active'
                    ).count()

                    if current_count >= MAX_RECIPIENTS_PER_BRIEFING:
                        flash(f'Maximum recipients ({MAX_RECIPIENTS_PER_BRIEFING}) reached for this briefing', 'error')
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
                    flash(f'Recipient {email} added successfully', 'success')

            elif action == 'bulk_add':
                emails_text = request.form.get('emails', '')
                import re
                
                # Parse emails (handle comma, newline, space, semicolon separators)
                emails = re.split(r'[,\n\s;]+', emails_text)
                emails = [e.strip().lower() for e in emails if e.strip() and '@' in e]
                
                if not emails:
                    flash('No valid email addresses found.', 'error')
                    return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))
                
                added = 0
                skipped = 0
                current_count = BriefRecipient.query.filter_by(
                    briefing_id=briefing_id,
                    status='active'
                ).count()
                
                for email in emails:
                    # Check limit
                    if current_count >= MAX_RECIPIENTS_PER_BRIEFING:
                        flash(f'Maximum recipients ({MAX_RECIPIENTS_PER_BRIEFING}) reached. {len(emails) - added - skipped} emails not added.', 'warning')
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
                            current_count += 1
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
                        current_count += 1
                
                db.session.commit()
                flash(f'Imported {added} recipients. {skipped} skipped (already exists or invalid).', 'success')
                
            elif action == 'bulk_remove':
                recipient_ids = request.form.getlist('recipient_ids')
                if recipient_ids:
                    count = BriefRecipient.query.filter(
                        BriefRecipient.id.in_([int(rid) for rid in recipient_ids]),
                        BriefRecipient.briefing_id == briefing_id
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    flash(f'{count} recipient(s) removed', 'success')
                else:
                    flash('No recipients selected', 'info')
                    
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
                            flash(f'{recipient.email} has been paused.', 'success')
                        elif recipient.status in ('paused', 'unsubscribed'):
                            recipient.status = 'active'
                            if recipient.status == 'unsubscribed':
                                recipient.unsubscribed_at = None
                                recipient.generate_magic_token()
                            flash(f'{recipient.email} has been activated.', 'success')
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
                        flash('Recipient removed', 'success')

            return redirect(url_for('briefing.manage_recipients', briefing_id=briefing_id))

        except Exception as e:
            logger.error(f"Error managing recipients: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred', 'error')
    
    # GET: Show recipients
    recipients = briefing.recipients.order_by(BriefRecipient.created_at.desc()).all()
    return render_template('briefing/recipients.html', briefing=briefing, recipients=recipients)


@briefing_bp.route('/<int:briefing_id>/unsubscribe/<token>')
@limiter.limit("60/minute")
def unsubscribe(briefing_id, token):
    """
    Unsubscribe recipient from briefing.

    Note: We intentionally do NOT enforce token expiry for unsubscribe.
    CAN-SPAM and GDPR require that unsubscribe links work indefinitely.
    Token expiry is tracked for audit purposes but not enforced here.
    """
    briefing = Briefing.query.get_or_404(briefing_id)

    recipient = BriefRecipient.query.filter_by(
        briefing_id=briefing_id,
        magic_token=token
    ).first()

    if not recipient:
        flash('Invalid unsubscribe link', 'error')
        return redirect(url_for('index'))

    if recipient.status == 'unsubscribed':
        flash('You are already unsubscribed', 'info')
    else:
        recipient.status = 'unsubscribed'
        recipient.unsubscribed_at = datetime.utcnow()
        # Regenerate token to invalidate any other links (security)
        recipient.generate_magic_token(expires_hours=0)  # Immediately expired
        db.session.commit()
        flash('You have been unsubscribed from this briefing', 'success')

    return render_template('briefing/unsubscribed.html', briefing=briefing, recipient=recipient)


# =============================================================================
# BriefRun Management Routes
# =============================================================================

@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>')
@login_required
@limiter.limit("60/minute")
def view_run(briefing_id, run_id):
    """View a BriefRun"""
    briefing = Briefing.query.get_or_404(briefing_id)
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
    
    items = brief_run.items.order_by(BriefRunItem.position).all()
    
    return render_template(
        'briefing/run_view.html',
        briefing=briefing,
        brief_run=brief_run,
        items=items
    )


@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def edit_run(briefing_id, run_id):
    """Edit/approve a BriefRun draft"""
    briefing = Briefing.query.get_or_404(briefing_id)
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
                brief_run.approved_at = datetime.utcnow()
                brief_run.status = 'approved'
                
                db.session.commit()
                
                # Send emails if auto-send or manual send requested
                if briefing.mode == 'auto_send' or request.form.get('send_now') == 'true':
                    from app.briefing.email_client import send_brief_run_emails
                    result = send_brief_run_emails(brief_run.id)
                    flash(f'Brief approved and sent to {result["sent"]} recipients', 'success')
                else:
                    flash('Brief approved (ready to send)', 'success')
                
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
                
                flash('Draft updated', 'success')
                return redirect(url_for('briefing.edit_run', briefing_id=briefing_id, run_id=run_id))
            
        except Exception as e:
            logger.error(f"Error editing BriefRun: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred', 'error')
    
    items = brief_run.items.order_by(BriefRunItem.position).all()
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
    briefing = Briefing.query.get_or_404(briefing_id)
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
        flash('Brief must be approved before sending', 'error')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    try:
        from app.briefing.email_client import send_brief_run_emails
        result = send_brief_run_emails(brief_run.id)
        flash(f'Sent to {result["sent"]} recipients ({result["failed"]} failed)', 'success')
    except Exception as e:
        logger.error(f"Error sending BriefRun: {e}", exc_info=True)
        flash('An error occurred while sending', 'error')
    
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
def list_domains():
    """List sending domains for user's organization"""
    if not current_user.company_profile:
        flash('You need a company profile to manage sending domains', 'error')
        return redirect(url_for('briefing.list_briefings'))

    domains = SendingDomain.query.filter_by(
        org_id=current_user.company_profile.id
    ).order_by(SendingDomain.created_at.desc()).all()

    return render_template('briefing/domains/list.html', domains=domains)


@briefing_bp.route('/domains/add', methods=['GET', 'POST'])
@login_required
@limiter.limit("5/minute")
def add_domain():
    """Add a new sending domain"""
    if not current_user.company_profile:
        flash('You need a company profile to add sending domains', 'error')
        return redirect(url_for('briefing.list_briefings'))

    if request.method == 'POST':
        try:
            domain = request.form.get('domain', '').strip().lower()

            # Validate domain format
            if not domain:
                flash('Domain is required', 'error')
                return redirect(url_for('briefing.add_domain'))

            # Basic domain validation
            import re
            domain_pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z]{2,}$'
            if not re.match(domain_pattern, domain):
                flash('Invalid domain format', 'error')
                return redirect(url_for('briefing.add_domain'))

            # Check if domain already exists
            existing = SendingDomain.query.filter_by(domain=domain).first()
            if existing:
                flash('This domain is already registered', 'error')
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
                flash(f'Domain "{domain}" added. Please configure DNS records.', 'success')
                return redirect(url_for('briefing.verify_domain', domain_id=sending_domain.id))
            else:
                flash(f'Failed to register domain: {result.get("error", "Unknown error")}', 'error')
                return redirect(url_for('briefing.add_domain'))

        except Exception as e:
            logger.error(f"Error adding domain: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while adding the domain', 'error')

    return render_template('briefing/domains/add.html')


@briefing_bp.route('/domains/<int:domain_id>')
@login_required
@limiter.limit("60/minute")
def verify_domain(domain_id):
    """View domain details and verification status"""
    if not current_user.company_profile:
        flash('You need a company profile to manage domains', 'error')
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
        return jsonify({'error': 'Company profile required'}), 403

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    try:
        if not domain.resend_domain_id:
            flash('Domain not yet registered with Resend', 'error')
            return redirect(url_for('briefing.verify_domain', domain_id=domain_id))
        
        from app.briefing.domains import check_domain_verification_status
        result = check_domain_verification_status(domain.resend_domain_id)

        if not result.get('success'):
            flash(f"Error checking verification: {result.get('error', 'Unknown error')}", 'error')
            return redirect(url_for('briefing.verify_domain', domain_id=domain_id))

        if result.get('status') == 'verified':
            domain.status = 'verified'
            domain.verified_at = datetime.utcnow()
            db.session.commit()
            flash('Domain verified successfully!', 'success')
        else:
            domain.status = 'pending_verification'
            db.session.commit()
            flash('Domain not yet verified. Please check DNS records.', 'info')

    except Exception as e:
        logger.error(f"Error checking domain verification: {e}", exc_info=True)
        flash('An error occurred while checking verification', 'error')

    return redirect(url_for('briefing.verify_domain', domain_id=domain_id))


@briefing_bp.route('/domains/<int:domain_id>/status', methods=['GET'])
@login_required
@limiter.limit("30/minute")
def get_domain_status(domain_id):
    """Get domain status as JSON (for AJAX requests)"""
    if not current_user.company_profile:
        return jsonify({'error': 'Company profile required'}), 403

    domain = SendingDomain.query.filter_by(
        id=domain_id,
        org_id=current_user.company_profile.id
    ).first_or_404()

    try:
        if not domain.resend_domain_id:
            return jsonify({
                'success': False,
                'error': 'Domain not yet registered with Resend',
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
            domain.verified_at = datetime.utcnow()
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
        flash('You need a company profile to manage domains', 'error')
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
            flash(f'Cannot delete domain: {active_briefings} active briefing(s) are using it. Please remove the domain from those briefings first.', 'error')
            return redirect(url_for('briefing.list_domains'))

        # Try to remove from Resend first
        if domain.resend_domain_id:
            from app.briefing.domains import delete_domain_from_resend
            result = delete_domain_from_resend(domain.resend_domain_id)
            
            if not result.get('success'):
                # Resend deletion failed - don't delete from DB
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to delete domain from Resend: {error_msg}. Domain kept in database for manual cleanup.', 'error')
                return redirect(url_for('briefing.list_domains'))

        # Resend deletion succeeded (or no resend_domain_id) - safe to delete from DB
        domain_name = domain.domain
        db.session.delete(domain)
        db.session.commit()
        flash(f'Domain "{domain_name}" deleted successfully', 'success')

    except Exception as e:
        logger.error(f"Error deleting domain: {e}", exc_info=True)
        db.session.rollback()
        flash('An error occurred while deleting the domain', 'error')

    return redirect(url_for('briefing.list_domains'))


# =============================================================================
# Public Archive Routes (No login required for public briefs)
# =============================================================================

@briefing_bp.route('/public/<int:briefing_id>')
@limiter.limit("30/minute")  # More restrictive for unauthenticated public endpoint
def public_briefing(briefing_id):
    """View a public briefing's archive"""
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check if briefing is public
    if briefing.visibility != 'public':
        flash('This briefing is not publicly accessible', 'error')
        return redirect(url_for('index'))

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
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check if briefing is public
    if briefing.visibility != 'public':
        flash('This briefing is not publicly accessible', 'error')
        return redirect(url_for('index'))

    brief_run = BriefRun.query.filter_by(
        id=run_id,
        briefing_id=briefing_id,
        status='sent'
    ).first_or_404()

    items = brief_run.items.order_by(BriefRunItem.position).all()

    return render_template(
        'briefing/public/run_view.html',
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
    """Generate a test brief immediately for preview"""
    briefing = Briefing.query.get_or_404(briefing_id)
    
    # Check permissions (DRY)
    is_allowed, redirect_response = check_briefing_permission(
        briefing, 
        error_message='You do not have permission to generate test briefs',
        redirect_to='detail'
    )
    if not is_allowed:
        return redirect_response
    
    # Check if briefing has sources
    if not briefing.sources:
        flash('Please add sources to your briefing before generating a test brief', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    try:
        from app.briefing.generator import BriefingGenerator
        
        # Generate test brief with current timestamp (add microseconds to avoid collisions)
        from datetime import timedelta
        import random
        generator = BriefingGenerator()
        # Add small random offset to avoid duplicate scheduled_at collisions
        test_scheduled_at = datetime.utcnow() + timedelta(microseconds=random.randint(1, 999999))
        
        brief_run = generator.generate_brief_run(
            briefing=briefing,
            scheduled_at=test_scheduled_at,
            ingested_items=None  # Let it select from sources
        )
        
        if brief_run is None:
            flash('No content available from your sources. Try adding more sources or wait for content to be ingested.', 'warning')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Mark as test/draft (override generator's status)
        brief_run.status = 'generated_draft'
        db.session.commit()
        
        flash('Test brief generated successfully!', 'success')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=brief_run.id))
        
    except Exception as e:
        logger.error(f"Error generating test brief: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Error generating test brief: {str(e)}', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))


@briefing_bp.route('/<int:briefing_id>/test-send', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def test_send(briefing_id):
    """Send test email to user's email"""
    briefing = Briefing.query.get_or_404(briefing_id)
    
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
        flash('Email is required', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    is_valid, error = validate_email(test_email)
    if not is_valid:
        flash(error, 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Get most recent run
    recent_run = briefing.runs.order_by(BriefRun.generated_at.desc()).first()
    
    if not recent_run:
        flash('No brief runs available. Generate a test brief first.', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Check if run has content
    if not recent_run.items.count():
        flash('The brief run has no content. Generate a new test brief.', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    # Check if run is ready to send (has draft or approved content)
    if not recent_run.draft_html and not recent_run.approved_html:
        flash('The brief run has no content. Generate a new test brief.', 'error')
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
            flash(f'Test email sent to {test_email}', 'success')
        else:
            flash('Failed to send test email. Check logs.', 'error')
            
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
    briefing = Briefing.query.get_or_404(briefing_id)
    
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
            source = InputSource.query.get(briefing_source.source_id)
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
        flash('An error occurred while duplicating the briefing', 'error')
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
        briefing = Briefing.query.get(briefing_id)
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
