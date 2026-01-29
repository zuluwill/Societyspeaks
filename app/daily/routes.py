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
from app.models import DailyQuestion, DailyQuestionResponse, DailyQuestionResponseFlag, DailyQuestionSubscriber, User, Discussion, DiscussionParticipant
from app.trending.conversion_tracking import track_social_click
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


def get_user_streak_data():
    """Get streak data for the current user/subscriber.

    Returns dict with streak info if available, None otherwise.
    Checks:
    1. Logged-in user with linked subscriber
    2. Session-based subscriber (from magic link)
    """
    subscriber = None

    # Check for logged-in user with linked subscriber
    if current_user.is_authenticated:
        # User might have a linked subscriber via the backref
        if hasattr(current_user, 'daily_subscription') and current_user.daily_subscription:
            # daily_subscription is a list due to backref, get first active one
            subs = current_user.daily_subscription if isinstance(current_user.daily_subscription, list) else [current_user.daily_subscription]
            for sub in subs:
                if sub.is_active:
                    subscriber = sub
                    break

    # Check for session-based subscriber (from magic link)
    if not subscriber:
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
            if subscriber and not subscriber.is_active:
                subscriber = None

    if not subscriber:
        return None

    return {
        'current_streak': subscriber.current_streak,
        'longest_streak': subscriber.longest_streak,
        'thoughtful_participations': subscriber.thoughtful_participations,
        'is_thoughtful_participant': subscriber.is_thoughtful_participant,
        'last_participation_date': subscriber.last_participation_date
    }


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
    # Track social media clicks (conversion tracking)
    user_id = str(current_user.id) if current_user.is_authenticated else None
    track_social_click(request, user_id)
    
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
        public_reasons = get_public_reasons(question, limit=6)  # Show 6 in preview
        reasons_stats = get_public_reasons_stats(question)
        streak_data = get_user_streak_data()
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
                             public_reasons=public_reasons,
                             reasons_stats=reasons_stats,
                             streak_data=streak_data)
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
        public_reasons = get_public_reasons(question, limit=6)  # Show 6 in preview
        reasons_stats = get_public_reasons_stats(question)
        streak_data = get_user_streak_data()
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
                             public_reasons=public_reasons,
                             reasons_stats=reasons_stats,
                             streak_data=streak_data)
    else:
        return render_template('daily/question.html',
                             question=question)


@daily_bp.route('/daily/<date_str>/comments')
def view_all_comments(date_str):
    """View all comments for a daily question (for modal view)"""
    try:
        question_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    question = DailyQuestion.query.filter_by(question_date=question_date).first()
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    # Get all public reasons
    all_reasons = get_public_reasons(question, get_all=True)
    reasons_stats = get_public_reasons_stats(question)
    user_response = get_user_response(question)

    # Filter out user's own response
    filtered_reasons = [r for r in all_reasons if not user_response or r.id != user_response.id]

    return render_template('daily/comments_modal.html',
                         question=question,
                         reasons=filtered_reasons,
                         reasons_stats=reasons_stats,
                         user_response=user_response)


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


