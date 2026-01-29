"""
Brief Routes

Public routes for daily brief viewing, subscription, and archive.
"""

import base64
import hashlib
import hmac
import logging
import os
import re

import pytz
from flask import render_template, redirect, url_for, flash, request, jsonify, session, current_app
from flask_login import current_user
from sqlalchemy import func
from datetime import date, datetime, timedelta

from app.brief import brief_bp
from app import db, limiter, csrf
from app.models import DailyBrief, BriefItem, DailyBriefSubscriber, BriefTeam, User, EmailEvent
from app.brief.email_client import send_brief_to_subscriber, ResendClient
from app.trending.conversion_tracking import track_social_click
from app.decorators import admin_required

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

VALID_SEND_HOURS = [6, 8, 18]
DEFAULT_SEND_HOUR = 18
ARCHIVE_PER_PAGE = 30
PREFERENCES_TOKEN_EXPIRE_HOURS = 168  # 7 days


# =============================================================================
# Helper Functions
# =============================================================================

def is_tts_available():
    """Check if TTS is available (XTTS package installed)."""
    try:
        from app.brief.xtts_client import XTTSClient
        client = XTTSClient()
        return client.available
    except ImportError:
        logger.debug("XTTS package not installed")
        return False
    except Exception as e:
        logger.warning(f"Error checking TTS availability: {e}")
        return False


def get_subscriber_status():
    """
    Get subscriber and eligibility status from session.

    Returns:
        tuple: (subscriber, is_subscriber) where subscriber is the DailyBriefSubscriber
               instance (or None) and is_subscriber is a boolean.
    """
    subscriber = None
    is_subscriber = False

    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])
        if subscriber and subscriber.is_subscribed_eligible():
            is_subscriber = True

    # Admins always marked as subscriber for UI consistency
    if current_user.is_authenticated and current_user.is_admin:
        is_subscriber = True

    return subscriber, is_subscriber


def _process_subscription(
    email: str,
    timezone: str = 'UTC',
    preferred_hour: int = DEFAULT_SEND_HOUR,
    update_preferences_on_reactivate: bool = True,
    set_session: bool = False,
    track_posthog: bool = False,
    source: str = None
) -> dict:
    """
    Common subscription processing logic.

    Handles new subscriptions, reactivations, and already-active cases.

    Args:
        email: Subscriber email address
        timezone: Timezone for email delivery (default UTC)
        preferred_hour: Preferred send hour (default DEFAULT_SEND_HOUR)
        update_preferences_on_reactivate: Whether to update tz/hour on reactivation
        set_session: Whether to set session['brief_subscriber_id']
        track_posthog: Whether to track with PostHog
        source: Source tracking string for logging

    Returns:
        dict with keys:
            - 'status': 'created' | 'reactivated' | 'already_active' | 'error'
            - 'subscriber': DailyBriefSubscriber instance (or None on error)
            - 'message': Human-readable message
            - 'error': Error message (only if status == 'error')
    """
    # Check if already subscribed
    existing = DailyBriefSubscriber.query.filter_by(email=email).first()

    if existing:
        if existing.status == 'active':
            return {
                'status': 'already_active',
                'subscriber': existing,
                'message': 'This email is already subscribed to the daily brief.'
            }
        else:
            # Reactivate
            existing.status = 'active'
            if update_preferences_on_reactivate:
                existing.timezone = timezone
                existing.preferred_send_hour = preferred_hour
            existing.generate_magic_token()
            existing.start_trial()
            existing.welcome_email_sent_at = None
            db.session.commit()

            # Send welcome email
            try:
                email_client = ResendClient()
                email_client.send_welcome(existing)
            except Exception as e:
                logger.error(f"Failed to send welcome email to {email}: {e}")

            # Optionally set session
            if set_session:
                session['brief_subscriber_id'] = existing.id
                session.modified = True

            return {
                'status': 'reactivated',
                'subscriber': existing,
                'message': 'Welcome back! Your subscription has been reactivated.'
            }

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
        subscriber.start_trial()

        db.session.add(subscriber)
        db.session.commit()

        source_str = f" (source: {source})" if source else ""
        logger.info(f"New brief subscriber: {email}{source_str}")

        # Send welcome email
        try:
            email_client = ResendClient()
            email_client.send_welcome(subscriber)
        except Exception as e:
            logger.error(f"Failed to send welcome email to {email}: {e}")

        # Optionally set session
        if set_session:
            session['brief_subscriber_id'] = subscriber.id
            session.modified = True

        # Optionally track with PostHog
        if track_posthog:
            try:
                import posthog
                if posthog:
                    posthog.capture(
                        distinct_id=str(user.id) if user else email,
                        event='daily_brief_subscribed',
                        properties={
                            'email': email,
                            'source': 'social' if request.referrer and ('utm_source' in request.referrer or any(d in request.referrer for d in ['twitter.com', 'x.com', 'bsky.social'])) else 'direct',
                            'referrer': request.referrer,
                            'subscription_type': 'daily_brief'
                        }
                    )
            except Exception as e:
                logger.warning(f"PostHog tracking error: {e}")

        return {
            'status': 'created',
            'subscriber': subscriber,
            'message': 'Successfully subscribed! Check your email for the first brief.'
        }

    except Exception as e:
        db.session.rollback()
        logger.error(f"Subscription error for {email}: {e}")
        return {
            'status': 'error',
            'subscriber': None,
            'message': 'An error occurred. Please try again.',
            'error': str(e)
        }


