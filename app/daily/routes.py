from flask import render_template, redirect, url_for, flash, request, jsonify, session, current_app, make_response
from flask_login import current_user, login_user
from datetime import date, datetime, timedelta
from app.daily import daily_bp
from app.daily.constants import (
    VOTE_MAP, VOTE_TO_POSITION, VOTE_LABELS, VOTE_EMOJIS,
    VOTE_GRACE_PERIOD_DAYS, VALID_UNSUBSCRIBE_REASONS, 
    VALID_VISIBILITY_OPTIONS, DEFAULT_EMAIL_VOTE_VISIBILITY
)
from app import db, limiter
from app.models import DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber, User, Discussion, DiscussionParticipant
import hashlib
import re
import secrets

DAILY_CLIENT_COOKIE_NAME = 'daily_client_id'
DAILY_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def get_source_articles(question, limit=5):
    """Get source articles from the source discussion if available.
    
    Uses a direct query with eager loading to prevent N+1 queries when
    accessing article.source.name in templates.
    """
    from app.models import DiscussionSourceArticle, NewsArticle
    from sqlalchemy.orm import joinedload
    
    if not question.source_discussion_id:
        return []
    
    # Query directly with eager loading to prevent N+1
    links = DiscussionSourceArticle.query.options(
        joinedload(DiscussionSourceArticle.article)
        .joinedload(NewsArticle.source)
    ).filter_by(
        discussion_id=question.source_discussion_id
    ).limit(limit).all()
    
    return [link.article for link in links if link.article]


def get_related_discussions(question, limit=3):
    """Get related discussions for exploration after voting"""
    related = []
    
    if question.source_discussion:
        source_topic = question.source_discussion.topic
        if source_topic:
            related = Discussion.query.filter(
                Discussion.topic == source_topic,
                Discussion.id != question.source_discussion_id,
                Discussion.has_native_statements == True
            ).order_by(Discussion.created_at.desc()).limit(limit).all()
    
    if len(related) < limit:
        needed = limit - len(related)
        exclude_ids = [d.id for d in related]
        if question.source_discussion_id:
            exclude_ids.append(question.source_discussion_id)
        
        query = Discussion.query.filter(
            Discussion.has_native_statements == True
        )
        if exclude_ids:
            query = query.filter(Discussion.id.notin_(exclude_ids))
        
        more = query.order_by(Discussion.created_at.desc()).limit(needed).all()
        related.extend(more)
    
    return related


def get_or_create_client_id():
    """Get the long-lived client ID from cookie, or generate a new one.
    
    Returns a tuple of (client_id, is_new) where is_new indicates if we need to set the cookie.
    """
    client_id = request.cookies.get(DAILY_CLIENT_COOKIE_NAME)
    if client_id and len(client_id) == 64:
        return client_id, False
    new_id = secrets.token_hex(32)
    return new_id, True


def get_session_fingerprint():
    """Generate a unique fingerprint for anonymous users.
    
    Uses a long-lived client ID cookie as the primary identifier to survive session restarts.
    This prevents both:
    1. Fingerprint collisions (multiple users getting the same fingerprint)
    2. Easy vote duplication (clearing session cookies to vote again)
    
    The client ID is stored in a separate long-lived cookie that persists for 1 year.
    Always regenerates from the client_id cookie to ensure consistency across session restarts.
    """
    client_id, is_new = get_or_create_client_id()
    fingerprint = hashlib.sha256(client_id.encode()).hexdigest()
    
    if session.get('daily_fingerprint') != fingerprint:
        session['daily_fingerprint'] = fingerprint
        session.modified = True
    
    return fingerprint


def set_client_id_cookie_if_needed(response):
    """Set the long-lived client ID cookie if it doesn't exist or needs refresh."""
    client_id, is_new = get_or_create_client_id()
    if is_new:
        response.set_cookie(
            DAILY_CLIENT_COOKIE_NAME,
            client_id,
            max_age=DAILY_CLIENT_COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite='Lax'
        )
    return response


@daily_bp.after_request
def after_request_set_client_cookie(response):
    """Automatically set the long-lived client ID cookie on all daily blueprint responses."""
    if not current_user.is_authenticated:
        return set_client_id_cookie_if_needed(response)
    return response