def get_public_reasons(question, limit=10, get_all=False):
    """
    Get public reasons from other users for this question.

    Uses representative sampling to ensure diversity of perspectives:
    - Shows mix of Agree/Disagree/Unsure responses
    - Prioritizes longer, more thoughtful responses
    - Balances recency with quality

    Args:
        question: DailyQuestion object
        limit: Number of responses to return for preview (default: 10)
        get_all: If True, return all public reasons (for modal view)

    Returns:
        List of DailyQuestionResponse objects
    """
    from sqlalchemy import func, case

    base_query = DailyQuestionResponse.query.filter(
        DailyQuestionResponse.daily_question_id == question.id,
        DailyQuestionResponse.reason.isnot(None),
        DailyQuestionResponse.reason != '',
        DailyQuestionResponse.reason_visibility.in_(['public_named', 'public_anonymous']),
        DailyQuestionResponse.is_hidden == False  # Exclude flagged/hidden responses
    )

    # If getting all, just return by recency
    if get_all:
        return base_query.order_by(DailyQuestionResponse.created_at.desc()).all()

    # For preview: Use representative sampling strategy
    # Goal: Show diverse perspectives, prioritize quality

    # Get count by vote type to ensure diversity
    vote_counts = db.session.query(
        DailyQuestionResponse.vote,
        func.count(DailyQuestionResponse.id)
    ).filter(
        DailyQuestionResponse.daily_question_id == question.id,
        DailyQuestionResponse.reason.isnot(None),
        DailyQuestionResponse.reason != '',
        DailyQuestionResponse.reason_visibility.in_(['public_named', 'public_anonymous']),
        DailyQuestionResponse.is_hidden == False  # Exclude flagged/hidden responses (matches base_query)
    ).group_by(DailyQuestionResponse.vote).all()

    vote_distribution = {vote: count for vote, count in vote_counts}
    total_responses = sum(vote_distribution.values())

    if total_responses == 0:
        return []

    # Calculate how many to take from each perspective (proportional but guaranteed minimum)
    samples_per_vote = {}
    remaining_limit = limit

    # Guarantee at least 1 from each perspective that exists (up to 3)
    for vote in [1, -1, 0]:  # Agree, Disagree, Unsure
        if vote in vote_distribution and remaining_limit > 0:
            samples_per_vote[vote] = 1
            remaining_limit -= 1

    # Distribute remaining slots proportionally
    if remaining_limit > 0:
        for vote, count in vote_distribution.items():
            proportion = count / total_responses
            additional = max(0, int(proportion * limit) - samples_per_vote.get(vote, 0))
            samples_per_vote[vote] = samples_per_vote.get(vote, 0) + min(additional, remaining_limit)
            remaining_limit -= min(additional, remaining_limit)
            if remaining_limit <= 0:
                break

    # Collect responses from each perspective
    selected_responses = []

    for vote, sample_size in samples_per_vote.items():
        if sample_size > 0:
            # Prioritize longer responses (more thoughtful) with recency balance
            # Score: 70% based on length, 30% based on recency
            # Use PostgreSQL-compatible date extraction (EXTRACT EPOCH)
            vote_responses = base_query.filter(
                DailyQuestionResponse.vote == vote
            ).order_by(
                # Length score (longer = more thoughtful, cap at 300 chars)
                (func.least(func.length(DailyQuestionResponse.reason), 300) / 300.0 * 0.7 +
                 # Recency score (newer = higher) - normalize days since question to 0-1 range
                 # Extract epoch difference in days, cap at 7 days, invert so newer = higher
                 func.greatest(0, 1 - func.extract('epoch', 
                     DailyQuestionResponse.created_at - func.cast(question.question_date, db.DateTime)
                 ) / 86400.0 / 7.0) * 0.3
                ).desc()
            ).limit(sample_size).all()

            selected_responses.extend(vote_responses)

    # Shuffle to avoid showing all Agree, then all Disagree, then all Unsure
    import random
    random.shuffle(selected_responses)

    return selected_responses[:limit]


