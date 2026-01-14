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
from sqlalchemy.exc import IntegrityError
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


def is_duplicate_date_error(error):
    """Check if an IntegrityError is due to duplicate question_date.
    
    Handles different database backends (PostgreSQL, SQLite, MySQL).
    """
    error_str = str(error).lower()
    orig = getattr(error, 'orig', None)
    
    if orig:
        orig_args = getattr(orig, 'args', ())
        if orig_args:
            orig_str = str(orig_args).lower()
            if 'question_date' in orig_str or 'uq_daily_question_date' in orig_str:
                return True
        pgcode = getattr(orig, 'pgcode', None)
        if pgcode == '23505':
            if 'uq_daily_question_date' in error_str or 'question_date' in error_str:
                return True
    
    return ('uq_daily_question_date' in error_str or 
            ('duplicate' in error_str and 'question_date' in error_str))


def get_eligible_discussions(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get discussions that haven't been used recently"""
    cutoff = datetime.utcnow() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_discussion_id).filter(
        DailyQuestionSelection.source_type == 'discussion',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_discussion_id.isnot(None)
    ).scalar_subquery()
    
    discussions = Discussion.query.filter(
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
    ).scalar_subquery()
    
    topics = TrendingTopic.query.filter(
        TrendingTopic.status == 'published',
        TrendingTopic.civic_score >= min_civic_score,
        TrendingTopic.id.notin_(recently_used_ids)
    ).order_by(TrendingTopic.civic_score.desc()).limit(30).all()
    
    return topics


def get_eligible_statements(days_to_avoid=AVOID_REPEAT_DAYS):
    """Get seed statements from discussions that haven't been used recently"""
    cutoff = datetime.utcnow() - timedelta(days=days_to_avoid)
    
    recently_used_ids = db.session.query(DailyQuestionSelection.source_statement_id).filter(
        DailyQuestionSelection.source_type == 'statement',
        DailyQuestionSelection.selected_at >= cutoff,
        DailyQuestionSelection.source_statement_id.isnot(None)
    ).scalar_subquery()
    
    statements = Statement.query.join(Discussion).filter(
        Statement.id.notin_(recently_used_ids),
        Statement.is_seed == True
    ).order_by(Statement.created_at.desc()).limit(50).all()
    
    return statements


def select_next_question_source():
    """
    Select the next question source using priority order:
    1. Seed statements from curated discussions (THE main source)
    2. High-quality trending topics (use their seed statements)
    3. Direct statements as fallback
    
    Key insight: Daily questions should be actual voteable statements,
    not just discussion titles. Users need specific claims to agree/disagree with.
    """
    discussions = get_eligible_discussions()
    if discussions:
        for discussion in discussions[:10]:
            seed_statements = Statement.query.filter_by(
                discussion_id=discussion.id,
                is_seed=True
            ).all()
            if seed_statements:
                selected_statement = random.choice(seed_statements)
                return {
                    'source_type': 'discussion',
                    'source': discussion,
                    'statement': selected_statement,
                    'question_text': selected_statement.content,
                    'context': discussion.title,
                    'topic_category': discussion.topic,
                    'discussion_slug': discussion.slug
                }
    
    topics = get_eligible_trending_topics()
    if topics:
        # Filter to only include topics that have seed statements (proper statements, not questions)
        topics_with_statements = [topic for topic in topics if topic.seed_statements]
        if topics_with_statements:
            selected = random.choice(topics_with_statements[:5])
            question_text = selected.seed_statements[0]
            return {
                'source_type': 'trending',
                'source': selected,
                'statement': None,
                'question_text': question_text,
                'context': selected.summary[:300] if selected.summary else None,
                'topic_category': selected.topic,
                'discussion_slug': None
            }
    
    statements = get_eligible_statements()
    if statements:
        selected = random.choice(statements[:10])
        return {
            'source_type': 'statement',
            'source': selected,
            'statement': selected,
            'question_text': selected.content,
            'context': selected.discussion.title if selected.discussion else None,
            'topic_category': selected.discussion.topic if selected.discussion else None,
            'discussion_slug': selected.discussion.slug if selected.discussion else None
        }
    
    return None


class DuplicateDateError(Exception):
    """Raised when a question already exists for the specified date"""
    pass


def create_daily_question_from_source(question_date, source_info, created_by_id=None):
    """Create a DailyQuestion from the selected source.
    
    Raises:
        DuplicateDateError: If a question already exists for this date (concurrent scheduling)
        IntegrityError: For other database integrity issues
    """
    source = source_info['source']
    source_type = source_info['source_type']
    statement = source_info.get('statement')
    
    source_discussion_id = None
    source_statement_id = None
    source_trending_topic_id = None
    
    if source_type == 'discussion':
        source_discussion_id = source.id
        if statement:
            source_statement_id = statement.id
    elif source_type == 'trending':
        source_trending_topic_id = source.id
    elif source_type == 'statement':
        source_statement_id = source.id
        if hasattr(source, 'discussion') and source.discussion:
            source_discussion_id = source.discussion.id
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            next_number = DailyQuestion.get_next_question_number()
            
            question = DailyQuestion(
                question_date=question_date,
                question_number=next_number,
                question_text=source_info['question_text'],
                context=source_info.get('context'),
                topic_category=source_info.get('topic_category'),
                source_type=source_type,
                source_discussion_id=source_discussion_id,
                source_trending_topic_id=source_trending_topic_id,
                source_statement_id=source_statement_id,
                status='scheduled',
                created_by_id=created_by_id
            )
            
            db.session.add(question)
            db.session.flush()
            
            selection = DailyQuestionSelection(
                source_type=source_type,
                source_discussion_id=source_discussion_id,
                source_trending_topic_id=source_trending_topic_id,
                source_statement_id=source_statement_id,
                question_date=question_date,
                daily_question_id=question.id
            )
            db.session.add(selection)
            
            db.session.commit()
            
            current_app.logger.info(f"Auto-created daily question #{next_number} for {question_date} from {source_type}")
            return question
            
        except IntegrityError as e:
            db.session.rollback()
            
            if is_duplicate_date_error(e):
                current_app.logger.info(f"Question for {question_date} already exists (concurrent scheduling)")
                raise DuplicateDateError(f"Question already exists for {question_date}")
            
            error_str = str(e).lower()
            if 'question_number' in error_str and attempt < max_retries - 1:
                current_app.logger.warning(f"Question number conflict, retrying (attempt {attempt + 1})")
                continue
            
            raise


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
            except DuplicateDateError:
                pass
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
            try:
                question = create_daily_question_from_source(today, source_info)
            except DuplicateDateError:
                question = DailyQuestion.query.filter_by(question_date=today).first()
            except Exception as e:
                current_app.logger.error(f"Error creating today's question: {e}")
                db.session.rollback()
                return None
        else:
            current_app.logger.warning("No content available for today's daily question")
            return None
    
    if question and question.status != 'published':
        question.status = 'published'
        question.published_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(f"Auto-published daily question #{question.question_number}")
    
    return question
