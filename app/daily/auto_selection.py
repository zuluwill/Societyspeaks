"""
Automatic Daily Question Selection Service

Selects the next daily question from curated content sources:
1. Existing discussion topics (primary)
2. Published trending topics with high civic scores
3. Statements from active discussions

Uses ENGAGEMENT-WEIGHTED SELECTION to maximize participation:
- Civic relevance score
- Timeliness (recency of topic)
- Statement clarity (shorter = higher engagement)
- Historical performance (learn from past questions)
- Position diversity (alternate pro/con/neutral)

Avoids repeating content within a configurable time window.
"""

from datetime import date, datetime, timedelta
from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from app import db
from app.models import (
    DailyQuestion,
    DailyQuestionSelection,
    Discussion,
    TrendingTopic,
    Statement,
    DailyQuestionResponse
)
import random
import math


AVOID_REPEAT_DAYS = 30
MIN_CIVIC_SCORE = 0.5

# Engagement scoring weights
WEIGHT_CIVIC = 0.25        # Civic importance
WEIGHT_TIMELINESS = 0.25   # How recent/relevant
WEIGHT_CLARITY = 0.20      # Statement clarity (shorter = better)
WEIGHT_CONTROVERSY = 0.15  # Potential for divided opinions (engagement driver)
WEIGHT_HISTORICAL = 0.15   # Learn from past performance


def calculate_timeliness_score(created_at):
    """
    Score based on recency. Newer content is more engaging.
    Returns 0-1 score with exponential decay over 14 days.
    """
    if not created_at:
        return 0.5  # Default for missing dates

    days_old = (datetime.utcnow() - created_at).days
    # Exponential decay: score = e^(-days/7)
    # 0 days = 1.0, 7 days = 0.37, 14 days = 0.14
    return math.exp(-days_old / 7)


def calculate_clarity_score(text):
    """
    Score based on statement clarity. Shorter, clearer statements engage better.
    Optimal length: 50-100 characters. Penalize very short or very long.
    """
    if not text:
        return 0.5

    length = len(text)

    # Optimal range: 50-100 chars
    if 50 <= length <= 100:
        return 1.0
    elif length < 50:
        # Too short might lack context
        return 0.7 + (length / 50) * 0.3
    elif length <= 150:
        # Slightly long is okay
        return 1.0 - ((length - 100) / 100) * 0.3
    else:
        # Long statements lose engagement
        return max(0.3, 0.7 - ((length - 150) / 200) * 0.4)


def calculate_controversy_potential(statement_text):
    """
    Estimate controversy potential from statement text.
    Controversial (divisive) topics drive more engagement.

    Looks for indicators of debatable claims.
    """
    if not statement_text:
        return 0.5

    text_lower = statement_text.lower()

    # Words that indicate debatable positions (higher controversy)
    divisive_indicators = [
        'should', 'must', 'need to', 'have to', 'ought to',
        'best', 'worst', 'better', 'worse',
        'always', 'never', 'every', 'none',
        'right', 'wrong', 'fair', 'unfair',
        'too much', 'too little', 'enough', 'not enough',
        'ban', 'allow', 'require', 'mandatory', 'optional'
    ]

    # Words that indicate neutral/factual statements (lower controversy)
    neutral_indicators = [
        'may', 'might', 'could', 'perhaps', 'possibly',
        'some', 'sometimes', 'often', 'occasionally'
    ]

    divisive_count = sum(1 for indicator in divisive_indicators if indicator in text_lower)
    neutral_count = sum(1 for indicator in neutral_indicators if indicator in text_lower)

    # Base score of 0.5, adjusted by indicators
    score = 0.5 + (divisive_count * 0.1) - (neutral_count * 0.05)
    return max(0.2, min(1.0, score))


