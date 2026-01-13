"""
News Transparency Routes

Main routes:
- /news: Dashboard showing all topics from last 24h (subscriber-only)
- /api/news/perspectives/<id>: Lazy-load perspectives (subscriber-only)
"""

from flask import render_template, session, jsonify, current_app, request
from flask_login import current_user
from datetime import date, datetime, timedelta
from typing import List, Dict
from app.news import news_bp
from app.news.selector import NewsPageSelector, get_topic_leaning
from app.models import (
    DailyBriefSubscriber,
    TrendingTopic,
    BriefItem,
    DailyBrief,
    NewsPerspectiveCache,
    db
)
from app.brief.coverage_analyzer import CoverageAnalyzer
from app import limiter
import logging

logger = logging.getLogger(__name__)


@news_bp.route('/news')
@limiter.limit("60/minute")
def dashboard():
    """
    News transparency dashboard - subscriber only.

    Shows all published topics from last 24h with coverage analysis.
    Brief topics show full cached data, others show coverage with lazy-load button.
    """
    # Check subscriber eligibility (reuse brief pattern)
    subscriber = None
    is_subscriber = False

    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])
        if subscriber and subscriber.is_subscribed_eligible():
            is_subscriber = True

    # Admins can access
    if current_user.is_authenticated and current_user.is_admin:
        is_subscriber = True

    # Non-subscribers see landing page
    if not is_subscriber:
        return render_template('news/landing.html')

    # Get topics for today
    try:
        selector = NewsPageSelector()
        topics = selector.select_topics()

        # Limit to 50 topics for performance (pagination can be added later if needed)
        if len(topics) > 50:
            logger.info(f"Limiting dashboard to 50 topics (from {len(topics)} total)")
            topics = topics[:50]

        # Prepare hybrid data (brief vs non-brief)
        topic_data = prepare_news_page_data(topics)

        # Group by leaning for filter UI
        left_topics = [t for t in topic_data if t['dominant_leaning'] == 'left']
        center_topics = [t for t in topic_data if t['dominant_leaning'] == 'center']
        right_topics = [t for t in topic_data if t['dominant_leaning'] == 'right']

        logger.info(
            f"News dashboard: {len(topics)} topics total "
            f"({len(left_topics)} left, {len(center_topics)} center, {len(right_topics)} right)"
        )

        return render_template(
            'news/dashboard.html',
            topics=topic_data,
            left_topics=left_topics,
            center_topics=center_topics,
            right_topics=right_topics,
            subscriber=subscriber,
            total_topics=len(topics),
            today=date.today()
        )

    except Exception as e:
        logger.error(f"Error loading news dashboard: {e}", exc_info=True)
        return render_template(
            'errors/500.html',
            error_message="Failed to load news dashboard. Please try again later."
        ), 500


