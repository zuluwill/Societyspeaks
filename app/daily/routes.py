from flask import render_template, redirect, url_for, flash, request, jsonify, session, current_app
from flask_login import current_user, login_user
from datetime import date, datetime
from app.daily import daily_bp
from app import db, limiter
from app.models import DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber, User, Discussion
import hashlib
import re


def get_source_articles(question, limit=5):
    """Get source articles from the source discussion if available"""
    if question.source_discussion and question.source_discussion.source_article_links:
        articles = []
        for link in question.source_discussion.source_article_links[:limit]:
            if link.article:
                articles.append(link.article)
        return articles
    return []


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


def get_session_fingerprint():
    """Generate a fingerprint for anonymous users"""
    if 'daily_fingerprint' not in session:
        session_id = session.get('_id', request.remote_addr or 'unknown')
        ip_addr = request.remote_addr or 'unknown'
        user_agent = request.headers.get('User-Agent', '')[:100]
        fingerprint_string = f"daily:{session_id}:{ip_addr}:{user_agent}"
        session['daily_fingerprint'] = hashlib.sha256(fingerprint_string.encode()).hexdigest()
        session.modified = True
    return session['daily_fingerprint']


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
        return render_template('daily/results.html',
                             question=question,
                             user_response=user_response,
                             stats=question.vote_percentages,
                             is_cold_start=question.is_cold_start,
                             early_signal=question.early_signal_message,
                             share_snippet=generate_share_snippet(question, user_response),
                             source_discussion=question.source_discussion,
                             source_articles=get_source_articles(question),
                             related_discussions=get_related_discussions(question))
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
                             related_discussions=get_related_discussions(question))
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
            
            from app.email_utils import send_daily_question_welcome_email
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


@daily_bp.route('/daily/unsubscribe/<token>')
def unsubscribe(token):
    """Unsubscribe from daily question emails"""
    subscriber = DailyQuestionSubscriber.query.filter_by(magic_token=token).first()
    
    if not subscriber:
        flash('Invalid unsubscribe link.', 'error')
        return redirect(url_for('daily.today'))
    
    subscriber.is_active = False
    db.session.commit()
    
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


@daily_bp.route('/daily/vote', methods=['POST'])
@limiter.limit("10 per minute")
def vote():
    """Submit a vote for today's question"""
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
    
    vote_map = {'agree': 1, 'disagree': -1, 'unsure': 0}
    if vote_value not in vote_map:
        return jsonify({'success': False, 'error': 'Invalid vote value'}), 400
    
    if reason and len(reason) > 500:
        reason = reason[:500]
    
    try:
        response = DailyQuestionResponse(
            daily_question_id=question.id,
            user_id=current_user.id if current_user.is_authenticated else None,
            session_fingerprint=get_session_fingerprint() if not current_user.is_authenticated else None,
            vote=vote_map[vote_value],
            reason=reason if reason else None
        )
        db.session.add(response)
        
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
            if subscriber:
                subscriber.update_participation_streak(has_reason=bool(reason))
        
        db.session.commit()
        
        return redirect(url_for('daily.today'))
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error submitting daily vote: {e}")
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