def get_historical_performance(topic_category=None, days_lookback=30):
    """
    Learn from historical daily question performance.
    Returns average response rate for similar topics.
    """
    cutoff = datetime.utcnow() - timedelta(days=days_lookback)

    query = db.session.query(
        func.avg(func.count(DailyQuestionResponse.id))
    ).join(DailyQuestion).filter(
        DailyQuestion.question_date >= cutoff.date(),
        DailyQuestion.status == 'published'
    )

    if topic_category:
        query = query.filter(DailyQuestion.topic_category == topic_category)

    query = query.group_by(DailyQuestion.id)

    # Get average responses per question
    results = db.session.query(
        DailyQuestion.topic_category,
        func.count(DailyQuestionResponse.id).label('response_count')
    ).outerjoin(DailyQuestionResponse).filter(
        DailyQuestion.question_date >= cutoff.date(),
        DailyQuestion.status == 'published'
    ).group_by(DailyQuestion.id, DailyQuestion.topic_category).all()

    if not results:
        return 0.5  # No history, neutral score

    # Calculate average by category
    category_totals = {}
    category_counts = {}
    overall_total = 0
    overall_count = 0

    for cat, count in results:
        overall_total += count
        overall_count += 1
        if cat:
            category_totals[cat] = category_totals.get(cat, 0) + count
            category_counts[cat] = category_counts.get(cat, 0) + 1

    overall_avg = overall_total / overall_count if overall_count > 0 else 0

    if topic_category and topic_category in category_totals:
        cat_avg = category_totals[topic_category] / category_counts[topic_category]
        # Score relative to overall average
        if overall_avg > 0:
            return min(1.0, cat_avg / (overall_avg * 2))

    return 0.5  # Neutral for unknown categories


def calculate_statement_engagement_score(statement, discussion=None):
    """
    Calculate comprehensive engagement score for a statement.
    Returns 0-1 score where higher = more likely to engage users.
    """
    scores = {}

    # 1. Civic relevance (from discussion topic if available)
    if discussion and hasattr(discussion, 'civic_score') and discussion.civic_score:
        scores['civic'] = discussion.civic_score
    else:
        scores['civic'] = 0.6  # Default moderate civic value

    # 2. Timeliness
    created_at = statement.created_at if hasattr(statement, 'created_at') else None
    scores['timeliness'] = calculate_timeliness_score(created_at)

    # 3. Clarity
    text = statement.content if hasattr(statement, 'content') else str(statement)
    scores['clarity'] = calculate_clarity_score(text)

    # 4. Controversy potential
    scores['controversy'] = calculate_controversy_potential(text)

    # 5. Historical performance
    topic = discussion.topic if discussion and hasattr(discussion, 'topic') else None
    scores['historical'] = get_historical_performance(topic)

    # Weighted combination
    total_score = (
        scores['civic'] * WEIGHT_CIVIC +
        scores['timeliness'] * WEIGHT_TIMELINESS +
        scores['clarity'] * WEIGHT_CLARITY +
        scores['controversy'] * WEIGHT_CONTROVERSY +
        scores['historical'] * WEIGHT_HISTORICAL
    )

    return total_score, scores


def calculate_topic_engagement_score(topic):
    """
    Calculate engagement score for a trending topic.
    """
    scores = {}

    # 1. Civic score (direct from topic)
    scores['civic'] = topic.civic_score or 0.5

    # 2. Timeliness
    scores['timeliness'] = calculate_timeliness_score(topic.created_at)

    # 3. Quality score as proxy for clarity
    scores['clarity'] = topic.quality_score or 0.5

    # 4. Controversy potential from seed statements
    if topic.seed_statements:
        controversy_scores = [calculate_controversy_potential(s) for s in topic.seed_statements[:3]]
        scores['controversy'] = sum(controversy_scores) / len(controversy_scores)
    else:
        scores['controversy'] = 0.5

    # 5. Historical performance
    scores['historical'] = get_historical_performance(topic.topic)

    # Weighted combination
    total_score = (
        scores['civic'] * WEIGHT_CIVIC +
        scores['timeliness'] * WEIGHT_TIMELINESS +
        scores['clarity'] * WEIGHT_CLARITY +
        scores['controversy'] * WEIGHT_CONTROVERSY +
        scores['historical'] * WEIGHT_HISTORICAL
    )

    return total_score, scores


