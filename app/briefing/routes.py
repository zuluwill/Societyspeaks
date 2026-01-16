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
    validate_visibility, validate_mode
)
from app import db, limiter
from app.models import (
    Briefing, BriefRun, BriefRunItem, BriefTemplate, InputSource, IngestedItem,
    BriefingSource, BriefRecipient, SendingDomain, User, CompanyProfile
)
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_RECIPIENTS_PER_BRIEFING = 100  # Limit recipients to prevent spam abuse
MAX_SOURCES_PER_BRIEFING = 20      # Limit sources per briefing


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
            preferred_send_hour = request.form.get('preferred_send_hour', type=int) or 18
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
            
            is_valid, error = validate_mode(mode)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            is_valid, error = validate_visibility(visibility)
            if not is_valid:
                flash(error, 'error')
                return redirect(url_for('briefing.create_briefing'))
            
            # Validate preferred_send_hour
            if preferred_send_hour not in [6, 8, 18]:
                flash('Preferred send hour must be 6, 8, or 18', 'error')
                return redirect(url_for('briefing.create_briefing'))

            # Determine owner_id
            owner_id = current_user.id
            if owner_type == 'org':
                if not current_user.company_profile:
                    flash('You need a company profile to create org briefings', 'error')
                    return redirect(url_for('briefing.create_briefing'))
                owner_id = current_user.company_profile.id

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
                mode=mode,
                visibility=visibility,
                status='active'
            )

            db.session.add(briefing)
            db.session.commit()

            flash(f'Briefing "{name}" created successfully!', 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing.id))

        except Exception as e:
            logger.error(f"Error creating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while creating the briefing', 'error')
            return redirect(url_for('briefing.create_briefing'))

    # GET: Show create form
    templates = BriefTemplate.query.filter_by(allow_customization=True).all()
    return render_template('briefing/create.html', templates=templates)


@briefing_bp.route('/<int:briefing_id>')
@login_required
@limiter.limit("60/minute")
def detail(briefing_id):
    """View briefing details"""
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to view this briefing', 'error')
        return redirect(url_for('briefing.list_briefings'))

    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to view this briefing', 'error')
            return redirect(url_for('briefing.list_briefings'))

    # Get related data
    sources = [bs.input_source for bs in briefing.sources]
    recipients = briefing.recipients.filter_by(status='active').all()
    recent_runs = briefing.runs.limit(10).all()
    
    # Get available sources user can add
    available_sources = InputSource.query.filter_by(
        owner_type='user',
        owner_id=current_user.id,
        enabled=True
    ).all()
    
    if current_user.company_profile:
        org_sources = InputSource.query.filter_by(
            owner_type='org',
            owner_id=current_user.company_profile.id,
            enabled=True
        ).all()
        available_sources.extend(org_sources)
    
    # Filter out sources already added
    added_source_ids = {s.id for s in sources}
    available_sources = [s for s in available_sources if s.id not in added_source_ids]

    return render_template(
        'briefing/detail.html',
        briefing=briefing,
        sources=sources,
        recipients=recipients,
        recent_runs=recent_runs,
        available_sources=available_sources
    )


@briefing_bp.route('/<int:briefing_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit("10/minute")
def edit(briefing_id):
    """Edit briefing configuration"""
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to edit this briefing', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))

    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to edit this briefing', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

    if request.method == 'POST':
        try:
            # Get form values
            name = request.form.get('name', briefing.name).strip()
            description = request.form.get('description', '').strip()
            cadence = request.form.get('cadence', briefing.cadence)
            timezone = request.form.get('timezone', briefing.timezone)
            preferred_send_hour = request.form.get('preferred_send_hour', type=int) or briefing.preferred_send_hour
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

            # Validate preferred_send_hour
            if preferred_send_hour not in [6, 8, 18]:
                flash('Preferred send hour must be 6, 8, or 18', 'error')
                return redirect(url_for('briefing.edit', briefing_id=briefing_id))

            # Update briefing
            briefing.name = name
            briefing.description = description
            briefing.cadence = cadence
            briefing.timezone = timezone
            briefing.preferred_send_hour = preferred_send_hour
            briefing.mode = mode
            briefing.visibility = visibility
            briefing.status = status

            db.session.commit()
            flash('Briefing updated successfully', 'success')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

        except Exception as e:
            logger.error(f"Error updating briefing: {e}", exc_info=True)
            db.session.rollback()
            flash('An error occurred while updating the briefing', 'error')

    templates = BriefTemplate.query.all()
    return render_template('briefing/edit.html', briefing=briefing, templates=templates)


@briefing_bp.route('/<int:briefing_id>/delete', methods=['POST'])
@login_required
@limiter.limit("5/minute")
def delete(briefing_id):
    """Delete a briefing"""
    briefing = Briefing.query.get_or_404(briefing_id)

    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to delete this briefing', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))

    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to delete this briefing', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))

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

    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403

    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
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
            filename = secure_filename(file.filename)
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset
            
            is_valid, error = validate_file_upload(filename, file_size, max_size_mb=10)
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to modify this briefing', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to modify this briefing', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    try:
        source_id = request.form.get('source_id', type=int)
        if not source_id:
            flash('Source ID is required', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check if source exists and user has access
        source = InputSource.query.get(source_id)
        if not source:
            flash('Source not found', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Check ownership
        if source.owner_type == 'user' and source.owner_id != current_user.id:
            flash('You do not have access to this source', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        if source.owner_type == 'org':
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
            source_id=source_id
        ).first()
        
        if existing:
            flash('Source already added to this briefing', 'info')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
        
        # Add source
        briefing_source = BriefingSource(
            briefing_id=briefing_id,
            source_id=source_id
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to modify this briefing', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to modify this briefing', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to manage recipients', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to manage recipients', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to view this run', 'error')
        return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to view this run', 'error')
            return redirect(url_for('briefing.detail', briefing_id=briefing_id))
    
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to edit this run', 'error')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to edit this run', 'error')
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
                brief_run.draft_html = brief_run.draft_markdown.replace('\n', '<br>')
                
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
    
    # Check permissions
    if briefing.owner_type == 'user' and briefing.owner_id != current_user.id:
        flash('You do not have permission to send this run', 'error')
        return redirect(url_for('briefing.view_run', briefing_id=briefing_id, run_id=run_id))
    
    if briefing.owner_type == 'org':
        if not current_user.company_profile or briefing.owner_id != current_user.company_profile.id:
            flash('You do not have permission to send this run', 'error')
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
                sending_domain.dns_records_required = result.get('dns_records', [])
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