def get_public_reasons_stats(question):
    """
    Get statistics about public reasons for display.

    Returns:
        dict with total_count and count by vote type
    """
    from sqlalchemy import func

    stats = db.session.query(
        DailyQuestionResponse.vote,
        func.count(DailyQuestionResponse.id)
    ).filter(
        DailyQuestionResponse.daily_question_id == question.id,
        DailyQuestionResponse.reason.isnot(None),
        DailyQuestionResponse.reason != '',
        DailyQuestionResponse.reason_visibility.in_(['public_named', 'public_anonymous']),
        DailyQuestionResponse.is_hidden == False  # Exclude flagged/hidden responses
    ).group_by(DailyQuestionResponse.vote).all()

    vote_counts = {vote: count for vote, count in stats}

    return {
        'total_count': sum(vote_counts.values()),
        'agree_count': vote_counts.get(1, 0),
        'disagree_count': vote_counts.get(-1, 0),
        'unsure_count': vote_counts.get(0, 0)
    }


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
            
            # Track conversion with PostHog
            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    ref = request.referrer or ''
                    posthog.capture(
                        distinct_id=str(user.id) if user else email,
                        event='daily_question_subscribed',
                        properties={
                            'subscription_tier': 'free',
                            'plan_name': 'Daily Question',
                            'email': email,
                            'source': 'social' if ('utm_source' in ref or any(d in ref for d in ['twitter.com', 'x.com', 'bsky.social'])) else 'direct',
                            'referrer': request.referrer,
                        }
                    )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")
            
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

    try:
        import posthog
        if posthog and getattr(posthog, 'project_api_key', None):
            distinct_id = str(subscriber.user_id) if subscriber.user_id else subscriber.email
            posthog.capture(
                distinct_id=distinct_id,
                event='daily_question_unsubscribed',
                properties={
                    'email': subscriber.email,
                    'reason': reason,
                }
            )
    except Exception as e:
        current_app.logger.warning(f"PostHog tracking error: {e}")

    current_app.logger.info(
        f"Subscriber {subscriber.id} ({subscriber.email}) unsubscribed. Reason: {reason}"
    )

    # Note: With Resend, unsubscribe is handled by List-Unsubscribe headers
    # and our database is the source of truth. No external API call needed.

    flash('You have been unsubscribed from daily civic questions.', 'success')
    return render_template('daily/unsubscribed.html', email=subscriber.email)


