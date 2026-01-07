"""
Brief Routes

Public routes for daily brief viewing, subscription, and archive.
"""

from flask import render_template, redirect, url_for, flash, request, jsonify, session, current_app
from datetime import date, datetime, timedelta
from app.brief import brief_bp
from app import db, limiter
from app.models import DailyBrief, BriefItem, DailyBriefSubscriber, BriefTeam, User
from app.brief.email_client import send_brief_to_subscriber
import re
import logging

logger = logging.getLogger(__name__)


@brief_bp.route('/brief')
@brief_bp.route('/brief/today')
def today():
    """Show today's brief"""
    brief = DailyBrief.get_today()

    if not brief:
        flash("Today's brief is being prepared. Check back soon!", 'info')
        return render_template('brief/no_brief.html')

    # Check if user is subscriber (active status required)
    subscriber = None
    is_subscriber = False
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])
        if subscriber and subscriber.status == 'active':
            is_subscriber = True

    # Get items ordered by position
    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'brief/view.html',
        brief=brief,
        items=items,
        subscriber=subscriber,
        is_subscriber=is_subscriber,
        is_today=True
    )


@brief_bp.route('/brief/<date_str>')
def view_date(date_str):
    """View brief for a specific date (YYYY-MM-DD format)"""
    try:
        brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format. Use YYYY-MM-DD.', 'error')
        return redirect(url_for('brief.today'))

    brief = DailyBrief.get_by_date(brief_date)

    if not brief:
        flash(f'No brief available for {brief_date.strftime("%B %d, %Y")}', 'info')
        return render_template('brief/no_brief.html', requested_date=brief_date)

    # Check if user is subscriber (active status required)
    subscriber = None
    is_subscriber = False
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])
        if subscriber and subscriber.status == 'active':
            is_subscriber = True

    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'brief/view.html',
        brief=brief,
        items=items,
        subscriber=subscriber,
        is_subscriber=is_subscriber,
        is_today=(brief_date == date.today())
    )


@brief_bp.route('/brief/archive')
def archive():
    """Browse brief archive"""
    page = request.args.get('page', 1, type=int)
    per_page = 30

    # Check if user is subscriber
    subscriber = None
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])

    # Get published briefs, newest first
    pagination = DailyBrief.query.filter_by(
        status='published'
    ).order_by(
        DailyBrief.date.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    briefs = pagination.items

    return render_template(
        'brief/archive.html',
        briefs=briefs,
        pagination=pagination,
        subscriber=subscriber
    )


@brief_bp.route('/brief/subscribe', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def subscribe():
    """Subscribe to daily brief"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        timezone = request.form.get('timezone', 'UTC')
        preferred_hour = request.form.get('preferred_hour', 18, type=int)

        # Validate email
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('brief.subscribe'))

        # Validate timezone
        import pytz
        try:
            pytz.timezone(timezone)
        except:
            timezone = 'UTC'

        # Validate preferred hour
        if preferred_hour not in [6, 8, 18]:
            preferred_hour = 18

        # Check if already subscribed
        existing = DailyBriefSubscriber.query.filter_by(email=email).first()

        if existing:
            if existing.status == 'active':
                flash('This email is already subscribed to the daily brief.', 'info')
                return redirect(url_for('brief.subscribe_success'))
            else:
                # Reactivate
                existing.status = 'active'
                existing.timezone = timezone
                existing.preferred_send_hour = preferred_hour
                existing.generate_magic_token()
                existing.start_trial()
                db.session.commit()

                flash('Welcome back! Your subscription has been reactivated.', 'success')
                return redirect(url_for('brief.subscribe_success'))

        # Check if user exists with this email
        user = User.query.filter_by(email=email).first()

        try:
            subscriber = DailyBriefSubscriber(
                email=email,
                user_id=user.id if user else None,
                timezone=timezone,
                preferred_send_hour=preferred_hour
            )
            subscriber.generate_magic_token()
            subscriber.start_trial()  # 14-day trial

            db.session.add(subscriber)
            db.session.commit()

            logger.info(f"New brief subscriber: {email}")

            # Send welcome email (optional - implement later)
            # send_brief_welcome_email(subscriber)

            flash('Successfully subscribed! Check your email for the first brief.', 'success')
            return redirect(url_for('brief.subscribe_success'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Subscription error for {email}: {e}")
            flash('An error occurred. Please try again.', 'error')
            return redirect(url_for('brief.subscribe'))

    # GET request - show subscription form
    return render_template('brief/subscribe.html')


@brief_bp.route('/brief/subscribe/success')
def subscribe_success():
    """Subscription confirmation page"""
    return render_template('brief/subscribe_success.html')


@brief_bp.route('/brief/unsubscribe/<token>')
def unsubscribe(token):
    """Unsubscribe from daily brief emails"""
    subscriber = DailyBriefSubscriber.query.filter_by(magic_token=token).first()

    if not subscriber:
        flash('Invalid unsubscribe link.', 'error')
        return redirect(url_for('brief.today'))

    # Update database
    subscriber.status = 'unsubscribed'
    subscriber.unsubscribed_at = datetime.utcnow()
    db.session.commit()

    logger.info(f"Brief unsubscribe: {subscriber.email}")

    flash('You have been unsubscribed from the daily brief.', 'success')
    return render_template('brief/unsubscribed.html', email=subscriber.email)


@brief_bp.route('/brief/m/<token>')
def magic_link(token):
    """Magic link access for subscribers"""
    subscriber = DailyBriefSubscriber.verify_magic_token(token)

    if not subscriber:
        flash('This link has expired or is invalid. Please subscribe again.', 'warning')
        return redirect(url_for('brief.subscribe'))

    # Set session
    session['brief_subscriber_id'] = subscriber.id
    session['brief_subscriber_token'] = token
    session.modified = True

    # Log them in if they have a User account
    if subscriber.user:
        from flask_login import login_user
        login_user(subscriber.user)

    flash(f'Welcome back! Signed in as {subscriber.email}', 'success')
    return redirect(url_for('brief.today'))


@brief_bp.route('/brief/methodology')
def methodology():
    """Explain how the brief works"""
    return render_template('brief/methodology.html')


@brief_bp.route('/brief/underreported')
def underreported():
    """Show underreported stories (high civic value, low coverage)"""
    from app.brief.underreported import get_underreported_stories

    stories = get_underreported_stories(days=7, limit=10)

    return render_template('brief/underreported.html', stories=stories)


@brief_bp.route('/api/brief/latest')
def api_latest():
    """API endpoint for latest brief (subscriber-only)"""
    # Check if user is an active subscriber
    subscriber = None
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])

    if not subscriber or subscriber.status != 'active':
        return jsonify({
            'error': 'Subscription required',
            'message': 'Subscribe to access the full Daily Brief API.',
            'subscribe_url': '/brief/subscribe'
        }), 401

    brief = DailyBrief.get_today()

    if not brief:
        return jsonify({'error': 'No brief available'}), 404

    return jsonify(brief.to_dict())


@brief_bp.route('/api/brief/<date_str>')
def api_brief_by_date(date_str):
    """API endpoint for brief by date (subscriber-only)"""
    # Check if user is an active subscriber
    subscriber = None
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])

    if not subscriber or subscriber.status != 'active':
        return jsonify({
            'error': 'Subscription required',
            'message': 'Subscribe to access the full Daily Brief API.',
            'subscribe_url': '/brief/subscribe'
        }), 401

    try:
        brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    brief = DailyBrief.get_by_date(brief_date)

    if not brief:
        return jsonify({'error': 'No brief found'}), 404

    return jsonify(brief.to_dict())