def weighted_random_choice(items, scores):
    """
    Select item using weighted random selection based on engagement scores.
    Higher scores = higher probability of selection, but not deterministic.
    """
    if not items or not scores:
        return None

    if len(items) != len(scores):
        return random.choice(items)

    # Ensure all scores are positive
    min_score = min(scores)
    if min_score <= 0:
        scores = [s - min_score + 0.1 for s in scores]

    # Use scores as weights for random selection
    return random.choices(items, weights=scores, k=1)[0]


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
    Select the next question source using ENGAGEMENT-WEIGHTED selection.

    Priority order:
    1. Seed statements from curated discussions (THE main source)
    2. High-quality trending topics (use their seed statements)
    3. Direct statements as fallback

    Selection is weighted by engagement potential:
    - Civic relevance
    - Timeliness (recent topics)
    - Statement clarity
    - Controversy potential (divisive = engaging)
    - Historical performance of similar topics

    Key insight: Daily questions should be actual voteable statements,
    not just discussion titles. Users need specific claims to agree/disagree with.
    """
    # Try discussions first - collect all eligible statements with scores
    discussions = get_eligible_discussions()
    all_discussion_statements = []

    for discussion in discussions[:15]:  # Check more discussions
        seed_statements = Statement.query.filter_by(
            discussion_id=discussion.id,
            is_seed=True
        ).all()
        for stmt in seed_statements:
            score, breakdown = calculate_statement_engagement_score(stmt, discussion)
            all_discussion_statements.append({
                'statement': stmt,
                'discussion': discussion,
                'score': score,
                'breakdown': breakdown
            })

    if all_discussion_statements:
        # Sort by score and take top candidates
        all_discussion_statements.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = all_discussion_statements[:10]

        # Weighted random selection from top candidates
        scores = [c['score'] for c in top_candidates]
        selected = weighted_random_choice(top_candidates, scores)

        if selected:
            current_app.logger.info(
                f"Selected statement with engagement score {selected['score']:.2f} "
                f"(civic={selected['breakdown']['civic']:.2f}, "
                f"timeliness={selected['breakdown']['timeliness']:.2f}, "
                f"clarity={selected['breakdown']['clarity']:.2f}, "
                f"controversy={selected['breakdown']['controversy']:.2f})"
            )
            return {
                'source_type': 'discussion',
                'source': selected['discussion'],
                'statement': selected['statement'],
                'question_text': selected['statement'].content,
                'context': selected['discussion'].title,
                'topic_category': selected['discussion'].topic,
                'discussion_slug': selected['discussion'].slug,
                'engagement_score': selected['score']
            }

    # Try trending topics with engagement scoring
    topics = get_eligible_trending_topics()
    if topics:
        topics_with_statements = [topic for topic in topics if topic.seed_statements]
        if topics_with_statements:
            # Score each topic
            scored_topics = []
            for topic in topics_with_statements:
                score, breakdown = calculate_topic_engagement_score(topic)
                scored_topics.append({
                    'topic': topic,
                    'score': score,
                    'breakdown': breakdown
                })

            # Sort and take top candidates
            scored_topics.sort(key=lambda x: x['score'], reverse=True)
            top_topics = scored_topics[:8]

            # Weighted random selection
            scores = [t['score'] for t in top_topics]
            selected = weighted_random_choice(top_topics, scores)

            if selected:
                topic = selected['topic']
                # Also score the seed statements and pick best one
                seed_scores = [
                    (s, calculate_controversy_potential(s))
                    for s in topic.seed_statements[:5]
                ]
                seed_scores.sort(key=lambda x: x[1], reverse=True)
                best_statement = seed_scores[0][0] if seed_scores else topic.seed_statements[0]

                current_app.logger.info(
                    f"Selected trending topic with engagement score {selected['score']:.2f}"
                )
                return {
                    'source_type': 'trending',
                    'source': topic,
                    'statement': None,
                    'question_text': best_statement,
                    'context': topic.summary[:300] if topic.summary else None,
                    'topic_category': topic.topic,
                    'discussion_slug': None,
                    'engagement_score': selected['score']
                }

    # Fallback to standalone statements with scoring
    statements = get_eligible_statements()
    if statements:
        scored_statements = []
        for stmt in statements[:20]:
            score, breakdown = calculate_statement_engagement_score(stmt, stmt.discussion)
            scored_statements.append({
                'statement': stmt,
                'score': score,
                'breakdown': breakdown
            })

        scored_statements.sort(key=lambda x: x['score'], reverse=True)
        top_statements = scored_statements[:10]

        scores = [s['score'] for s in top_statements]
        selected = weighted_random_choice(top_statements, scores)

        if selected:
            stmt = selected['statement']
            return {
                'source_type': 'statement',
                'source': stmt,
                'statement': stmt,
                'question_text': stmt.content,
                'context': stmt.discussion.title if stmt.discussion else None,
                'topic_category': stmt.discussion.topic if stmt.discussion else None,
                'discussion_slug': stmt.discussion.slug if stmt.discussion else None,
                'engagement_score': selected['score']
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