@news_bp.route('/api/news/perspectives/<int:topic_id>', methods=['POST'])
@limiter.limit("30/minute")  # More restrictive for expensive LLM calls
def load_perspectives(topic_id):
    """
    Load perspective analysis for a topic (lazy-load endpoint).

    Subscriber-only. Generates or retrieves cached perspective analysis.
    Returns JSON with perspectives, so_what, personal_impact.
    """
    # Verify this is an AJAX request (basic CSRF protection)
    if not request.is_json and not request.headers.get('X-Requested-With'):
        return jsonify({'error': 'Invalid request'}), 400

    # Verify subscription
    subscriber = None
    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])

    is_admin = current_user.is_authenticated and current_user.is_admin

    if not (subscriber and subscriber.is_subscribed_eligible()) and not is_admin:
        return jsonify({
            'error': 'Subscription required',
            'message': 'Subscribe to access full analysis.',
            'subscribe_url': '/brief/subscribe'
        }), 401

    # Get topic and validate it's published
    topic = TrendingTopic.query.get_or_404(topic_id)

    if topic.status != 'published':
        return jsonify({
            'error': 'Topic not available',
            'message': 'This topic is not published.'
        }), 404

    # Check if topic is from today (only show current topics)
    # Use selector's lookback hours for consistency
    from app.news.selector import NewsPageSelector
    selector = NewsPageSelector()
    cutoff = datetime.utcnow() - timedelta(hours=selector.lookback_hours)

    if not topic.published_at or topic.published_at < cutoff:
        return jsonify({
            'error': 'Topic not available',
            'message': 'This topic is no longer available for perspective analysis.'
        }), 404

    try:
        # Check if this topic is in today's brief (use cached data)
        brief_item = BriefItem.query.join(DailyBrief).filter(
            BriefItem.trending_topic_id == topic.id,
            DailyBrief.date == date.today(),
            DailyBrief.status == 'published'
        ).first()

        if brief_item:
            # Use cached brief data (free, instant)
            logger.info(f"Using cached brief data for topic {topic_id}")
            return jsonify({
                'topic_id': topic.id,
                'perspectives': brief_item.perspectives,
                'so_what': brief_item.so_what,
                'personal_impact': brief_item.personal_impact,
                'source': 'brief',
                'generated_at': brief_item.created_at.isoformat()
            })

        # Not in brief - check perspective cache
        cached = NewsPerspectiveCache.query.filter_by(
            trending_topic_id=topic.id,
            generated_date=date.today()
        ).first()

        if cached:
            # Use cached perspective (generated earlier today)
            logger.info(f"Using cached perspective for topic {topic_id}")
            return jsonify({
                'topic_id': topic.id,
                'perspectives': cached.perspectives,
                'so_what': cached.so_what,
                'personal_impact': cached.personal_impact,
                'source': 'cache',
                'generated_at': cached.generated_at.isoformat()
            })

        # Generate new perspective (expensive LLM call)
        logger.info(f"Generating new perspective for topic {topic_id}")
        from app.news.generator import generate_perspective_analysis

        result = generate_perspective_analysis(topic)

        return jsonify({
            'topic_id': topic.id,
            'perspectives': result['perspectives'],
            'so_what': result['so_what'],
            'personal_impact': result['personal_impact'],
            'source': 'generated',
            'generated_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error loading perspectives for topic {topic_id}: {e}", exc_info=True)
        return jsonify({
            'error': 'Generation failed',
            'message': 'Failed to generate perspective analysis. Please try again.'
        }), 500


def prepare_news_page_data(topics: List[TrendingTopic]) -> List[Dict]:
    """
    Prepare hybrid data: brief topics get full cached data, others get coverage only.

    Returns list of topic dicts with different content levels:
    - Brief topics: Full analysis + perspectives (cached, free)
    - Other topics: Coverage only, perspectives lazy-loaded (LLM on-demand)
    """
    result = []

    # Batch load all brief items for today to prevent N+1 queries
    topic_ids = [topic.id for topic in topics]
    brief_items_map = {
        bi.trending_topic_id: bi
        for bi in BriefItem.query.join(DailyBrief).filter(
            BriefItem.trending_topic_id.in_(topic_ids),
            DailyBrief.date == date.today(),
            DailyBrief.status == 'published'
        ).all()
    }

    for topic in topics:
        try:
            # Check if in today's brief (using pre-loaded map)
            brief_item = brief_items_map.get(topic.id)

            if brief_item:
                # Use cached brief data (FREE, instant)
                result.append({
                    'topic': topic,
                    'source': 'brief',
                    'headline': brief_item.headline,
                    'summary': brief_item.summary_bullets,
                    'coverage': {
                        'distribution': brief_item.coverage_distribution,
                        'imbalance': brief_item.coverage_imbalance,
                        'sources_by_leaning': brief_item.sources_by_leaning,
                        'source_count': brief_item.source_count
                    },
                    'perspectives': brief_item.perspectives,
                    'so_what': brief_item.so_what,
                    'personal_impact': brief_item.personal_impact,
                    'sensationalism': brief_item.sensationalism_label or 'unknown',
                    'is_lazy_load': False,
                    'dominant_leaning': get_dominant_leaning(brief_item.coverage_distribution)
                })
            else:
                # Compute coverage (fast, ~50ms, no LLM)
                analyzer = CoverageAnalyzer(topic)
                coverage = analyzer.calculate_distribution()

                result.append({
                    'topic': topic,
                    'source': 'published',
                    'headline': topic.title,
                    'summary': None,
                    'coverage': coverage,
                    'perspectives': None,  # Lazy-loaded
                    'so_what': None,
                    'personal_impact': None,
                    'sensationalism': analyzer.get_sensationalism_label(
                        coverage.get('sensationalism_avg', 0)
                    ),
                    'is_lazy_load': True,
                    'dominant_leaning': get_dominant_leaning(coverage.get('distribution', {}))
                })

        except Exception as e:
            logger.warning(f"Error preparing data for topic {topic.id}: {e}")
            # Skip this topic on error
            continue

    return result


def get_dominant_leaning(distribution: dict) -> str:
    """
    Return 'left', 'center', or 'right' based on highest percentage.

    Args:
        distribution: Dict with 'left', 'center', 'right' keys (0-1 values)

    Returns:
        'left', 'center', or 'right'
    """
    if not distribution:
        return 'center'

    left = distribution.get('left', 0)
    center = distribution.get('center', 0)
    right = distribution.get('right', 0)

    if left > max(center, right):
        return 'left'
    elif right > max(center, left):
        return 'right'
    else:
        return 'center'