@brief_bp.route('/brief')
@brief_bp.route('/brief/today')
@limiter.limit("60/minute")
def today():
    """Show today's brief - open to everyone, reading is free"""
    # Track social media clicks (conversion tracking)
    user_id = str(current_user.id) if current_user.is_authenticated else None
    track_social_click(request, user_id)

    brief = DailyBrief.get_today()

    # Check subscriber status for personalization (not access control)
    subscriber, is_subscriber = get_subscriber_status()

    # No brief available for today - show most recent brief instead
    if not brief:
        # Find the most recent published brief
        latest_brief = DailyBrief.query.filter_by(
            status='published'
        ).order_by(DailyBrief.date.desc()).first()
        
        if latest_brief:
            items = latest_brief.items.order_by(BriefItem.position).all()
            return render_template(
                'brief/view.html',
                brief=latest_brief,
                items=items,
                subscriber=subscriber,
                is_subscriber=is_subscriber,
                is_today=False,
                waiting_for_today=True,
                show_email_capture=(not is_subscriber),
                tts_available=is_tts_available()
            )
        else:
            return render_template('brief/no_brief.html')

    # Get items ordered by position
    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'brief/view.html',
        brief=brief,
        items=items,
        subscriber=subscriber,
        is_subscriber=is_subscriber,
        is_today=True,
        show_email_capture=(not is_subscriber),
        tts_available=is_tts_available()
    )


@brief_bp.route('/brief/<date_str>')
@limiter.limit("60/minute")
def view_date(date_str):
    """View brief for a specific date (YYYY-MM-DD format) - open to everyone"""
    try:
        brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format. Use YYYY-MM-DD.', 'error')
        return redirect(url_for('brief.today'))

    brief = DailyBrief.get_by_date(brief_date)

    # Check subscriber status for personalization (not access control)
    subscriber, is_subscriber = get_subscriber_status()

    if not brief:
        flash(f'No brief available for {brief_date.strftime("%B %d, %Y")}', 'info')
        return render_template('brief/no_brief.html', requested_date=brief_date)

    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'brief/view.html',
        brief=brief,
        items=items,
        subscriber=subscriber,
        is_subscriber=is_subscriber,
        is_today=(brief_date == date.today()),
        show_email_capture=(not is_subscriber),
        tts_available=is_tts_available()
    )