@daily_bp.route('/daily/preferences', methods=['GET', 'POST'])
def manage_preferences():
    """
    Allow users to manage email frequency and send time preferences.
    Accessible via magic token from email or logged-in user session.
    """
    # Get subscriber from token or session
    token = request.args.get('token')
    subscriber = None

    if token:
        subscriber = DailyQuestionSubscriber.query.filter_by(magic_token=token).first()
        if subscriber:
            session['daily_subscriber_id'] = subscriber.id
    else:
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)

    # Also check if logged-in user has a subscription
    if not subscriber and current_user.is_authenticated:
        subscriber = DailyQuestionSubscriber.query.filter_by(user_id=current_user.id).first()

    if not subscriber:
        flash('Please use the link from your weekly digest email to manage preferences.', 'info')
        return redirect(url_for('daily.subscribe'))

    if not subscriber.is_active:
        flash('Your subscription is currently inactive.', 'info')
        return redirect(url_for('daily.subscribe'))

    # Use model constants for DRY (valid frequencies and send days)
    valid_frequencies = DailyQuestionSubscriber.VALID_EMAIL_FREQUENCIES
    send_days = DailyQuestionSubscriber.SEND_DAYS

    if request.method == 'POST':
        validation_errors = []

        # Capture old values BEFORE changes for PostHog tracking
        old_frequency = subscriber.email_frequency

        # Update frequency
        frequency = request.form.get('email_frequency', 'weekly')
        if frequency in valid_frequencies:
            subscriber.email_frequency = frequency
        else:
            validation_errors.append(f"Invalid frequency: {frequency}")

        # Update send day (for weekly subscribers)
        if frequency == 'weekly':
            try:
                send_day = int(request.form.get('preferred_send_day', 1))
                if 0 <= send_day <= 6:
                    subscriber.preferred_send_day = send_day
                else:
                    validation_errors.append(f"Invalid send day: {send_day} (must be 0-6)")
            except (ValueError, TypeError) as e:
                validation_errors.append(f"Invalid send day format: {e}")

            try:
                send_hour = int(request.form.get('preferred_send_hour', 9))
                if 0 <= send_hour <= 23:
                    subscriber.preferred_send_hour = send_hour
                else:
                    validation_errors.append(f"Invalid send hour: {send_hour} (must be 0-23)")
            except (ValueError, TypeError) as e:
                validation_errors.append(f"Invalid send hour format: {e}")

        # Update timezone
        timezone = request.form.get('timezone', '').strip()
        if timezone:
            # Validate timezone
            try:
                import pytz
                pytz.timezone(timezone)  # Will raise if invalid
                subscriber.timezone = timezone
            except pytz.exceptions.UnknownTimeZoneError:
                validation_errors.append(f"Invalid timezone: {timezone}")
            except Exception as e:
                validation_errors.append(f"Error validating timezone: {e}")

        if validation_errors:
            for error in validation_errors:
                flash(error, 'error')
            current_app.logger.warning(
                f"Subscriber {subscriber.id} preference update had errors: {validation_errors}"
            )
        else:
            try:
                # Track preference change with PostHog (old_frequency captured at start of POST)
                try:
                    import posthog
                    if posthog and getattr(posthog, 'project_api_key', None):
                        distinct_id = str(subscriber.user_id) if subscriber.user_id else subscriber.email
                        posthog.capture(
                            distinct_id=distinct_id,
                            event='frequency_preference_changed',
                            properties={
                                'old_frequency': old_frequency,
                                'new_frequency': subscriber.email_frequency,
                                'send_day': subscriber.preferred_send_day,
                                'send_hour': subscriber.preferred_send_hour,
                                'timezone': subscriber.timezone or 'UTC'
                            }
                        )
                except Exception as e:
                    current_app.logger.warning(f"PostHog tracking error: {e}")
                
                db.session.commit()
                current_app.logger.info(
                    f"Subscriber {subscriber.id} updated preferences: "
                    f"frequency={subscriber.email_frequency}, "
                    f"send_day={subscriber.preferred_send_day}, "
                    f"send_hour={subscriber.preferred_send_hour}, "
                    f"timezone={subscriber.timezone}"
                )
                flash('Your preferences have been updated successfully.', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error saving preferences: {e}")
                flash('There was an error saving your preferences. Please try again.', 'error')

        return redirect(url_for('daily.manage_preferences', token=token))

    # GET: Show current preferences
    return render_template('daily/preferences.html',
        subscriber=subscriber,
        send_days=send_days,
        frequencies=valid_frequencies,
        token=token
    )


@daily_bp.route('/daily/weekly')
def weekly_batch():
    """
    Batch voting page for weekly digest subscribers.
    Shows 5 questions at once, allowing sequential voting.
    """
    from app.daily.auto_selection import select_questions_for_weekly_digest
    from app.daily.utils import get_discussion_stats_for_question

    # Get subscriber from token or session
    token = request.args.get('token')
    subscriber = None

    if token:
        subscriber = DailyQuestionSubscriber.query.filter_by(magic_token=token).first()
        if subscriber:
            session['daily_subscriber_id'] = subscriber.id
            session['daily_subscriber_token'] = token
    else:
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)

    # Also check logged-in user
    if not subscriber and current_user.is_authenticated:
        subscriber = DailyQuestionSubscriber.query.filter_by(user_id=current_user.id).first()

    if not subscriber:
        flash('Please use the link from your weekly digest email to access this page.', 'info')
        return redirect(url_for('daily.subscribe'))

    # Log in if user has account
    if subscriber.user:
        login_user(subscriber.user)

    # Get specific question IDs if provided (from email link)
    question_ids_param = request.args.get('questions')
    questions = []
    original_question_ids = None  # Track original order for email links

    if question_ids_param:
        # Parse comma-separated question IDs from email link
        try:
            original_question_ids = [int(qid.strip()) for qid in question_ids_param.split(',') if qid.strip()]
            if original_question_ids:
                questions = DailyQuestion.query.filter(
                    DailyQuestion.id.in_(original_question_ids)
                ).order_by(DailyQuestion.question_date.desc()).all()
                
                # Log if some questions weren't found
                if len(questions) < len(original_question_ids):
                    found_ids = {q.id for q in questions}
                    missing_ids = set(original_question_ids) - found_ids
                    current_app.logger.warning(
                        f"Some question IDs from email not found in database: {missing_ids}. "
                        f"Found {len(questions)}/{len(original_question_ids)} questions."
                    )
            else:
                original_question_ids = None
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Error parsing question IDs from URL: {e}")
            original_question_ids = None

    # Fall back to auto-selected questions from past week
    if not questions:
        questions = select_questions_for_weekly_digest(days_back=7, count=5)

    if not questions:
        flash('No questions available for this week yet.', 'info')
        return redirect(url_for('daily.today'))

    # Optimize: Eager load discussions to prevent N+1 queries
    from sqlalchemy.orm import joinedload
    question_ids = [q.id for q in questions]
    questions = DailyQuestion.query.options(
        joinedload(DailyQuestion.source_discussion)
    ).filter(DailyQuestion.id.in_(question_ids)).order_by(DailyQuestion.question_date.desc()).all()
    
    # Preserve original order from question_ids_param (if provided)
    if original_question_ids:
        # Sort by original order from email
        id_to_question = {q.id: q for q in questions}
        ordered_questions = [id_to_question[qid] for qid in original_question_ids if qid in id_to_question]
        # Only use ordered list if we found all questions (otherwise keep eager-loaded order)
        if len(ordered_questions) == len(questions):
            questions = ordered_questions
        else:
            # Some questions from email not found - log warning but continue with what we have
            current_app.logger.warning(
                f"Some question IDs from email not found: requested {len(original_question_ids)}, "
                f"found {len(questions)}. Using available questions."
            )

    # Build question data with vote status, discussion stats, and source articles
    questions_data = []
    fingerprint = get_session_fingerprint() if not current_user.is_authenticated else None
    
    for question in questions:
        # Check if already voted (with null safety)
        user_vote = None
        try:
            if current_user.is_authenticated:
                response = DailyQuestionResponse.query.filter_by(
                    daily_question_id=question.id,
                    user_id=current_user.id
                ).first()
                if response:
                    user_vote = response.vote
            else:
                if fingerprint:
                    response = DailyQuestionResponse.query.filter_by(
                        daily_question_id=question.id,
                        session_fingerprint=fingerprint
                    ).first()
                    if response:
                        user_vote = response.vote
        except Exception as e:
            current_app.logger.warning(f"Error checking vote status for question {question.id}: {e}")

        # Get discussion stats (with error handling)
        try:
            discussion_stats = get_discussion_stats_for_question(question)
        except Exception as e:
            current_app.logger.warning(f"Error getting discussion stats for question {question.id}: {e}", exc_info=True)
            discussion_stats = {
                'has_discussion': False,
                'discussion_id': None,
                'discussion_slug': None,
                'discussion_title': None,
                'participant_count': 0,
                'response_count': 0,
                'is_active': False,
                'discussion_url': None
            }

        # Get vote counts for results display
        try:
            vote_counts = db.session.query(
                DailyQuestionResponse.vote,
                db.func.count(DailyQuestionResponse.id)
            ).filter(
                DailyQuestionResponse.daily_question_id == question.id
            ).group_by(DailyQuestionResponse.vote).all()

            vote_results = {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0}
            for vote_val, count in vote_counts:
                vote_results['total'] += count
                if vote_val == 1:
                    vote_results['agree'] = count
                elif vote_val == -1:
                    vote_results['disagree'] = count
                elif vote_val == 0:
                    vote_results['unsure'] = count

            # Calculate percentages
            if vote_results['total'] > 0:
                vote_results['agree_pct'] = round(vote_results['agree'] / vote_results['total'] * 100)
                vote_results['disagree_pct'] = round(vote_results['disagree'] / vote_results['total'] * 100)
                vote_results['unsure_pct'] = round(vote_results['unsure'] / vote_results['total'] * 100)
            else:
                vote_results['agree_pct'] = 0
                vote_results['disagree_pct'] = 0
                vote_results['unsure_pct'] = 0
        except Exception as e:
            current_app.logger.warning(f"Error getting vote results for question {question.id}: {e}")
            vote_results = {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0, 
                          'agree_pct': 0, 'disagree_pct': 0, 'unsure_pct': 0}

        # Get source articles (with error handling)
        try:
            source_articles = get_source_articles(question, limit=3)
        except Exception as e:
            current_app.logger.warning(f"Error getting source articles for question {question.id}: {e}", exc_info=True)
            source_articles = []

        questions_data.append({
            'question': question,
            'user_vote': user_vote,
            'has_voted': user_vote is not None,
            'discussion_stats': discussion_stats,
            'vote_results': vote_results,
            'source_articles': source_articles
        })

    # Count completed votes
    votes_completed = sum(1 for q in questions_data if q['has_voted'])
    all_voted = votes_completed == len(questions_data)

    return render_template('daily/weekly_batch.html',
        subscriber=subscriber,
        questions=questions_data,
        votes_completed=votes_completed,
        total_questions=len(questions_data),
        all_voted=all_voted,
        token=token
    )


