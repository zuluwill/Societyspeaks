"""
Utility functions for the Daily Questions feature.
These are reusable across routes, email templates, and scheduler jobs.
"""
from datetime import datetime, timedelta
from flask import url_for
from app import db


def get_discussion_stats_for_question(question):
    """
    Get discussion statistics for a question's linked discussion.
    This is a user-agnostic version for use in email templates and selection logic.

    Unlike get_discussion_participation_data() in routes.py, this doesn't track
    user-specific vote counts - just general stats for display.

    Args:
        question: DailyQuestion object

    Returns:
        dict: {
            'has_discussion': bool,
            'discussion_id': int | None,
            'discussion_slug': str | None,
            'discussion_title': str | None,
            'participant_count': int,
            'response_count': int,
            'is_active': bool,  # Has activity in last 24h
            'discussion_url': str | None
        }
    """
    from app.models import StatementVote, Statement, Response

    # Default response for questions without discussions
    default_response = {
        'has_discussion': False,
        'discussion_id': None,
        'discussion_slug': None,
        'discussion_title': None,
        'participant_count': 0,
        'response_count': 0,
        'is_active': False,
        'discussion_url': None
    }

    # Null safety checks
    if not question:
        return default_response
    
    if not question.source_discussion_id:
        return default_response

    try:
        discussion = question.source_discussion
        if not discussion:
            return default_response
    except Exception as e:
        # Handle case where relationship fails
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error accessing source_discussion for question {question.id}: {e}")
        return default_response

    # Count participants (authenticated users who voted)
    participant_count = db.session.query(
        db.func.count(db.distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    # Add anonymous participants
    anon_count = db.session.query(
        db.func.count(db.distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0

    participant_count += anon_count

    # Count responses (statements added to discussion)
    response_count = Statement.query.filter_by(
        discussion_id=discussion.id
    ).count()

    # Check if discussion is active (has activity in last 24h)
    yesterday = datetime.utcnow() - timedelta(hours=24)
    recent_votes = StatementVote.query.filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.created_at >= yesterday
    ).first()
    is_active = recent_votes is not None

    # Build discussion URL
    try:
        discussion_url = url_for(
            'discussions.view_discussion',
            discussion_id=discussion.id,
            slug=discussion.slug,
            _external=True
        )
    except Exception:
        # Fallback if url_for fails (e.g., outside request context)
        discussion_url = f"/discussions/{discussion.id}/{discussion.slug}"

    return {
        'has_discussion': True,
        'discussion_id': discussion.id,
        'discussion_slug': discussion.slug,
        'discussion_title': discussion.title,
        'participant_count': participant_count,
        'response_count': response_count,
        'is_active': is_active,
        'discussion_url': discussion_url
    }


def get_source_articles_for_question(question, limit=3):
    """
    Get source articles for a question for the "Learn More" section.
    
    This is a wrapper around get_source_articles() for DRY principles.
    Returns NewsArticle objects (same as routes.py version).

    Args:
        question: DailyQuestion object
        limit: Maximum number of articles to return

    Returns:
        list: List of NewsArticle objects (same format as routes.py)
    """
    from app.daily.routes import get_source_articles
    return get_source_articles(question, limit=limit)


def build_question_email_data(question, subscriber, base_url=None):
    """
    Build all the data needed for a question in the weekly digest email.
    DRY helper function used by both email sending and batch page.

    Args:
        question: DailyQuestion object
        subscriber: DailyQuestionSubscriber object
        base_url: Optional base URL (for use outside request context)

    Returns:
        dict: Contains question, discussion_stats, vote_urls, source_articles, question_url
    """
    # Get discussion stats (with error handling)
    try:
        discussion_stats = get_discussion_stats_for_question(question)
    except Exception as e:
        # Log error but continue with default stats
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error getting discussion stats for question {question.id}: {e}")
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

    # Generate vote token and URLs
    vote_token = subscriber.generate_vote_token(question.id)

    if base_url:
        # Use provided base_url (for use outside request context, e.g., email sending)
        vote_urls = {
            'agree': f"{base_url}/daily/v/{vote_token}/agree?q={question.id}&source=weekly_digest",
            'disagree': f"{base_url}/daily/v/{vote_token}/disagree?q={question.id}&source=weekly_digest",
            'unsure': f"{base_url}/daily/v/{vote_token}/unsure?q={question.id}&source=weekly_digest",
        }
        question_url = f"{base_url}/daily/{question.question_date.isoformat()}"
    else:
        # Use url_for (for use within request context)
        try:
            vote_urls = {
                'agree': url_for('daily.one_click_vote',
                               token=vote_token,
                               vote_choice='agree',
                               _external=True) + f'?q={question.id}&source=weekly_digest',
                'disagree': url_for('daily.one_click_vote',
                                  token=vote_token,
                                  vote_choice='disagree',
                                  _external=True) + f'?q={question.id}&source=weekly_digest',
                'unsure': url_for('daily.one_click_vote',
                                token=vote_token,
                                vote_choice='unsure',
                                _external=True) + f'?q={question.id}&source=weekly_digest'
            }
            question_url = url_for('daily.by_date',
                                  date_str=question.question_date.isoformat(),
                                  _external=True)
        except Exception:
            # Fallback if url_for fails
            vote_urls = {
                'agree': f'/daily/v/{vote_token}/agree?q={question.id}&source=weekly_digest',
                'disagree': f'/daily/v/{vote_token}/disagree?q={question.id}&source=weekly_digest',
                'unsure': f'/daily/v/{vote_token}/unsure?q={question.id}&source=weekly_digest'
            }
            question_url = f"/daily/{question.question_date.isoformat()}"

    # Get source articles for learning (returns NewsArticle objects)
    try:
        source_articles = get_source_articles_for_question(question, limit=5)
    except Exception as e:
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Error getting source articles for question {question.id}: {e}")
        source_articles = []

    return {
        'question': question,
        'discussion_stats': discussion_stats,
        'vote_urls': vote_urls,
        'source_articles': source_articles,
        'question_url': question_url
    }