@brief_bp.route('/brief/<date_str>/reader')
@limiter.limit("60/minute")
def reader_view(date_str):
    """
    Reader-optimized view for a brief.

    Clean, minimal HTML designed for:
    - Reader apps (ElevenReader, Pocket, Instapaper)
    - Browser reader mode
    - Text-to-speech tools
    - Accessibility
    """
    try:
        brief_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format. Use YYYY-MM-DD.', 'error')
        return redirect(url_for('brief.today'))

    brief = DailyBrief.get_by_date(brief_date)

    if not brief:
        flash(f'No brief available for {brief_date.strftime("%B %d, %Y")}', 'info')
        return render_template('brief/no_brief.html', requested_date=brief_date)

    items = brief.items.order_by(BriefItem.position).all()

    return render_template(
        'brief/reader.html',
        brief=brief,
        items=items
    )


@brief_bp.route('/brief/today/reader')
@limiter.limit("60/minute")
def reader_today():
    """Reader view for today's brief - redirects to date-specific reader URL."""
    brief = DailyBrief.get_today()

    if not brief:
        # Fall back to most recent
        latest_brief = DailyBrief.query.filter_by(
            status='published'
        ).order_by(DailyBrief.date.desc()).first()

        if latest_brief:
            return redirect(url_for('brief.reader_view', date_str=latest_brief.date.strftime('%Y-%m-%d')))
        else:
            return render_template('brief/no_brief.html')

    return redirect(url_for('brief.reader_view', date_str=brief.date.strftime('%Y-%m-%d')))


@brief_bp.route('/brief/archive')
@limiter.limit("60/minute")
def archive():
    """Browse brief archive"""
    page = request.args.get('page', 1, type=int)

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
        per_page=ARCHIVE_PER_PAGE,
        error_out=False
    )

    briefs = pagination.items
    
    # Batch fetch item counts to prevent N+1 queries
    brief_ids = [b.id for b in briefs]
    if brief_ids:
        counts = db.session.query(
            BriefItem.brief_id,
            func.count(BriefItem.id)
        ).filter(
            BriefItem.brief_id.in_(brief_ids)
        ).group_by(BriefItem.brief_id).all()
        item_counts = {bid: count for bid, count in counts}
        
        for brief in briefs:
            brief._cached_item_count = item_counts.get(brief.id, 0)

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
        preferred_hour = request.form.get('preferred_hour', DEFAULT_SEND_HOUR, type=int)

        # Validate email
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('brief.subscribe'))

        # Validate timezone
        try:
            pytz.timezone(timezone)
        except (pytz.UnknownTimeZoneError, KeyError):
            timezone = 'UTC'

        # Validate preferred hour
        if preferred_hour not in VALID_SEND_HOURS:
            preferred_hour = DEFAULT_SEND_HOUR

        # Process subscription using shared helper
        result = _process_subscription(
            email=email,
            timezone=timezone,
            preferred_hour=preferred_hour,
            update_preferences_on_reactivate=True,
            set_session=False,
            track_posthog=True
        )

        # Handle result
        if result['status'] == 'already_active':
            flash(result['message'], 'info')
            return redirect(url_for('brief.subscribe_success'))
        elif result['status'] == 'reactivated':
            flash(result['message'], 'success')
            return redirect(url_for('brief.subscribe_success'))
        elif result['status'] == 'created':
            flash(result['message'], 'success')
            return redirect(url_for('brief.subscribe_success'))
        else:  # error
            flash(result['message'], 'error')
            return redirect(url_for('brief.subscribe'))

    # GET request - show subscription form
    return render_template('brief/subscribe.html')


@brief_bp.route('/brief/subscribe/success')
def subscribe_success():
    """Subscription confirmation page"""
    return render_template('brief/subscribe_success.html')


