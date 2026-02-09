"""
Brief Admin Interface

Admin routes for reviewing, editing, and publishing daily briefs.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from app import db
from app.models import DailyBrief, BriefItem, TrendingTopic, User
from app.brief.generator import generate_daily_brief
from app.brief.topic_selector import select_todays_topics
from app.decorators import admin_required
import logging

logger = logging.getLogger(__name__)

# Create admin blueprint
brief_admin_bp = Blueprint('brief_admin', __name__, url_prefix='/admin/brief')


@brief_admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard for briefs"""
    from sqlalchemy import func
    
    # Get today's brief
    today_brief = DailyBrief.query.filter_by(date=date.today()).first()

    # Get recent briefs
    recent_briefs = DailyBrief.query.order_by(
        DailyBrief.date.desc()
    ).limit(10).all()
    
    # Batch fetch item counts to prevent N+1 queries
    brief_ids = [b.id for b in recent_briefs]
    if today_brief and today_brief.id not in brief_ids:
        brief_ids.append(today_brief.id)
    
    item_counts = {}
    if brief_ids:
        counts = db.session.query(
            BriefItem.brief_id,
            func.count(BriefItem.id)
        ).filter(
            BriefItem.brief_id.in_(brief_ids)
        ).group_by(BriefItem.brief_id).all()
        item_counts = {bid: count for bid, count in counts}
    
    # Cache counts on brief objects
    for brief in recent_briefs:
        brief._cached_item_count = item_counts.get(brief.id, 0)
    if today_brief:
        today_brief._cached_item_count = item_counts.get(today_brief.id, 0)

    # Get upcoming candidate topics
    candidate_topics = select_todays_topics(limit=10)

    # Stats
    from app.models import DailyBriefSubscriber
    total_subscribers = DailyBriefSubscriber.query.filter_by(status='active').count()
    trial_subscribers = DailyBriefSubscriber.query.filter_by(tier='trial', status='active').count()
    free_subscribers = DailyBriefSubscriber.query.filter_by(tier='free', status='active').count()
    paid_subscribers = DailyBriefSubscriber.query.filter(
        DailyBriefSubscriber.tier.in_(['individual', 'team']),
        DailyBriefSubscriber.status == 'active'
    ).count()

    # Cadence breakdown
    daily_subscribers = DailyBriefSubscriber.query.filter(
        DailyBriefSubscriber.status == 'active',
        db.or_(
            DailyBriefSubscriber.cadence == 'daily',
            DailyBriefSubscriber.cadence.is_(None)
        )
    ).count()
    weekly_subscribers = DailyBriefSubscriber.query.filter_by(
        cadence='weekly', status='active'
    ).count()

    # Latest weekly brief
    latest_weekly = DailyBrief.query.filter_by(
        brief_type='weekly'
    ).order_by(DailyBrief.date.desc()).first()

    return render_template(
        'admin/brief_dashboard.html',
        today_brief=today_brief,
        recent_briefs=recent_briefs,
        candidate_topics=candidate_topics,
        total_subscribers=total_subscribers,
        trial_subscribers=trial_subscribers,
        free_subscribers=free_subscribers,
        paid_subscribers=paid_subscribers,
        daily_subscribers=daily_subscribers,
        weekly_subscribers=weekly_subscribers,
        latest_weekly=latest_weekly
    )


@brief_admin_bp.route('/preview')
@brief_admin_bp.route('/preview/<date_str>')
@admin_required
def preview(date_str=None):
    """Preview today's brief or generate draft"""
    if date_str:
        try:
            brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.', 'error')
            return redirect(url_for('brief_admin.dashboard'))
    else:
        brief_date = date.today()

    # Get or generate brief
    brief = DailyBrief.query.filter_by(date=brief_date).first()

    if not brief:
        flash(f'No brief exists for {brief_date}. Generate one below.', 'info')
        return redirect(url_for('brief_admin.generate', date_str=brief_date.isoformat()))

    # Get items
    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'admin/brief_preview.html',
        brief=brief,
        items=items,
        is_today=(brief_date == date.today())
    )


