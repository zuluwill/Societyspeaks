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
from functools import wraps
import logging

logger = logging.getLogger(__name__)

# Create admin blueprint
brief_admin_bp = Blueprint('brief_admin', __name__, url_prefix='/admin/brief')


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access admin features.', 'error')
            return redirect(url_for('auth.login'))

        # Check if user is admin (adjust based on your User model)
        if not getattr(current_user, 'is_admin', False):
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))

        return f(*args, **kwargs)
    return decorated_function


@brief_admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard for briefs"""
    # Get today's brief
    today_brief = DailyBrief.query.filter_by(date=date.today()).first()

    # Get recent briefs
    recent_briefs = DailyBrief.query.order_by(
        DailyBrief.date.desc()
    ).limit(10).all()

    # Get upcoming candidate topics
    candidate_topics = select_todays_topics(limit=10)

    # Stats
    from app.models import DailyBriefSubscriber
    total_subscribers = DailyBriefSubscriber.query.filter_by(status='active').count()
    trial_subscribers = DailyBriefSubscriber.query.filter_by(tier='trial', status='active').count()
    paid_subscribers = DailyBriefSubscriber.query.filter(
        DailyBriefSubscriber.tier.in_(['individual', 'team']),
        DailyBriefSubscriber.status == 'active'
    ).count()

    return render_template(
        'admin/brief_dashboard.html',
        today_brief=today_brief,
        recent_briefs=recent_briefs,
        candidate_topics=candidate_topics,
        total_subscribers=total_subscribers,
        trial_subscribers=trial_subscribers,
        paid_subscribers=paid_subscribers
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
    """View subscriber list"""
    page = request.args.get('page', 1, type=int)
    per_page = 50

    from app.models import DailyBriefSubscriber

    pagination = DailyBriefSubscriber.query.order_by(
        DailyBriefSubscriber.created_at.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    subscribers = pagination.items

    # Calculate stats
    stats = {
        'total': DailyBriefSubscriber.query.count(),
        'active': DailyBriefSubscriber.query.filter_by(status='active').count(),
        'trial': DailyBriefSubscriber.query.filter_by(tier='trial', status='active').count(),
        'individual': DailyBriefSubscriber.query.filter_by(tier='individual', status='active').count(),
        'team': DailyBriefSubscriber.query.filter_by(tier='team', status='active').count(),
        'unsubscribed': DailyBriefSubscriber.query.filter_by(status='unsubscribed').count()
    }

    return render_template(
        'admin/brief_subscribers.html',
        subscribers=subscribers,
        pagination=pagination,
        stats=stats
    )


@brief_admin_bp.route('/test-send', methods=['POST'])
@admin_required
def test_send():
    """Send test email to admin"""
    brief_id = request.form.get('brief_id', type=int)
    test_email = request.form.get('email', current_user.email)

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