@brief_bp.route('/brief/subscribe/inline', methods=['POST'])
@limiter.limit("5 per minute")
def subscribe_inline():
    """Inline subscription from email capture forms (AJAX-friendly)"""
    email = request.form.get('email', '').strip().lower()
    source = request.form.get('source', 'inline')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # Validate email
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        if is_ajax:
            return jsonify({'success': False, 'error': 'Please enter a valid email address.'}), 400
        flash('Please enter a valid email address.', 'error')
        return redirect(request.referrer or url_for('brief.today'))

    # Process subscription using shared helper
    # Note: update_preferences_on_reactivate=False to keep existing preferences
    result = _process_subscription(
        email=email,
        timezone='UTC',
        preferred_hour=DEFAULT_SEND_HOUR,
        update_preferences_on_reactivate=False,
        set_session=True,
        track_posthog=False,
        source=source
    )

    # Handle result with inline-specific messages and responses
    if result['status'] == 'already_active':
        if is_ajax:
            return jsonify({'success': True, 'message': "You're already subscribed!"})
        flash("You're already subscribed to the Daily Brief!", 'info')
        return redirect(request.referrer or url_for('brief.today'))

    elif result['status'] == 'reactivated':
        if is_ajax:
            return jsonify({'success': True, 'message': 'Welcome back! Check your inbox.'})
        flash('Welcome back! Your subscription has been reactivated.', 'success')
        return redirect(request.referrer or url_for('brief.today'))

    elif result['status'] == 'created':
        if is_ajax:
            return jsonify({'success': True, 'message': "You're subscribed! Check your inbox."})
        flash("You're subscribed! Check your inbox for the welcome email.", 'success')
        return redirect(request.referrer or url_for('brief.today'))

    else:  # error
        if is_ajax:
            return jsonify({'success': False, 'error': 'Something went wrong. Please try again.'}), 500
        flash('Something went wrong. Please try again.', 'error')
        return redirect(request.referrer or url_for('brief.today'))


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


@brief_bp.route('/brief/preferences/<token>', methods=['GET', 'POST'])
def manage_preferences(token):
    """Manage subscriber preferences (timezone, send hour)"""
    # Use safe token lookup (prevents timing attacks by using constant-time comparison internally)
    subscriber = DailyBriefSubscriber.query.filter_by(magic_token=token).first()

    if not subscriber:
        flash('Invalid preferences link. Please use the link from your email.', 'error')
        return redirect(url_for('brief.subscribe'))
    
    # Check token expiration for security (but allow unsubscribed users to manage preferences)
    if subscriber.magic_token_expires and subscriber.magic_token_expires < datetime.utcnow():
        # Regenerate token for active subscribers
        if subscriber.status == 'active':
            subscriber.generate_magic_token(expires_hours=PREFERENCES_TOKEN_EXPIRE_HOURS)
            db.session.commit()
        flash('Your link has expired. Please check your latest email for a new link.', 'warning')
        return redirect(url_for('brief.today'))

    if request.method == 'POST':
        # Update timezone
        new_timezone = request.form.get('timezone', 'UTC')
        # Validate timezone
        try:
            pytz.timezone(new_timezone)
            subscriber.timezone = new_timezone
        except Exception:
            subscriber.timezone = 'UTC'

        # Update send hour
        new_hour = request.form.get('preferred_send_hour', str(DEFAULT_SEND_HOUR))
        try:
            hour = int(new_hour)
            if hour in VALID_SEND_HOURS:
                subscriber.preferred_send_hour = hour
        except (ValueError, TypeError):
            pass

        # Handle resubscribe
        if request.form.get('resubscribe') and subscriber.status == 'unsubscribed':
            subscriber.status = 'active'
            subscriber.unsubscribed_at = None
            flash('Welcome back! You have been resubscribed to the Daily Brief.', 'success')
        
        db.session.commit()
        flash('Your preferences have been updated.', 'success')
        return redirect(url_for('brief.manage_preferences', token=token))

    # Common timezones for dropdown
    common_timezones = [
        ('UTC', 'UTC (Coordinated Universal Time)'),
        ('America/New_York', 'Eastern Time (US)'),
        ('America/Chicago', 'Central Time (US)'),
        ('America/Denver', 'Mountain Time (US)'),
        ('America/Los_Angeles', 'Pacific Time (US)'),
        ('Europe/London', 'London (GMT/BST)'),
        ('Europe/Paris', 'Paris (CET/CEST)'),
        ('Europe/Berlin', 'Berlin (CET/CEST)'),
        ('Asia/Tokyo', 'Tokyo (JST)'),
        ('Asia/Shanghai', 'Shanghai (CST)'),
        ('Asia/Singapore', 'Singapore (SGT)'),
        ('Australia/Sydney', 'Sydney (AEST/AEDT)'),
    ]

    return render_template(
        'brief/preferences.html',
        subscriber=subscriber,
        token=token,
        common_timezones=common_timezones
    )