@brief_admin_bp.route('/generate', methods=['GET', 'POST'])
@admin_required
def generate(date_str=None):
    """Generate brief for a date"""
    if request.method == 'POST':
        date_str = request.form.get('date')

    if not date_str:
        date_str = date.today().isoformat()

    try:
        brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('brief_admin.dashboard'))

    try:
        # Check if already exists
        existing = DailyBrief.query.filter_by(date=brief_date).first()
        if existing and existing.status != 'draft':
            flash(f'Brief already exists for {brief_date} with status: {existing.status}', 'warning')
            return redirect(url_for('brief_admin.preview', date_str=date_str))

        # Generate
        logger.info(f"Admin generating brief for {brief_date}")
        brief = generate_daily_brief(brief_date, auto_publish=False)

        if brief is None:
            flash('No suitable topics available for this date. Try fetching news first.', 'warning')
            return redirect(url_for('brief_admin.dashboard'))

        flash(f'Brief generated successfully! Review it before publishing.', 'success')
        return redirect(url_for('brief_admin.preview', date_str=date_str))

    except Exception as e:
        logger.error(f"Brief generation failed: {e}", exc_info=True)
        flash(f'Error generating brief: {str(e)}', 'error')
        return redirect(url_for('brief_admin.dashboard'))


@brief_admin_bp.route('/publish/<int:brief_id>', methods=['POST'])
@admin_required
def publish(brief_id):
    """Publish a draft brief"""
    brief = DailyBrief.query.get_or_404(brief_id)

    if brief.status == 'published':
        flash('Brief is already published.', 'info')
        return redirect(url_for('brief_admin.preview', date_str=brief.date.isoformat()))

    # Update status
    brief.status = 'published'
    brief.published_at = datetime.utcnow()
    brief.auto_selected = False  # Marked as manually published
    brief.admin_edited_by = current_user.id

    db.session.commit()

    logger.info(f"Brief {brief.id} published by {current_user.email}")
    flash(f'Brief published! Emails will send at scheduled times.', 'success')

    return redirect(url_for('brief_admin.preview', date_str=brief.date.isoformat()))


@brief_admin_bp.route('/unpublish/<int:brief_id>', methods=['POST'])
@admin_required
def unpublish(brief_id):
    """Unpublish a brief"""
    brief = DailyBrief.query.get_or_404(brief_id)

    brief.status = 'draft'
    brief.published_at = None

    db.session.commit()

    logger.info(f"Brief {brief.id} unpublished by {current_user.email}")
    flash('Brief unpublished.', 'success')

    return redirect(url_for('brief_admin.preview', date_str=brief.date.isoformat()))


@brief_admin_bp.route('/skip/<int:brief_id>', methods=['POST'])
@admin_required
def skip(brief_id):
    """Skip a brief (mark as not sending)"""
    brief = DailyBrief.query.get_or_404(brief_id)
    reason = request.form.get('reason', 'Admin decision')

    brief.status = 'skipped'
    brief.admin_notes = reason
    brief.admin_edited_by = current_user.id

    db.session.commit()

    logger.info(f"Brief {brief.id} skipped by {current_user.email}: {reason}")
    flash(f'Brief marked as skipped.', 'success')

    return redirect(url_for('brief_admin.dashboard'))


@brief_admin_bp.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_item(item_id):
    """Edit a brief item"""
    item = BriefItem.query.get_or_404(item_id)

    if request.method == 'POST':
        # Update fields
        item.headline = request.form.get('headline', item.headline)

        # Parse bullets (one per line)
        bullets_text = request.form.get('bullets', '')
        item.summary_bullets = [b.strip() for b in bullets_text.split('\n') if b.strip()]

        item.cta_text = request.form.get('cta_text', item.cta_text)

        # Mark brief as manually edited
        item.brief.auto_selected = False
        item.brief.admin_edited_by = current_user.id

        db.session.commit()

        logger.info(f"Brief item {item.id} edited by {current_user.email}")
        flash('Item updated successfully.', 'success')

        return redirect(url_for('brief_admin.preview', date_str=item.brief.date.isoformat()))

    # GET - show edit form
    bullets_text = '\n'.join(item.summary_bullets)

    return render_template(
        'admin/edit_item.html',
        item=item,
        bullets_text=bullets_text
    )