@daily_bp.route('/daily/weekly/vote', methods=['POST'])
@limiter.limit("30 per minute")
def weekly_batch_vote():
    """
    Handle a vote from the weekly batch page.
    Records vote and returns updated state for the question.
    
    Security: Uses session-based authentication (subscriber_id in session).
    For JSON requests, session is sufficient. For form submissions, CSRF would be checked.
    """
    # Get subscriber from session (session-based auth is sufficient for this endpoint)
    subscriber_id = session.get('daily_subscriber_id')
    if not subscriber_id:
        return jsonify({'error': 'Not authenticated'}), 401

    subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
    if not subscriber or not subscriber.is_active:
        return jsonify({'error': 'Subscriber not found or inactive'}), 404

    # Log in if user has account
    if subscriber.user:
        login_user(subscriber.user)

    # Parse request (expects JSON from AJAX)
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    question_id = data.get('question_id')
    vote_choice = data.get('vote')
    reason = data.get('reason', '').strip() if data.get('reason') else None

    if not question_id or not vote_choice:
        return jsonify({'error': 'Missing question_id or vote'}), 400

    # Validate vote choice
    if vote_choice not in VOTE_MAP:
        return jsonify({'error': 'Invalid vote'}), 400

    # Get the question
    question = DailyQuestion.query.get(question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    # Check if already voted
    if has_user_voted(question):
        return jsonify({'error': 'Already voted', 'already_voted': True}), 400

    try:
        fingerprint = get_session_fingerprint()
        new_vote = VOTE_MAP[vote_choice]

        # Create the daily question response
        response = DailyQuestionResponse(
            daily_question_id=question.id,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=fingerprint if not current_user.is_authenticated else None,
            vote=new_vote,
            reason=reason[:500] if reason else None,
            reason_visibility=DEFAULT_EMAIL_VOTE_VISIBILITY if reason else None,
            voted_via_email=True  # Mark as from weekly digest
        )
        db.session.add(response)

        # Sync vote to statement if linked to discussion
        sync_vote_to_statement(question, new_vote, fingerprint)

        # Update subscriber streak
        subscriber.update_participation_streak(has_reason=bool(reason))

        db.session.commit()

        current_app.logger.info(
            f"Weekly batch vote recorded: {vote_choice} for question #{question.id} "
            f"by subscriber {subscriber.id}"
        )

        # Get updated vote counts for this question
        try:
            vote_counts = db.session.query(
                DailyQuestionResponse.vote,
                db.func.count(DailyQuestionResponse.id)
            ).filter(
                DailyQuestionResponse.daily_question_id == question.id
            ).group_by(DailyQuestionResponse.vote).all()

            vote_results = {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0}
            for vote_val, count in vote_counts:
                vote_results['total'] += count
                if vote_val == 1:
                    vote_results['agree'] = count
                elif vote_val == -1:
                    vote_results['disagree'] = count
                elif vote_val == 0:
                    vote_results['unsure'] = count

            if vote_results['total'] > 0:
                vote_results['agree_pct'] = round(vote_results['agree'] / vote_results['total'] * 100)
                vote_results['disagree_pct'] = round(vote_results['disagree'] / vote_results['total'] * 100)
                vote_results['unsure_pct'] = round(vote_results['unsure'] / vote_results['total'] * 100)
            else:
                vote_results['agree_pct'] = 0
                vote_results['disagree_pct'] = 0
                vote_results['unsure_pct'] = 0
        except Exception as e:
            current_app.logger.error(f"Error getting vote results: {e}")
            vote_results = {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0,
                          'agree_pct': 0, 'disagree_pct': 0, 'unsure_pct': 0}

        # Get discussion stats and source articles for mini results
        try:
            from app.daily.utils import get_discussion_stats_for_question
            discussion_stats = get_discussion_stats_for_question(question)
            source_articles = get_source_articles(question, limit=3)
        except Exception as e:
            current_app.logger.warning(f"Error getting discussion stats/articles: {e}", exc_info=True)
            discussion_stats = {'has_discussion': False, 'discussion_url': None, 'participant_count': 0}
            source_articles = []

        return jsonify({
            'success': True,
            'vote': vote_choice,
            'results': vote_results,
            'discussion_stats': discussion_stats,
            'source_articles': [
                {
                    'title': article.title if hasattr(article, 'title') else 'Source Article',
                    'url': article.url if hasattr(article, 'url') else '#',
                    'source_name': article.source.name if hasattr(article, 'source') and article.source else 'Unknown'
                }
                for article in source_articles[:3]
            ]
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing weekly batch vote: {e}", exc_info=True)
        return jsonify({'error': 'Failed to record vote'}), 500


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
        # If from weekly digest, redirect to batch page to vote on remaining questions
        source = request.args.get('source', '')
        if source == 'weekly_digest':
            session['daily_subscriber_token'] = subscriber.magic_token
            return redirect(url_for('daily.weekly_batch', token=subscriber.magic_token))
        return redirect(url_for('daily.today'))

    # GET request: Show confirmation page (prevents mail scanner prefetch from voting)
    if request.method == 'GET':
        source = request.args.get('source', '')
        return render_template('daily/confirm_vote.html',
                             question=question,
                             vote_choice=vote_choice,
                             vote_label=VOTE_LABELS.get(VOTE_MAP.get(vote_choice), vote_choice.title()),
                             vote_emoji=VOTE_EMOJIS.get(vote_choice, ''),
                             token=token,
                             source=source)
    
    # POST request: Record the vote
    try:
        fingerprint = get_session_fingerprint()
        new_vote = VOTE_MAP[vote_choice]

        # Get optional reason from form (same as web flow for consistent experience)
        reason = request.form.get('reason', '').strip()
        reason_visibility = request.form.get('reason_visibility', DEFAULT_EMAIL_VOTE_VISIBILITY)

        # Validate visibility using constants
        if reason_visibility not in VALID_VISIBILITY_OPTIONS:
            reason_visibility = DEFAULT_EMAIL_VOTE_VISIBILITY

        # Truncate reason if too long
        if reason and len(reason) > 500:
            reason = reason[:500]

        # Create the daily question response (now includes reason if provided)
        response = DailyQuestionResponse(
            daily_question_id=question.id,
            email_question_id=email_question_id,  # Track which question the email was about
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=fingerprint if not current_user.is_authenticated else None,
            vote=new_vote,
            reason=reason if reason else None,
            reason_visibility=reason_visibility if reason else DEFAULT_EMAIL_VOTE_VISIBILITY,
            voted_via_email=True
        )
        db.session.add(response)

        # Sync vote to statement if linked to discussion (uses shared helper)
        sync_vote_to_statement(question, new_vote, fingerprint)

        # If user provided a reason, sync as a Response to the linked discussion
        if reason and reason_visibility != 'private':
            if question.source_statement_id and question.source_discussion_id:
                sync_daily_reason_to_statement(
                    statement_id=question.source_statement_id,
                    user_id=current_user.id if current_user.is_authenticated else None,
                    vote=new_vote,
                    reason=reason,
                    is_anonymous=(reason_visibility == 'public_anonymous' or not current_user.is_authenticated),
                    session_fingerprint=fingerprint if not current_user.is_authenticated else None
                )

        # Update subscriber streak (now tracks if reason was provided)
        subscriber.update_participation_streak(has_reason=bool(reason))

        db.session.commit()

        try:
            import posthog
            if posthog and getattr(posthog, 'project_api_key', None):
                distinct_id = str(current_user.id) if current_user.is_authenticated else subscriber.email
                posthog.capture(
                    distinct_id=distinct_id,
                    event='daily_question_participated',
                    properties={
                        'question_id': question.id,
                        'question_number': question.question_number,
                        'vote': vote_choice,
                        'has_reason': bool(reason),
                        'is_authenticated': current_user.is_authenticated,
                        'voted_via_email': True,
                        'source': request.args.get('source', 'email'),
                    }
                )
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")

        current_app.logger.info(
            f"One-click email vote recorded: {vote_choice} for question #{question.question_number} "
            f"(email_q#{email_question_id}) by subscriber {subscriber.id}"
            f"{' with reason' if reason else ''}"
        )

        flash('Vote recorded! Thanks for participating.', 'success')

        # Check if user came from weekly digest - redirect to batch page to continue voting
        source = request.args.get('source', '')
        if source == 'weekly_digest':
            # Store the subscriber's token in session for batch page access
            session['daily_subscriber_token'] = subscriber.magic_token
            return redirect(url_for('daily.weekly_batch', token=subscriber.magic_token))

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

        try:
            import posthog
            if posthog and getattr(posthog, 'project_api_key', None):
                distinct_id = str(current_user.id) if current_user.is_authenticated else get_session_fingerprint() or 'anonymous'
                posthog.capture(
                    distinct_id=distinct_id,
                    event='daily_question_participated',
                    properties={
                        'question_id': question.id,
                        'question_number': question.question_number,
                        'vote': vote_value,
                        'has_reason': bool(reason),
                        'is_authenticated': current_user.is_authenticated,
                        'voted_via_email': False,
                    }
                )
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")

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


@daily_bp.route('/daily/report', methods=['POST'])
@limiter.limit("5 per hour")
def report_response():
    """Submit a flag/report for an inappropriate daily question response"""
    try:
        data = request.get_json()
        
        # Handle missing JSON body
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request format'}), 400
            
        response_id = data.get('response_id')
        reason = data.get('reason')
        details = data.get('details', '').strip() if data.get('details') else ''

        # Validate inputs
        if not response_id or not reason:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        valid_reasons = ['spam', 'harassment', 'misinformation', 'other']
        if reason not in valid_reasons:
            return jsonify({'success': False, 'message': 'Invalid reason'}), 400

        # Check if response exists - use with_for_update() to prevent race conditions
        response = DailyQuestionResponse.query.filter_by(id=response_id).with_for_update().first()
        if not response:
            return jsonify({'success': False, 'message': 'Response not found'}), 404

        # Don't allow flagging responses that are already hidden
        if response.is_hidden:
            return jsonify({'success': False, 'message': 'This response has already been reviewed'}), 400

        # Don't allow flagging your own response
        if current_user.is_authenticated and response.user_id == current_user.id:
            return jsonify({'success': False, 'message': 'You cannot report your own response'}), 400

        # Get fingerprint for anonymous flagging
        fingerprint = session.get('session_fingerprint')
        if not fingerprint:
            fingerprint = hashlib.sha256(
                f"{request.headers.get('User-Agent', '')}{request.remote_addr}{secrets.token_urlsafe(16)}".encode()
            ).hexdigest()
            session['session_fingerprint'] = fingerprint

        # Check for duplicate flag
        existing_flag = DailyQuestionResponseFlag.query.filter_by(
            response_id=response_id,
            flagged_by_fingerprint=fingerprint
        ).first()

        if existing_flag:
            return jsonify({'success': False, 'message': 'You have already reported this response'}), 400

        # Create flag
        flag = DailyQuestionResponseFlag(
            response_id=response_id,
            flagged_by_user_id=current_user.id if current_user.is_authenticated else None,
            flagged_by_fingerprint=fingerprint,
            reason=reason,
            details=details[:500] if details else None
        )

        db.session.add(flag)

        # Increment flag count on response (row is locked, so this is safe)
        response.flag_count += 1

        # Auto-hide after 3 flags
        if response.flag_count >= 3 and not response.is_hidden:
            response.is_hidden = True
            current_app.logger.warning(
                f"Auto-hiding daily response {response_id} after reaching 3 flags"
            )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Report submitted successfully',
            'flag_count': response.flag_count
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error submitting flag: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to submit report'}), 500


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