@brief_bp.route('/brief/methodology')
def methodology():
    """Explain how the brief works"""
    return render_template('brief/methodology.html')


@brief_bp.route('/api/brief/<int:brief_id>/audio/generate', methods=['POST'])
@csrf.exempt
@limiter.limit("5 per minute")
@admin_required
def generate_brief_audio(brief_id):
    """
    Create batch audio generation job for entire brief.

    Requires admin authentication - audio generation is resource-intensive
    and should be protected from abuse.
    """
    from app.brief.audio_generator import audio_generator

    brief = DailyBrief.query.get_or_404(brief_id)

    # Get voice ID from request (optional)
    data = request.get_json() or {}
    voice_id = data.get('voice_id')

    # Create generation job
    job = audio_generator.create_generation_job(brief_id, voice_id=voice_id)

    if not job:
        return jsonify({'error': 'Failed to create audio generation job'}), 500

    return jsonify({
        'success': True,
        'job_id': job.id,
        'status': job.status,
        'total_items': job.total_items
    })


@brief_bp.route('/api/brief/audio/job/<int:job_id>/status')
@limiter.limit("30 per minute")
def get_audio_job_status(job_id):
    """Get status of audio generation job"""
    from app.brief.audio_generator import audio_generator
    from app.models import AudioGenerationJob
    
    job = AudioGenerationJob.query.get_or_404(job_id)
    
    return jsonify(job.to_dict())