@brief_admin_bp.route('/item/<int:item_id>/remove', methods=['POST'])
@admin_required
def remove_item(item_id):
    """Remove item from brief"""
    item = BriefItem.query.get_or_404(item_id)
    brief = item.brief

    # Store position for reordering
    removed_position = item.position

    db.session.delete(item)

    # Reorder remaining items
    remaining_items = BriefItem.query.filter(
        BriefItem.brief_id == brief.id,
        BriefItem.position > removed_position
    ).all()

    for remaining_item in remaining_items:
        remaining_item.position -= 1

    # Mark as edited
    brief.auto_selected = False
    brief.admin_edited_by = current_user.id

    db.session.commit()

    logger.info(f"Brief item {item_id} removed by {current_user.email}")
    flash('Item removed from brief.', 'success')

    return redirect(url_for('brief_admin.preview', date_str=brief.date.isoformat()))


@brief_admin_bp.route('/subscribers')
@admin_required
def subscribers():
    """View subscriber list with search, status, and cadence filters."""
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Search and filter params (follows same pattern as admin.list_users)
    search_query = request.args.get('q', '').strip()[:255]  # Length limit
    status_filter = request.args.get('status', '')
    cadence_filter = request.args.get('cadence', '')
    tier_filter = request.args.get('tier', '')

    from app.models import DailyBriefSubscriber

    # Build query with filters
    query = DailyBriefSubscriber.query

    # Search by email (case-insensitive, same pattern as admin users list)
    if search_query:
        # Escape SQL LIKE wildcards to prevent unintended matching
        escaped = search_query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        search_term = f'%{escaped}%'
        query = query.filter(DailyBriefSubscriber.email.ilike(search_term))

    # Filter by status
    if status_filter:
        query = query.filter(DailyBriefSubscriber.status == status_filter)

    # Filter by cadence
    if cadence_filter == 'daily':
        query = query.filter(
            db.or_(
                DailyBriefSubscriber.cadence == 'daily',
                DailyBriefSubscriber.cadence.is_(None)
            )
        )
    elif cadence_filter == 'weekly':
        query = query.filter(DailyBriefSubscriber.cadence == 'weekly')

    # Filter by tier
    if tier_filter:
        query = query.filter(DailyBriefSubscriber.tier == tier_filter)

    pagination = query.order_by(
        DailyBriefSubscriber.created_at.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    subscribers = pagination.items

    # Calculate stats (always unfiltered for the overview cards)
    stats = {
        'total': DailyBriefSubscriber.query.count(),
        'active': DailyBriefSubscriber.query.filter_by(status='active').count(),
        'trial': DailyBriefSubscriber.query.filter_by(tier='trial', status='active').count(),
        'free': DailyBriefSubscriber.query.filter_by(tier='free', status='active').count(),
        'individual': DailyBriefSubscriber.query.filter_by(tier='individual', status='active').count(),
        'team': DailyBriefSubscriber.query.filter_by(tier='team', status='active').count(),
        'unsubscribed': DailyBriefSubscriber.query.filter_by(status='unsubscribed').count()
    }

    return render_template(
        'admin/brief_subscribers.html',
        subscribers=subscribers,
        pagination=pagination,
        stats=stats,
        search_query=search_query,
        status_filter=status_filter,
        cadence_filter=cadence_filter,
        tier_filter=tier_filter
    )


@brief_admin_bp.route('/test-send', methods=['POST'])
@admin_required
def test_send():
    """Send test email to admin"""
    brief_id = request.form.get('brief_id', type=int)
    test_email = request.form.get('email') or current_user.email

    if not brief_id:
        flash('Brief ID required.', 'error')
        return redirect(url_for('brief_admin.dashboard'))

    brief = DailyBrief.query.get_or_404(brief_id)

    try:
        from app.brief.email_client import send_brief_to_subscriber

        # Check if test email is subscribed, if not create temp subscriber
        from app.models import DailyBriefSubscriber
        subscriber = DailyBriefSubscriber.query.filter_by(email=test_email).first()

        if not subscriber:
            # Create temporary subscriber for test
            subscriber = DailyBriefSubscriber(
                email=test_email,
                timezone='UTC',
                preferred_send_hour=18
            )
            subscriber.generate_magic_token()
            subscriber.start_trial()
            db.session.add(subscriber)
            db.session.commit()

        success = send_brief_to_subscriber(test_email, brief.date.isoformat())

        if success:
            flash(f'Test email sent to {test_email}', 'success')
        else:
            flash('Failed to send test email. Check logs.', 'error')

    except Exception as e:
        logger.error(f"Test send failed: {e}")
        flash(f'Error: {str(e)}', 'error')

    return redirect(url_for('brief_admin.preview', date_str=brief.date.isoformat()))


@brief_admin_bp.route('/send-to-subscriber', methods=['POST'])
@admin_required
def send_to_subscriber():
    """Manually send today's brief to a specific subscriber"""
    email = request.form.get('email')
    brief_date_str = request.form.get('brief_date', date.today().isoformat())
    
    if not email:
        flash('Email address required.', 'error')
        return redirect(url_for('brief_admin.dashboard'))
    
    try:
        from app.brief.email_client import send_brief_to_subscriber
        from app.models import DailyBriefSubscriber
        
        subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
        if not subscriber:
            flash(f'Subscriber not found: {email}', 'error')
            return redirect(url_for('brief_admin.dashboard'))
        
        if subscriber.status != 'active':
            flash(f'Subscriber is not active: {email} (status: {subscriber.status})', 'error')
            return redirect(url_for('brief_admin.dashboard'))
        
        brief = DailyBrief.query.filter_by(date=datetime.strptime(brief_date_str, '%Y-%m-%d').date()).first()
        if not brief:
            flash(f'No brief found for {brief_date_str}', 'error')
            return redirect(url_for('brief_admin.dashboard'))
        
        if brief.status != 'published':
            flash(f'Brief is not published (status: {brief.status})', 'error')
            return redirect(url_for('brief_admin.dashboard'))
        
        success = send_brief_to_subscriber(email, brief_date_str)
        
        if success:
            flash(f'Brief sent to {email}', 'success')
        else:
            flash(f'Failed to send brief to {email}. Check logs.', 'error')
    
    except Exception as e:
        logger.error(f"Manual send failed: {e}", exc_info=True)
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('brief_admin.dashboard'))