def has_user_voted(daily_question):
    """Check if current user/session has already voted on this question"""
    if current_user.is_authenticated:
        return DailyQuestionResponse.query.filter_by(
            daily_question_id=daily_question.id,
            user_id=current_user.id
        ).first() is not None
    else:
        fingerprint = get_session_fingerprint()
        return DailyQuestionResponse.query.filter_by(
            daily_question_id=daily_question.id,
            session_fingerprint=fingerprint
        ).first() is not None


def get_user_response(daily_question):
    """Get current user's response if exists"""
    if current_user.is_authenticated:
        return DailyQuestionResponse.query.filter_by(
            daily_question_id=daily_question.id,
            user_id=current_user.id
        ).first()
    else:
        fingerprint = get_session_fingerprint()
        return DailyQuestionResponse.query.filter_by(
            daily_question_id=daily_question.id,
            session_fingerprint=fingerprint
        ).first()


def get_discussion_participation_data(question):
    """
    Get user's participation data for the linked discussion.
    Used to show progress toward unlocking consensus analysis.
    
    Returns dict with:
    - vote_count: number of statements voted on
    - votes_needed: votes needed to unlock consensus (0 if already unlocked)
    - total_statements: total statements in discussion
    - participant_count: total participants in discussion
    """
    from app.models import StatementVote, Statement
    from app.discussions.consensus import PARTICIPATION_THRESHOLD
    
    if not question.source_discussion_id:
        return None
    
    discussion = question.source_discussion
    if not discussion:
        return None
    
    # Get vote count for this user in the discussion
    vote_count = 0
    fingerprint = get_session_fingerprint()
    
    if current_user.is_authenticated:
        vote_count = StatementVote.query.filter_by(
            discussion_id=question.source_discussion_id,
            user_id=current_user.id
        ).count()
        
        # Also count fingerprint votes (for pre-login votes)
        if fingerprint:
            fingerprint_count = StatementVote.query.filter_by(
                discussion_id=question.source_discussion_id,
                session_fingerprint=fingerprint
            ).filter(StatementVote.user_id.is_(None)).count()
            vote_count += fingerprint_count
    elif fingerprint:
        vote_count = StatementVote.query.filter_by(
            discussion_id=question.source_discussion_id,
            session_fingerprint=fingerprint
        ).count()
    
    # Count total statements and participants
    total_statements = Statement.query.filter_by(
        discussion_id=question.source_discussion_id
    ).count()
    
    participant_count = db.session.query(
        db.func.count(db.distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id == question.source_discussion_id,
        StatementVote.user_id.isnot(None)
    ).scalar() or 0
    
    # Add anonymous participants
    anon_count = db.session.query(
        db.func.count(db.distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id == question.source_discussion_id,
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0
    
    participant_count += anon_count
    
    votes_needed = max(0, PARTICIPATION_THRESHOLD - vote_count)
    
    return {
        'vote_count': vote_count,
        'votes_needed': votes_needed,
        'threshold': PARTICIPATION_THRESHOLD,
        'total_statements': total_statements,
        'participant_count': participant_count,
        'is_unlocked': votes_needed == 0
    }


@daily_bp.route('/daily')
def today():
    """Display today's daily question"""
    question = DailyQuestion.get_today()
    
    if not question:
        # Fallback: try to auto-publish if scheduler missed (e.g., autoscale cold start)
        try:
            from app.daily.auto_selection import auto_publish_todays_question
            question = auto_publish_todays_question()
            if question:
                current_app.logger.info(f"Fallback auto-published daily question #{question.question_number}")
        except Exception as e:
            current_app.logger.error(f"Fallback auto-publish failed: {e}")
    
    if not question:
        return render_template('daily/no_question.html')
    
    user_response = get_user_response(question)
    has_voted = user_response is not None
    
    if has_voted:
        participation_data = get_discussion_participation_data(question)
        public_reasons = get_public_reasons(question)
        return render_template('daily/results.html',
                             question=question,
                             user_response=user_response,
                             stats=question.vote_percentages,
                             is_cold_start=question.is_cold_start,
                             early_signal=question.early_signal_message,
                             share_snippet=generate_share_snippet(question, user_response),
                             source_discussion=question.source_discussion,
                             source_articles=get_source_articles(question),
                             related_discussions=get_related_discussions(question),
                             participation=participation_data,
                             public_reasons=public_reasons)
    else:
        return render_template('daily/question.html',
                             question=question)


@daily_bp.route('/daily/<date_str>')
def by_date(date_str):
    """Display daily question for a specific date (permalink)"""
    try:
        question_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Invalid date format. Please use YYYY-MM-DD.", "warning")
        return redirect(url_for('daily.today'))
    
    question = DailyQuestion.get_by_date(question_date)
    
    if not question:
        return render_template('daily/no_question.html', 
                             specific_date=question_date)
    
    is_today = question_date == date.today()
    user_response = get_user_response(question)
    has_voted = user_response is not None
    
    if has_voted or not is_today:
        participation_data = get_discussion_participation_data(question)
        public_reasons = get_public_reasons(question)
        return render_template('daily/results.html',
                             question=question,
                             user_response=user_response,
                             stats=question.vote_percentages,
                             is_cold_start=question.is_cold_start,
                             early_signal=question.early_signal_message,
                             share_snippet=generate_share_snippet(question, user_response) if user_response else None,
                             is_past=not is_today,
                             source_discussion=question.source_discussion,
                             source_articles=get_source_articles(question),
                             related_discussions=get_related_discussions(question),
                             participation=participation_data,
                             public_reasons=public_reasons)
    else:
        return render_template('daily/question.html',
                             question=question)


@daily_bp.route('/daily/api/status')
def api_status():
    """API endpoint to check current question status"""
    question = DailyQuestion.get_today()
    
    if not question:
        return jsonify({'has_question': False})
    
    has_voted = has_user_voted(question)
    
    response_data = {
        'has_question': True,
        'question_number': question.question_number,
        'question_date': question.question_date.isoformat(),
        'has_voted': has_voted
    }
    
    if has_voted:
        response_data['stats'] = question.vote_percentages
        response_data['is_cold_start'] = question.is_cold_start
    
    return jsonify(response_data)


def generate_share_snippet(question, user_response):
    """Generate share snippet for social media"""
    if not user_response:
        return None
    
    base_url = current_app.config.get('SITE_URL', 'https://societyspeaks.io')
    permalink = f"{base_url}/daily/{question.question_date.isoformat()}"
    
    emoji = user_response.vote_emoji
    
    text = f"""Society Speaks – Daily Question #{question.question_number} ({question.question_date.strftime('%Y-%m-%d')})
{emoji}
{permalink}"""
    
    return {
        'text': text,
        'emoji': emoji,
        'question_number': question.question_number,
        'date': question.question_date.strftime('%Y-%m-%d'),
        'permalink': permalink,
        'vote_label': user_response.vote_label
    }


def sync_daily_reason_to_statement(statement_id, user_id, vote, reason, is_anonymous=False, session_fingerprint=None):
    """
    Sync a daily question reason to a statement response.
    Updates existing response or creates new one to prevent duplicates.
    Now supports anonymous responses from email subscribers.

    Args:
        statement_id: ID of the statement to add response to
        user_id: ID of the user submitting the response (None for anonymous)
        vote: Vote value (1=agree, -1=disagree, 0=unsure)
        reason: The reason/response text
        is_anonymous: Whether the response should be marked as anonymous
        session_fingerprint: Session fingerprint for anonymous users (optional)

    Returns:
        tuple: (Response object, is_new boolean)
    """
    from app.models import Response

    # Check if user/session already has a response on this statement
    if user_id:
        existing_response = Response.query.filter_by(
            statement_id=statement_id,
            user_id=user_id
        ).first()
    elif session_fingerprint:
        existing_response = Response.query.filter_by(
            statement_id=statement_id,
            session_fingerprint=session_fingerprint
        ).first()
    else:
        # No user_id or fingerprint - can't check for duplicates, create new
        existing_response = None

    position = VOTE_TO_POSITION.get(vote, 'neutral')

    if existing_response:
        # Update existing response content instead of creating duplicate
        existing_response.content = reason
        existing_response.position = position
        existing_response.is_anonymous = is_anonymous
        current_app.logger.info(
            f"Daily question reason updated existing response on statement {statement_id} "
            f"(anonymous={is_anonymous})"
        )
        return existing_response, False
    else:
        # Create new Response for the linked statement
        statement_response = Response(
            statement_id=statement_id,
            user_id=user_id,
            session_fingerprint=session_fingerprint,
            position=position,
            content=reason,
            is_anonymous=is_anonymous
        )
        db.session.add(statement_response)
        current_app.logger.info(
            f"Daily question reason synced as response to statement {statement_id} "
            f"(anonymous={is_anonymous}, user_id={user_id}, has_fingerprint={bool(session_fingerprint)})"
        )
        return statement_response, True


def get_public_reasons(question, limit=10):
    """Get public reasons from other users for this question."""
    reasons = DailyQuestionResponse.query.filter(
        DailyQuestionResponse.daily_question_id == question.id,
        DailyQuestionResponse.reason.isnot(None),
        DailyQuestionResponse.reason != '',
        DailyQuestionResponse.reason_visibility.in_(['public_named', 'public_anonymous'])
    ).order_by(DailyQuestionResponse.created_at.desc()).limit(limit).all()
    return reasons


def sync_vote_to_statement(question, vote_value, fingerprint):
    """
    Sync a daily question vote to the linked statement in the discussion.
    
    Args:
        question: DailyQuestion object with source_statement_id and source_discussion_id
        vote_value: Vote value (1=agree, -1=disagree, 0=unsure)
        fingerprint: Session fingerprint for anonymous users
        
    Returns:
        tuple: (created_new_vote: bool, updated_existing: bool)
    """
    from app.models import StatementVote, Statement
    
    if not question.source_statement_id or not question.source_discussion_id:
        return False, False
    
    statement = Statement.query.get(question.source_statement_id)
    if not statement:
        return False, False
    
    # Check for existing statement vote
    existing_vote = None
    if current_user.is_authenticated:
        existing_vote = StatementVote.query.filter_by(
            statement_id=question.source_statement_id,
            user_id=current_user.id
        ).first()
    elif fingerprint:
        existing_vote = StatementVote.query.filter_by(
            statement_id=question.source_statement_id,
            session_fingerprint=fingerprint
        ).first()
    
    if existing_vote:
        # Update existing vote if different
        old_vote = existing_vote.vote
        if old_vote != vote_value:
            # Adjust counts
            if old_vote == 1:
                statement.vote_count_agree = max(0, (statement.vote_count_agree or 0) - 1)
            elif old_vote == -1:
                statement.vote_count_disagree = max(0, (statement.vote_count_disagree or 0) - 1)
            elif old_vote == 0:
                statement.vote_count_unsure = max(0, (statement.vote_count_unsure or 0) - 1)
            
            if vote_value == 1:
                statement.vote_count_agree = (statement.vote_count_agree or 0) + 1
            elif vote_value == -1:
                statement.vote_count_disagree = (statement.vote_count_disagree or 0) + 1
            else:
                statement.vote_count_unsure = (statement.vote_count_unsure or 0) + 1
            
            existing_vote.vote = vote_value
            return False, True
        return False, False
    else:
        # Create new statement vote
        stmt_vote = StatementVote(
            statement_id=question.source_statement_id,
            discussion_id=question.source_discussion_id,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=fingerprint if not current_user.is_authenticated else None,
            vote=vote_value
        )
        db.session.add(stmt_vote)
        
        # Update statement vote counts
        if vote_value == 1:
            statement.vote_count_agree = (statement.vote_count_agree or 0) + 1
        elif vote_value == -1:
            statement.vote_count_disagree = (statement.vote_count_disagree or 0) + 1
        else:
            statement.vote_count_unsure = (statement.vote_count_unsure or 0) + 1
        
        return True, False


@daily_bp.route('/daily/subscribe', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def subscribe():
    """Email subscription signup for daily questions"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('Please enter a valid email address.', 'error')
            return redirect(url_for('daily.subscribe'))
        
        existing = DailyQuestionSubscriber.query.filter_by(email=email).first()
        if existing:
            if existing.is_active:
                flash('This email is already subscribed to daily questions.', 'info')
            else:
                existing.is_active = True
                existing.generate_magic_token()
                db.session.commit()
                flash('Welcome back! Your subscription has been reactivated.', 'success')
            return redirect(url_for('daily.subscribe_success'))
        
        user = User.query.filter_by(email=email).first()
        
        try:
            subscriber = DailyQuestionSubscriber(
                email=email,
                user_id=user.id if user else None
            )
            subscriber.generate_magic_token()
            db.session.add(subscriber)
            db.session.commit()
            
            from app.resend_client import send_daily_question_welcome_email
            send_daily_question_welcome_email(subscriber)
            
            flash('You have successfully subscribed to daily civic questions!', 'success')
            return redirect(url_for('daily.subscribe_success'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating daily subscriber: {e}")
            flash('There was an error processing your subscription. Please try again.', 'error')
    
    return render_template('daily/subscribe.html')


@daily_bp.route('/daily/subscribe/success')
def subscribe_success():
    """Subscription confirmation page"""
    return render_template('daily/subscribe_success.html')


@daily_bp.route('/daily/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    """Unsubscribe from daily question emails with optional reason tracking"""
    subscriber = DailyQuestionSubscriber.query.filter_by(magic_token=token).first()

    if not subscriber:
        flash('Invalid unsubscribe link.', 'error')
        return redirect(url_for('daily.today'))

    # If already unsubscribed, just show confirmation
    if not subscriber.is_active:
        return render_template('daily/unsubscribed.html', email=subscriber.email)

    # GET: Show unsubscribe confirmation form with reason options
    if request.method == 'GET':
        return render_template('daily/unsubscribe_confirm.html',
                             email=subscriber.email,
                             token=token)

    # POST: Process unsubscribe with reason
    reason = request.form.get('reason', 'not_specified')

    # Validate reason using constants
    if reason not in VALID_UNSUBSCRIBE_REASONS:
        reason = 'not_specified'

    # Update database (source of truth for subscription status)
    subscriber.is_active = False
    subscriber.unsubscribe_reason = reason
    subscriber.unsubscribed_at = datetime.utcnow()
    db.session.commit()

    current_app.logger.info(
        f"Subscriber {subscriber.id} ({subscriber.email}) unsubscribed. Reason: {reason}"
    )

    # Note: With Resend, unsubscribe is handled by List-Unsubscribe headers
    # and our database is the source of truth. No external API call needed.

    flash('You have been unsubscribed from daily civic questions.', 'success')
    return render_template('daily/unsubscribed.html', email=subscriber.email)


@daily_bp.route('/daily/m/<token>')
def magic_link(token):
    """Magic link access for email subscribers - allows voting without login"""
    subscriber = DailyQuestionSubscriber.verify_magic_token(token)
    
    if not subscriber:
        flash('This link has expired or is invalid. Please subscribe again.', 'warning')
        return redirect(url_for('daily.subscribe'))
    
    session['daily_subscriber_id'] = subscriber.id
    session['daily_subscriber_token'] = token
    session.modified = True
    
    if subscriber.user:
        login_user(subscriber.user)
    
    return redirect(url_for('daily.today'))


@daily_bp.route('/daily/v/<token>/<vote_choice>', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def one_click_vote(token, vote_choice):
    """One-click vote from email - shows confirmation page (GET) then records vote (POST).

    Bot protection:
    - Two-step process: GET shows confirmation, POST records vote
    - This prevents mail scanners/link prefetchers from registering votes
    - Rate limiting (10/min)
    - Token validation (expires in 7 days)
    - Question-specific tokens prevent voting on wrong question
    """
    from app.models import StatementVote, Statement

    # Validate vote choice using constants
    if vote_choice not in VOTE_MAP:
        flash('Invalid vote option.', 'error')
        return redirect(url_for('daily.today'))

    # Verify subscriber token and extract question_id (returns differentiated errors)
    subscriber, email_question_id, error = DailyQuestionSubscriber.verify_vote_token(token)
    
    if error:
        # Provide user-friendly error messages based on error type
        error_messages = {
            'expired': 'This vote link has expired. Please check your latest email for today\'s question.',
            'invalid': 'This vote link is invalid. Please use the link from your email.',
            'invalid_type': 'This link cannot be used for voting. Please check your latest email.',
            'subscriber_not_found': 'Your subscription was not found. Please subscribe again.'
        }
        flash(error_messages.get(error, 'This vote link is invalid.'), 'warning')
        return redirect(url_for('daily.subscribe') if error == 'subscriber_not_found' else url_for('daily.today'))

    # Set up session
    session['daily_subscriber_id'] = subscriber.id
    session.modified = True

    # Log in if user has account
    if subscriber.user:
        login_user(subscriber.user)

    # Get the specific question this email was about
    question = DailyQuestion.query.get(email_question_id)
    if not question:
        flash('This question is no longer available.', 'info')
        return redirect(url_for('daily.today'))

    # Check if question is in the future (shouldn't happen, but handle edge case)
    today = date.today()
    if question.question_date > today:
        flash('This question isn\'t available yet. Please check back later.', 'info')
        return redirect(url_for('daily.today'))

    # Check if question is still current (within grace period)
    if question.question_date < (today - timedelta(days=VOTE_GRACE_PERIOD_DAYS)):
        flash(f'This question expired on {question.question_date}. Please check today\'s question!', 'info')
        return redirect(url_for('daily.today'))
    
    # Check if already voted
    if has_user_voted(question):
        flash('You have already voted on this question.', 'info')
        return redirect(url_for('daily.today'))
    
    # GET request: Show confirmation page (prevents mail scanner prefetch from voting)
    if request.method == 'GET':
        return render_template('daily/confirm_vote.html',
                             question=question,
                             vote_choice=vote_choice,
                             vote_label=VOTE_LABELS.get(VOTE_MAP.get(vote_choice), vote_choice.title()),
                             vote_emoji=VOTE_EMOJIS.get(vote_choice, ''),
                             token=token)
    
    # POST request: Record the vote
    try:
        fingerprint = get_session_fingerprint()
        new_vote = VOTE_MAP[vote_choice]

        # Create the daily question response (no reason yet - that comes after)
        response = DailyQuestionResponse(
            daily_question_id=question.id,
            email_question_id=email_question_id,  # Track which question the email was about
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=fingerprint if not current_user.is_authenticated else None,
            vote=new_vote,
            reason=None,
            reason_visibility=DEFAULT_EMAIL_VOTE_VISIBILITY,
            voted_via_email=True
        )
        db.session.add(response)

        # Sync vote to statement if linked to discussion (uses shared helper)
        sync_vote_to_statement(question, new_vote, fingerprint)

        # Update subscriber streak
        subscriber.update_participation_streak(has_reason=False)

        db.session.commit()

        current_app.logger.info(
            f"One-click email vote recorded: {vote_choice} for question #{question.question_number} "
            f"(email_q#{email_question_id}) by subscriber {subscriber.id}"
        )

        flash('Vote recorded! Share your reasoning below if you\'d like.', 'success')
        return redirect(url_for('daily.today'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing one-click vote: {e}", exc_info=True)
        flash('There was an error recording your vote. Please try again.', 'error')
        return redirect(url_for('daily.today'))


@daily_bp.route('/daily/vote', methods=['POST'])
@limiter.limit("10 per minute")
def vote():
    """Submit a vote for today's question
    
    When the daily question is linked to a discussion statement, the vote is
    also recorded as a StatementVote in that discussion. This allows daily
    question participation to contribute to the discussion's consensus analysis.
    
    If a reason is provided and the user is authenticated, the reason is also
    synced as a Response on the linked statement, making it visible in the
    discussion's response thread.
    """
    from app.models import StatementVote, Statement, Response
    
    user_agent = request.headers.get('User-Agent', '').lower()
    bot_indicators = ['bot', 'crawler', 'spider', 'preview', 'fetch', 'slurp', 'mediapartners']
    if any(indicator in user_agent for indicator in bot_indicators):
        flash('Automated requests are not allowed.', 'error')
        return redirect(url_for('daily.today'))
    
    question = DailyQuestion.get_today()
    
    if not question:
        return jsonify({'success': False, 'error': 'No question available today'}), 400
    
    if has_user_voted(question):
        return jsonify({'success': False, 'error': 'You have already voted today'}), 400
    
    vote_value = request.form.get('vote')
    if vote_value is None or vote_value == '':
        flash('Please select a vote option.', 'error')
        return redirect(url_for('daily.today'))
    reason = request.form.get('reason', '').strip()
    reason_visibility = request.form.get('reason_visibility', DEFAULT_EMAIL_VOTE_VISIBILITY)
    
    # Validate visibility using constants
    if reason_visibility not in VALID_VISIBILITY_OPTIONS:
        reason_visibility = DEFAULT_EMAIL_VOTE_VISIBILITY
    
    # Only allow public_named for authenticated users
    if reason_visibility == 'public_named' and not current_user.is_authenticated:
        reason_visibility = 'public_anonymous'
    
    # Validate vote value using constants
    if vote_value not in VOTE_MAP:
        return jsonify({'success': False, 'error': 'Invalid vote value'}), 400
    
    if reason and len(reason) > 500:
        reason = reason[:500]
    
    try:
        fingerprint = get_session_fingerprint()
        new_vote = VOTE_MAP[vote_value]
        
        # Create the daily question response
        response = DailyQuestionResponse(
            daily_question_id=question.id,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=fingerprint if not current_user.is_authenticated else None,
            vote=new_vote,
            reason=reason if reason else None,
            reason_visibility=reason_visibility if reason else 'public_anonymous',
            voted_via_email=False
        )
        db.session.add(response)
        
        # Sync vote to statement if linked to discussion (uses shared helper)
        created_new, updated = sync_vote_to_statement(question, new_vote, fingerprint)
        
        if created_new:
            current_app.logger.info(
                f"Daily question vote synced to discussion {question.source_discussion_id}, "
                f"statement {question.source_statement_id}"
            )
        elif updated:
            current_app.logger.info(
                f"Daily question vote updated existing vote in discussion {question.source_discussion_id}"
            )
        
        # If user provided a reason, sync as a Response (supports both authenticated and anonymous)
        if reason and reason_visibility != 'private':
            if question.source_statement_id and question.source_discussion_id:
                statement_response, is_new = sync_daily_reason_to_statement(
                    statement_id=question.source_statement_id,
                    user_id=current_user.id if current_user.is_authenticated else None,
                    vote=new_vote,
                    reason=reason,
                    is_anonymous=(reason_visibility == 'public_anonymous' or not current_user.is_authenticated),
                    session_fingerprint=fingerprint if not current_user.is_authenticated else None
                )

                # Track participation for authenticated users
                if is_new and current_user.is_authenticated:
                    participant = DiscussionParticipant.track_participant(
                        discussion_id=question.source_discussion_id,
                        user_id=current_user.id,
                        commit=False
                    )
                    participant.increment_response_count(commit=False)
        
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
            if subscriber:
                subscriber.update_participation_streak(has_reason=bool(reason))
        
        db.session.commit()

        return redirect(url_for('daily.today'))

    except ValueError as e:
        # Validation errors (e.g., from track_participant)
        db.session.rollback()
        current_app.logger.warning(f"Validation error submitting daily vote: {e}")
        return jsonify({'success': False, 'error': 'Invalid request data'}), 400

    except db.exc.IntegrityError as e:
        # Database constraint violations (e.g., duplicate votes)
        db.session.rollback()
        current_app.logger.warning(f"Integrity error submitting daily vote: {e}")
        return jsonify({'success': False, 'error': 'Duplicate vote detected'}), 409

    except Exception as e:
        # Catch-all for unexpected errors
        db.session.rollback()
        current_app.logger.error(f"Unexpected error submitting daily vote: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to submit vote'}), 500


def get_subscriber_streak():
    """Get current subscriber's streak info if available"""
    subscriber_id = session.get('daily_subscriber_id')
    if subscriber_id:
        subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
        if subscriber and subscriber.current_streak > 0:
            return {
                'current_streak': subscriber.current_streak,
                'longest_streak': subscriber.longest_streak,
                'is_thoughtful': subscriber.is_thoughtful_participant
            }
    return None