@brief_bp.route('/audio/<filename>')
@limiter.limit("60 per minute")
def serve_audio(filename):
    """Serve audio files from storage"""
    from app.brief.audio_storage import audio_storage
    from flask import Response
    
    # Security: validate filename to prevent path traversal
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    # Additional validation: ensure filename matches expected pattern
    # Format: brief_{brief_id}_item_{item_id}_{timestamp}_{hash}.wav
    # Or: brief_run_{run_id}_item_{item_id}_{timestamp}_{hash}.wav
    import re
    expected_pattern = r'^brief(_run)?_\d+_item_\d+_\d{8}_\d{6}_[a-f0-9]{8}\.(wav|mp3)$'
    if not re.match(expected_pattern, filename):
        logger.warning(f"Suspicious filename pattern: {filename}")
        # Still allow it for backward compatibility, but log for monitoring
    
    try:
        audio_data = audio_storage.get(filename)
        
        if not audio_data:
            return jsonify({'error': 'Audio not found'}), 404
        
        # Determine content type from extension
        if filename.endswith('.wav'):
            mimetype = 'audio/wav'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'audio/wav'  # Default
        
        return Response(
            audio_data,
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'inline; filename="{filename}"',
                'Cache-Control': 'public, max-age=31536000'  # Cache for 1 year
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to serve audio: {e}")
        return jsonify({'error': 'Failed to serve audio'}), 500


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


@brief_bp.route('/brief/admin/test-send', methods=['POST'])
@admin_required
def admin_test_send():
    """Send a test brief email (admin only, development use)"""
    import secrets

    data = request.get_json() or {}
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email required'}), 400

    # Get or create the subscriber
    subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
    if not subscriber:
        subscriber = DailyBriefSubscriber(
            email=email,
            status='active',
            tier='trial',
            timezone='Europe/London',
            preferred_send_hour=8,
            magic_token=secrets.token_urlsafe(32),
            trial_ends_at=datetime.utcnow() + timedelta(days=14)
        )
        db.session.add(subscriber)
        db.session.commit()
        logger.info(f"Created test subscriber: {email}")

    # Get or create a test brief
    today = date.today()
    brief = DailyBrief.query.filter_by(date=today).first()

    if not brief:
        # Create a sample brief for testing
        brief = DailyBrief(
            date=today,
            title=f"Tuesday's Brief: AI, Climate, Democracy",
            intro_text="Today we look at three stories shaping public discourse: advances in AI governance, climate policy debates, and democratic participation trends. Each story includes coverage from multiple perspectives.",
            status='published',
            auto_selected=True
        )
        db.session.add(brief)
        db.session.flush()

        # Add sample items
        sample_items = [
            {
                'headline': 'AI Safety Summit Sets New International Standards',
                'summary_bullets': [
                    'World leaders agreed on voluntary AI safety protocols at the summit.',
                    'The framework addresses both near-term risks and long-term existential concerns.',
                    'Tech companies committed to pre-deployment testing for high-risk systems.'
                ],
                'source_count': 12,
                'coverage_distribution': {'left': 0.35, 'center': 0.40, 'right': 0.25},
                'sources_by_leaning': {'left': ['Guardian', 'Vox'], 'center': ['BBC', 'Reuters'], 'right': ['WSJ']}
            },
            {
                'headline': 'Climate Finance Debate Heats Up Ahead of COP',
                'summary_bullets': [
                    'Developing nations push for $1 trillion annual climate fund.',
                    'Rich countries resist binding commitments, propose private sector solutions.',
                    'Small island states warn of existential threat without immediate action.'
                ],
                'source_count': 8,
                'coverage_distribution': {'left': 0.45, 'center': 0.30, 'right': 0.25},
                'sources_by_leaning': {'left': ['Guardian'], 'center': ['AP', 'BBC'], 'right': ['Telegraph']}
            },
            {
                'headline': 'Voter Turnout Trends Signal Shifting Democratic Engagement',
                'summary_bullets': [
                    'Youth voter registration up 15% in key battleground areas.',
                    'Mail-in voting preferences vary significantly by party affiliation.',
                    'New voting laws spark debate over access versus security.'
                ],
                'source_count': 6,
                'coverage_distribution': {'left': 0.30, 'center': 0.35, 'right': 0.35},
                'sources_by_leaning': {'left': ['NPR'], 'center': ['PBS'], 'right': ['Fox News']}
            }
        ]

        for i, item_data in enumerate(sample_items, start=1):
            item = BriefItem(
                brief_id=brief.id,
                position=i,
                headline=item_data['headline'],
                summary_bullets=item_data['summary_bullets'],
                source_count=item_data['source_count'],
                coverage_distribution=item_data['coverage_distribution'],
                sources_by_leaning=item_data['sources_by_leaning']
            )
            db.session.add(item)

        db.session.commit()
        logger.info(f"Created test brief for {today}")

    # Send the email
    try:
        client = ResendClient()
        success = client.send_brief(subscriber, brief)

        if success:
            return jsonify({
                'success': True,
                'message': f'Test brief sent to {email}',
                'brief_title': brief.title
            })
        else:
            return jsonify({'error': 'Failed to send email'}), 500

    except Exception as e:
        logger.error(f"Test send failed: {e}")
        return jsonify({'error': str(e)}), 500


@brief_bp.route('/brief/webhooks/resend', methods=['POST'])
def resend_webhook():
    """
    Unified Resend webhook handler for ALL email types.
    
    Resend sends events: email.sent, email.delivered, email.opened,
    email.clicked, email.bounced, email.complained
    
    Uses EmailAnalytics service for DRY event processing.
    
    Docs: https://resend.com/docs/dashboard/webhooks/introduction
    """
    from app.lib.email_analytics import EmailAnalytics
    
    try:
        # Verify webhook signature (Resend uses svix for webhooks)
        webhook_secret = os.environ.get('RESEND_WEBHOOK_SECRET')

        # Check for both None and empty string
        if webhook_secret and webhook_secret.strip():
            # Get signature headers from Resend/Svix
            svix_id = request.headers.get('svix-id')
            svix_timestamp = request.headers.get('svix-timestamp')
            svix_signature = request.headers.get('svix-signature')

            if not all([svix_id, svix_timestamp, svix_signature]):
                logger.warning("Missing webhook signature headers")
                return jsonify({'error': 'Missing signature headers'}), 401

            # Guard against empty string headers
            if not svix_signature.strip():
                logger.warning("Empty webhook signature header")
                return jsonify({'error': 'Empty signature header'}), 401

            # Verify signature using HMAC-SHA256
            payload_bytes = request.get_data()
            signed_content = f"{svix_id}.{svix_timestamp}.{payload_bytes.decode('utf-8')}"

            # Extract the base64 encoded secret
            secret_bytes = webhook_secret.encode('utf-8')
            if webhook_secret.startswith('whsec_'):
                secret_bytes = base64.b64decode(webhook_secret[6:])

            expected_sig = hmac.new(
                secret_bytes,
                signed_content.encode('utf-8'),
                hashlib.sha256
            ).digest()

            expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode('utf-8')
            
            # Svix sends signatures as "v1,<sig> v1,<sig2>" or just "v1,<sig>"
            signatures = svix_signature.split(' ')
            valid = False
            for sig_entry in signatures:
                if ',' in sig_entry:
                    version, sig_value = sig_entry.split(',', 1)
                    standard_sig = base64.b64encode(expected_sig).decode('utf-8')
                    if hmac.compare_digest(sig_value, expected_sig_b64) or hmac.compare_digest(sig_value, standard_sig):
                        valid = True
                        break
            
            if not valid:
                logger.warning(f"Invalid webhook signature")
                return jsonify({'error': 'Invalid signature'}), 401
        
        # Get webhook payload
        payload = request.get_json()
        
        if not payload:
            logger.warning("Empty webhook payload received")
            return jsonify({'status': 'ignored'}), 200
        
        event_type = payload.get('type')
        if not event_type:
            return jsonify({'status': 'ignored'}), 200
        
        logger.info(f"Resend webhook received: {event_type}")
        
        # Use unified EmailAnalytics service (DRY)
        event = EmailAnalytics.record_from_webhook(payload)
        
        # Update subscriber metrics in a separate transaction for isolation
        try:
            data = payload.get('data', {})
            to_list = data.get('to', [])
            to_email = to_list[0] if to_list else None
            
            if to_email:
                subscriber = DailyBriefSubscriber.query.filter_by(email=to_email).first()
                if subscriber:
                    normalized_type = event_type.replace('email.', '')
                    if normalized_type == 'opened':
                        subscriber.total_opens = (subscriber.total_opens or 0) + 1
                        subscriber.last_opened_at = datetime.utcnow()
                    elif normalized_type == 'clicked':
                        subscriber.total_clicks = (subscriber.total_clicks or 0) + 1
                        subscriber.last_clicked_at = datetime.utcnow()
                    db.session.commit()
        except Exception as sub_error:
            logger.warning(f"Failed to update subscriber metrics (non-fatal): {sub_error}")
            db.session.rollback()
        
        return jsonify({'status': 'processed'}), 200
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@brief_bp.route('/brief/admin/analytics')
@admin_required
def admin_analytics():
    """
    Unified email analytics dashboard.
    Uses EmailAnalytics service for DRY stats retrieval.
    """
    from app.lib.email_analytics import EmailAnalytics
    
    # Get filter params
    category_filter = request.args.get('category', None)
    days = request.args.get('days', 7, type=int)
    
    # Get unified stats using DRY service
    dashboard_stats = EmailAnalytics.get_dashboard_stats(days=days)
    
    # Get recent events (optionally filtered - pass None explicitly if no filter)
    recent_events = EmailAnalytics.get_recent_events(category=category_filter if category_filter else None, limit=50)
    
    # Get stats for selected category or overall
    if category_filter:
        stats = dashboard_stats['by_category'].get(category_filter, dashboard_stats['overall'])
    else:
        stats = dashboard_stats['overall']
    
    return render_template(
        'admin/email_analytics.html',
        stats=stats,
        dashboard_stats=dashboard_stats,
        recent_events=recent_events,
        category_filter=category_filter,
        days=days,
        categories={
            'auth': 'Authentication',
            'daily_brief': 'Daily Brief',
            'daily_question': 'Daily Question',
            'discussion': 'Discussion Notifications'
        }
    )
