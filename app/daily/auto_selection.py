"""
Automatic Daily Question Selection Service

Selects the next daily question from curated content sources:
1. Existing discussion topics (primary)
2. Published trending topics with high civic scores
3. Statements from active discussions

Avoids repeating content within a configurable time window.
"""

from datetime import date, datetime, timedelta
from flask import current_app
from app import db
from app.models import (
    DailyQuestion, 
    DailyQuestionSelection,
    Discussion, 
    TrendingTopic,
    Statement
)
import random


AVOID_REPEAT_DAYS = 30
MIN_CIVIC_SCORE = 0.5


def get_eligible_discussions(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get discussions that haven't been used recently"""
    cutoff = datetime.utcnow() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_discussion_id).filter(
        DailyQuestionSelection.source_type == 'discussion',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_discussion_id.isnot(None)
    ).subquery()
    
    discussions = Discussion.query.filter(
        Discussion.status == 'active',
        Discussion.id.notin_(recently_used_ids)
    ).order_by(Discussion.created_at.desc()).limit(50).all()
    
    return discussions


def get_eligible_trending_topics(days_to_avoid=AVOID_REPEAT_DAYS, min_civic_score=MIN_CIVIC_SCORE):
    """Get published trending topics that haven't been used recently"""
    cutoff = datetime.utcnow() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_trending_topic_id).filter(
        DailyQuestionSelection.source_type == 'trending',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_trending_topic_id.isnot(None)
    ).subquery()
    
    topics = TrendingTopic.query.filter(
        TrendingTopic.status == 'published',
        TrendingTopic.civic_score >= min_civic_score,
        TrendingTopic.id.notin_(recently_used_ids)
    ).order_by(TrendingTopic.civic_score.desc()).limit(30).all()
    
    return topics


def get_eligible_statements(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get statements from active discussions that haven't been used recently"""
    cutoff = datetime.utcnow() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_statement_id).filter(
        DailyQuestionSelection.source_type == 'statement',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_statement_id.isnot(None)
    ).subquery()
    
    statements = Statement.query.join(Discussion).filter(
        Discussion.status == 'active',
        Statement.id.notin_(recently_used_ids),
        Statement.is_seed == True
    ).order_by(Statement.created_at.desc()).limit(50).all()
    
    return statements


def select_next_question_source():
    """
    Select the next question source using priority order:
    1. Curated discussions
    2. High-quality trending topics
    3. Seed statements from discussions
    """
    discussions = get_eligible_discussions()
    if discussions:
        selected = random.choice(discussions[:10])
        return {
            'source_type': 'discussion',
            'source': selected,
            'question_text': selected.title,
            'context': selected.description[:300] if selected.description else None,
            'topic_category': selected.topic
        }
    
    topics = get_eligible_trending_topics()
    if topics:
        selected = random.choice(topics[:5])
        seed_statements = selected.seed_statements
        question_text = seed_statements[0] if seed_statements else selected.title
        return {
            'source_type': 'trending',
            'source': selected,
            'question_text': question_text,
            'context': selected.summary[:300] if selected.summary else None,
            'topic_category': selected.topic
        }
    
    statements = get_eligible_statements()
    if statements:
        selected = random.choice(statements[:10])
        return {
            'source_type': 'statement',
            'source': selected,
            'question_text': selected.text,
            'context': f"From discussion: {selected.discussion.title}" if selected.discussion else None,
            'topic_category': selected.discussion.topic if selected.discussion else None
        }
    
    return None


def create_daily_question_from_source(question_date, source_info, created_by_id=None):
    """Create a DailyQuestion from the selected source"""
    source = source_info['source']
    source_type = source_info['source_type']
    
    next_number = DailyQuestion.get_next_question_number()
    
    question = DailyQuestion(
        question_date=question_date,
        question_number=next_number,
        question_text=source_info['question_text'],
        context=source_info.get('context'),
        topic_category=source_info.get('topic_category'),
        source_type=source_type,
        source_discussion_id=source.id if source_type == 'discussion' else None,
        source_trending_topic_id=source.id if source_type == 'trending' else None,
        source_statement_id=source.id if source_type == 'statement' else None,
        status='scheduled',
        created_by_id=created_by_id
    )
    
    db.session.add(question)
    
    selection = DailyQuestionSelection(
        source_type=source_type,
        source_discussion_id=source.id if source_type == 'discussion' else None,
        source_trending_topic_id=source.id if source_type == 'trending' else None,
        source_statement_id=source.id if source_type == 'statement' else None,
        question_date=question_date
    )
    db.session.add(selection)
    
    db.session.commit()
    
    selection.daily_question_id = question.id
    db.session.commit()
    
    current_app.logger.info(f"Auto-created daily question #{next_number} for {question_date} from {source_type}")
    return question


def auto_schedule_upcoming_questions(days_ahead=7):
    """Auto-schedule questions for the next N days if not already scheduled"""
    today = date.today()
    scheduled_count = 0
    
    for i in range(days_ahead):
        target_date = today + timedelta(days=i)
        
        existing = DailyQuestion.query.filter_by(question_date=target_date).first()
        if existing:
            continue
        
        source_info = select_next_question_source()
        if source_info:
            try:
                create_daily_question_from_source(target_date, source_info)
                scheduled_count += 1
            except Exception as e:
                current_app.logger.error(f"Error auto-scheduling question for {target_date}: {e}")
                db.session.rollback()
        else:
            current_app.logger.warning(f"No eligible content found for auto-scheduling {target_date}")
    
    return scheduled_count


def auto_publish_todays_question():
    """Auto-publish today's scheduled question if not already published"""
    today = date.today()
    
    question = DailyQuestion.query.filter_by(question_date=today).first()
    
    if not question:
        source_info = select_next_question_source()
        if source_info:
            question = create_daily_question_from_source(today, source_info)
        else:
            current_app.logger.warning("No content available for today's daily question")
            return None
    
    if question.status != 'published':
        question.status = 'published'
        question.published_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(f"Auto-published daily question #{question.question_number}")
    
    return question