# =============================================================================
# SUBSCRIBER MANAGEMENT ROUTES
# =============================================================================

@brief_admin_bp.route('/subscribers/add', methods=['POST'])
@admin_required
def add_subscriber():
    """Add a single subscriber by email with tier selection"""
    from app.models import DailyBriefSubscriber
    
    email = request.form.get('email', '').strip().lower()
    timezone = request.form.get('timezone', 'UTC')
    preferred_hour = request.form.get('preferred_hour', 18, type=int)
    tier = request.form.get('tier', 'trial')
    trial_days = request.form.get('trial_days', 14, type=int)
    
    if not email:
        flash('Email address required.', 'error')
        return redirect(url_for('brief_admin.subscribers'))
    
    # Check if already exists
    existing = DailyBriefSubscriber.query.filter_by(email=email).first()
    if existing:
        flash(f'{email} is already subscribed.', 'warning')
        return redirect(url_for('brief_admin.subscribers'))
    
    try:
        subscriber = DailyBriefSubscriber(
            email=email,
            timezone=timezone,
            preferred_send_hour=preferred_hour
        )
        subscriber.generate_magic_token()
        
        # Set tier based on admin selection
        if tier == 'free':
            subscriber.grant_free_access()
        else:
            subscriber.start_trial(days=trial_days)
        
        db.session.add(subscriber)
        db.session.commit()
        
        tier_msg = 'free access' if tier == 'free' else f'{trial_days}-day trial'
        flash(f'Added {email} with {tier_msg}.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to add subscriber: {e}")
        flash(f'Error adding subscriber: {str(e)}', 'error')
    
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/bulk-import', methods=['POST'])
@admin_required
def bulk_import_subscribers():
    """Bulk import subscribers from text input (comma, newline, or space separated)"""
    from app.models import DailyBriefSubscriber
    import re
    
    emails_text = request.form.get('emails', '')
    timezone = request.form.get('timezone', 'UTC')
    preferred_hour = request.form.get('preferred_hour', 18, type=int)
    tier = request.form.get('tier', 'trial')
    trial_days = request.form.get('trial_days', 14, type=int)
    
    # Parse emails (handle comma, newline, space, semicolon separators)
    emails = re.split(r'[,\n\s;]+', emails_text)
    emails = [e.strip().lower() for e in emails if e.strip() and '@' in e]
    
    if not emails:
        flash('No valid email addresses found.', 'error')
        return redirect(url_for('brief_admin.subscribers'))
    
    added = 0
    skipped = 0
    
    for email in emails:
        # Check if already exists
        existing = DailyBriefSubscriber.query.filter_by(email=email).first()
        if existing:
            skipped += 1
            continue
        
        try:
            subscriber = DailyBriefSubscriber(
                email=email,
                timezone=timezone,
                preferred_send_hour=preferred_hour
            )
            subscriber.generate_magic_token()
            
            # Set tier based on admin selection
            if tier == 'free':
                subscriber.grant_free_access()
            else:
                subscriber.start_trial(days=trial_days)
            
            db.session.add(subscriber)
            added += 1
        except Exception as e:
            logger.error(f"Failed to add subscriber {email}: {e}")
            skipped += 1
    
    db.session.commit()
    
    tier_msg = 'free access' if tier == 'free' else f'{trial_days}-day trial'
    flash(f'Imported {added} subscribers with {tier_msg}. {skipped} skipped (already subscribed).', 'success')
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/<int:subscriber_id>/toggle', methods=['POST'])
@admin_required
def toggle_subscriber(subscriber_id):
    """Toggle subscriber active/paused status"""
    from app.models import DailyBriefSubscriber
    
    subscriber = DailyBriefSubscriber.query.get_or_404(subscriber_id)
    
    if subscriber.status == 'active':
        subscriber.status = 'paused'
        flash(f'{subscriber.email} has been paused.', 'success')
    elif subscriber.status in ('paused', 'unsubscribed'):
        subscriber.status = 'active'
        flash(f'{subscriber.email} has been reactivated.', 'success')
    else:
        flash(f'Cannot toggle status for {subscriber.email} (status: {subscriber.status})', 'warning')
    
    db.session.commit()
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/<int:subscriber_id>/delete', methods=['POST'])
@admin_required
def delete_subscriber(subscriber_id):
    """Delete a subscriber"""
    from app.models import DailyBriefSubscriber
    
    subscriber = DailyBriefSubscriber.query.get_or_404(subscriber_id)
    email = subscriber.email
    
    db.session.delete(subscriber)
    db.session.commit()
    
    logger.info(f"Subscriber {email} deleted by {current_user.email}")
    flash(f'{email} has been removed.', 'success')
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/bulk-remove', methods=['POST'])
@admin_required
def bulk_remove_subscribers():
    """Bulk remove selected subscribers"""
    from app.models import DailyBriefSubscriber
    
    subscriber_ids = request.form.getlist('subscriber_ids', type=int)
    
    if not subscriber_ids:
        flash('No subscribers selected.', 'warning')
        return redirect(url_for('brief_admin.subscribers'))
    
    deleted = DailyBriefSubscriber.query.filter(
        DailyBriefSubscriber.id.in_(subscriber_ids)
    ).delete(synchronize_session=False)
    
    db.session.commit()
    
    logger.info(f"{deleted} subscribers deleted by {current_user.email}")
    flash(f'Removed {deleted} subscribers.', 'success')
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/<int:subscriber_id>/resend', methods=['POST'])
@admin_required
def resend_to_subscriber(subscriber_id):
    """Resend today's brief to a specific subscriber"""
    from app.models import DailyBriefSubscriber
    from app.brief.email_client import send_brief_to_subscriber
    
    subscriber = DailyBriefSubscriber.query.get_or_404(subscriber_id)
    
    # Get today's published brief
    today_brief = DailyBrief.query.filter_by(
        date=date.today(),
        status='published'
    ).first()
    
    if not today_brief:
        flash('No published brief for today.', 'error')
        return redirect(url_for('brief_admin.subscribers'))
    
    try:
        success = send_brief_to_subscriber(subscriber.email, date.today().isoformat())
        if success:
            flash(f'Brief resent to {subscriber.email}', 'success')
        else:
            flash(f'Failed to resend to {subscriber.email}', 'error')
    except Exception as e:
        logger.error(f"Resend failed: {e}")
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/<int:subscriber_id>/set-tier', methods=['POST'])
@admin_required
def set_subscriber_tier(subscriber_id):
    """Change a subscriber's tier (admin only)"""
    from app.models import DailyBriefSubscriber
    
    subscriber = DailyBriefSubscriber.query.get_or_404(subscriber_id)
    new_tier = request.form.get('tier')
    
    valid_tiers = ['trial', 'free', 'individual', 'team']
    if new_tier not in valid_tiers:
        flash(f'Invalid tier: {new_tier}', 'error')
        return redirect(url_for('brief_admin.subscribers'))
    
    old_tier = subscriber.tier
    
    if new_tier == 'free':
        subscriber.grant_free_access()
        flash(f'{subscriber.email} granted permanent free access.', 'success')
    elif new_tier == 'trial':
        # Reset to new 14-day trial
        subscriber.start_trial(days=14)
        flash(f'{subscriber.email} reset to 14-day trial.', 'success')
    else:
        # For individual/team, just set the tier (Stripe will handle the rest)
        subscriber.tier = new_tier
        flash(f'{subscriber.email} tier changed to {new_tier}. Note: Stripe subscription required for paid tiers.', 'info')
    
    db.session.commit()
    logger.info(f"Subscriber {subscriber.email} tier changed from {old_tier} to {new_tier} by {current_user.email}")
    
    return redirect(url_for('brief_admin.subscribers'))


@brief_admin_bp.route('/subscribers/<int:subscriber_id>/extend-trial', methods=['POST'])
@admin_required
def extend_subscriber_trial(subscriber_id):
    """Extend a subscriber's trial period"""
    from app.models import DailyBriefSubscriber
    
    subscriber = DailyBriefSubscriber.query.get_or_404(subscriber_id)
    additional_days = request.form.get('days', 14, type=int)
    
    if additional_days < 1 or additional_days > 365:
        flash('Days must be between 1 and 365.', 'error')
        return redirect(url_for('brief_admin.subscribers'))
    
    subscriber.extend_trial(additional_days=additional_days)
    db.session.commit()
    
    logger.info(f"Subscriber {subscriber.email} trial extended by {additional_days} days by {current_user.email}")
    flash(f'Extended {subscriber.email} trial by {additional_days} days. New expiration: {subscriber.trial_ends_at.strftime("%b %d, %Y")}', 'success')
    
    return redirect(url_for('brief_admin.subscribers'))
