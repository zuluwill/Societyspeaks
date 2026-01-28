"""
News Transparency Routes

Main routes:
- /news: Dashboard showing articles from all 140+ sources (subscriber-only)
- /api/news/perspectives/<id>: Lazy-load perspectives (subscriber-only)
"""

from flask import render_template, session, jsonify, current_app, request
from flask_login import current_user
from datetime import date, datetime, timedelta
from typing import List, Dict
from sqlalchemy.orm import joinedload
from app.news import news_bp
from app.news.selector import NewsPageSelector, get_topic_leaning
from app.models import (
    DailyBriefSubscriber,
    TrendingTopic,
    BriefItem,
    DailyBrief,
    NewsPerspectiveCache,
    NewsSource,
    NewsArticle,
    db
)
from app.brief.coverage_analyzer import CoverageAnalyzer
from app import limiter, cache
import logging
import json

logger = logging.getLogger(__name__)

# Import thresholds from CoverageAnalyzer (single source of truth)
LEFT_THRESHOLD = CoverageAnalyzer.LEFT_THRESHOLD
RIGHT_THRESHOLD = CoverageAnalyzer.RIGHT_THRESHOLD

# Article limits to prevent unbounded queries
MAX_TOTAL_ARTICLES = 500  # Max articles to fetch from DB
MAX_ARTICLES_PER_COLUMN = 150  # Max articles per leaning column

# Cache key for dashboard data
DASHBOARD_CACHE_KEY = 'news_dashboard_data'
DASHBOARD_CACHE_TTL = 180  # 3 minutes

# Podcast detection keywords
PODCAST_KEYWORDS = ['podcast', 'show', 'huberman', 'ferriss', 'fridman', 'ezra klein', 
                   'triggernometry', 'all-in', 'acquired', 'modern wisdom', 'diary of a ceo',
                   'news agents', 'rest is politics']


def _is_podcast(name: str) -> bool:
    """Check if a source name matches podcast patterns."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in PODCAST_KEYWORDS)


def _get_dashboard_data():
    """
    Fetch and organize dashboard data with Redis caching.
    Returns cached data if available, otherwise fetches from DB.
    """
    # Try cache first
    cached = cache.get(DASHBOARD_CACHE_KEY)
    if cached:
        logger.debug("News dashboard: serving from cache")
        return json.loads(cached)
    
    logger.debug("News dashboard: cache miss, fetching from database")
    
    # Get all active sources with their political leanings
    sources = NewsSource.query.filter(
        NewsSource.is_active == True
    ).order_by(NewsSource.political_leaning.nullsfirst()).all()

    # Categorize sources by leaning
    left_sources = []
    center_sources = []
    right_sources = []
    
    for source in sources:
        leaning = source.political_leaning or 0
        source_is_podcast = _is_podcast(source.name)
        source_data = {
            'id': source.id,
            'name': source.name,
            'leaning': leaning,
            'leaning_label': get_leaning_label(leaning),
            'country': source.country,
            'source_type': 'podcast' if source_is_podcast else 'news',
            'is_podcast': source_is_podcast
        }
        if leaning <= LEFT_THRESHOLD:
            left_sources.append(source_data)
        elif leaning >= RIGHT_THRESHOLD:
            right_sources.append(source_data)
        else:
            center_sources.append(source_data)

    # Get articles from last 24 hours with eager-loaded sources
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    # Get all source IDs
    source_ids = [s.id for s in sources]
    
    # Fetch articles from last 24 hours with hard limit for scalability
    # Uses composite index on (published_at DESC, source_id)
    articles = NewsArticle.query.filter(
        NewsArticle.published_at >= cutoff,
        NewsArticle.source_id.in_(source_ids)
    ).options(
        joinedload(NewsArticle.source)
    ).order_by(NewsArticle.published_at.desc()).limit(MAX_TOTAL_ARTICLES).all()

    # Prepare article data organized by source leaning
    left_articles = []
    center_articles = []
    right_articles = []
    
    # Build source lookup for podcast detection
    source_lookup = {s['id']: s for s in left_sources + center_sources + right_sources}
    
    for article in articles:
        source = article.source
        if not source:
            continue
            
        leaning = source.political_leaning or 0
        source_info = source_lookup.get(source.id, {})
        article_data = {
            'id': article.id,
            'title': article.title,
            'url': article.url,
            'summary': article.summary,
            'published_at': article.published_at.isoformat() if article.published_at else None,
            'source_id': source.id,
            'source_name': source.name,
            'source_leaning': leaning,
            'leaning_label': get_leaning_label(leaning),
            'sensationalism_score': article.sensationalism_score,
            'relevance_score': article.relevance_score,
            'is_podcast': source_info.get('is_podcast', False),
            'source_type': source_info.get('source_type', 'news')
        }
        
        if leaning <= LEFT_THRESHOLD:
            left_articles.append(article_data)
        elif leaning >= RIGHT_THRESHOLD:
            right_articles.append(article_data)
        else:
            center_articles.append(article_data)

    # Apply per-column limits (articles already sorted by published_at desc)
    left_articles = left_articles[:MAX_ARTICLES_PER_COLUMN]
    center_articles = center_articles[:MAX_ARTICLES_PER_COLUMN]
    right_articles = right_articles[:MAX_ARTICLES_PER_COLUMN]

    # Calculate coverage balance
    total_articles = len(left_articles) + len(center_articles) + len(right_articles)
    coverage = {
        'left_pct': round((len(left_articles) / total_articles * 100)) if total_articles > 0 else 0,
        'center_pct': round((len(center_articles) / total_articles * 100)) if total_articles > 0 else 0,
        'right_pct': round((len(right_articles) / total_articles * 100)) if total_articles > 0 else 0,
        'left_count': len(left_articles),
        'center_count': len(center_articles),
        'right_count': len(right_articles),
        'total': total_articles
    }

    # Track which sources actually have articles (for filter dropdown)
    sources_with_articles = set()
    for article in left_articles + center_articles + right_articles:
        sources_with_articles.add(article['source_id'])
    
    # Filter source lists to only include those with articles
    left_sources = [s for s in left_sources if s['id'] in sources_with_articles]
    center_sources = [s for s in center_sources if s['id'] in sources_with_articles]
    right_sources = [s for s in right_sources if s['id'] in sources_with_articles]

    logger.info(
        f"News dashboard: {total_articles} articles from {len(sources)} sources "
        f"({len(left_articles)} left, {len(center_articles)} center, {len(right_articles)} right)"
    )

    result = {
        'left_articles': left_articles,
        'center_articles': center_articles,
        'right_articles': right_articles,
        'left_sources': left_sources,
        'center_sources': center_sources,
        'right_sources': right_sources,
        'coverage': coverage
    }
    
    # Cache the result
    try:
        cache.set(DASHBOARD_CACHE_KEY, json.dumps(result), timeout=DASHBOARD_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Failed to cache dashboard data: {e}")
    
    return result


def _parse_cached_articles(articles: List[Dict]) -> List[Dict]:
    """Convert ISO date strings back to datetime objects for template rendering."""
    for article in articles:
        if article.get('published_at'):
            article['published_at'] = datetime.fromisoformat(article['published_at'])
    return articles


def _filter_articles_by_search(articles: List[Dict], search_term: str) -> List[Dict]:
    """Filter articles by search term (matches title or summary)."""
    if not search_term:
        return articles
    search_lower = search_term.lower()
    return [
        a for a in articles
        if search_lower in (a.get('title') or '').lower()
        or search_lower in (a.get('summary') or '').lower()
        or search_lower in (a.get('source_name') or '').lower()
    ]


@news_bp.route('/news')
@limiter.limit("60/minute")
def dashboard():
    """
    News transparency dashboard - open to everyone.

    Shows top articles from all 140+ sources across the political spectrum.
    Users can filter by source and by political leaning.
    """
    search_term = request.args.get('q', '').strip()
    
    # Check subscriber status for personalization (not access control)
    subscriber = None
    is_subscriber = False

    if 'brief_subscriber_id' in session:
        subscriber = DailyBriefSubscriber.query.get(session['brief_subscriber_id'])
        if subscriber and subscriber.is_subscribed_eligible():
            is_subscriber = True

    # Admins always marked as subscriber for UI consistency
    if current_user.is_authenticated and current_user.is_admin:
        is_subscriber = True

    try:
        # Get cached or fresh dashboard data
        data = _get_dashboard_data()
        
        # Parse datetime strings for template rendering
        left_articles = _parse_cached_articles(data['left_articles'])
        center_articles = _parse_cached_articles(data['center_articles'])
        right_articles = _parse_cached_articles(data['right_articles'])
        
        # Apply search filter if provided
        if search_term:
            left_articles = _filter_articles_by_search(left_articles, search_term)
            center_articles = _filter_articles_by_search(center_articles, search_term)
            right_articles = _filter_articles_by_search(right_articles, search_term)

        # Recalculate coverage for search results
        total_articles = len(left_articles) + len(center_articles) + len(right_articles)
        coverage = {
            'left_pct': round((len(left_articles) / total_articles * 100)) if total_articles > 0 else 0,
            'center_pct': round((len(center_articles) / total_articles * 100)) if total_articles > 0 else 0,
            'right_pct': round((len(right_articles) / total_articles * 100)) if total_articles > 0 else 0,
            'left_count': len(left_articles),
            'center_count': len(center_articles),
            'right_count': len(right_articles),
            'total': total_articles
        } if search_term else data['coverage']

        return render_template(
            'news/dashboard.html',
            left_articles=left_articles,
            center_articles=center_articles,
            right_articles=right_articles,
            left_sources=data['left_sources'],
            center_sources=data['center_sources'],
            right_sources=data['right_sources'],
            coverage=coverage,
            subscriber=subscriber,
            is_subscriber=is_subscriber,
            show_email_capture=(not is_subscriber),
            today=date.today(),
            search_term=search_term
        )

    except Exception as e:
        logger.error(f"Error loading news dashboard: {e}", exc_info=True)
        return render_template(
            'errors/500.html',
            error_message="Failed to load news dashboard. Please try again later."
        ), 500


def get_leaning_label(leaning: float) -> str:
    """Convert numeric leaning to human-readable label based on AllSides ratings."""
    if leaning is None:
        return 'Unknown'
    if leaning <= -1.5:
        return 'Left'
    elif leaning <= -0.5:
        return 'Centre-Left'
    elif leaning >= 1.5:
        return 'Right'
    elif leaning >= 0.5:
        return 'Centre-Right'
    else:
        return 'Centre'


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
    from sqlalchemy.orm import joinedload
    from app.models import TrendingTopicArticle, NewsArticle

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

    # Batch prefetch all article links for all topics in a single query
    source_links_map = batch_prefetch_source_links(topic_ids)

    for topic in topics:
        try:
            # Check if in today's brief (using pre-loaded map)
            brief_item = brief_items_map.get(topic.id)

            # Get source links from prefetched map
            source_links = source_links_map.get(topic.id, {'left': [], 'center': [], 'right': []})

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
                    'dominant_leaning': get_dominant_leaning(brief_item.coverage_distribution),
                    'civic_score': topic.civic_score,
                    'source_links': source_links
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
                    'dominant_leaning': get_dominant_leaning(coverage.get('distribution', {})),
                    'civic_score': topic.civic_score,
                    'source_links': source_links
                })

        except Exception as e:
            logger.warning(f"Error preparing data for topic {topic.id}: {e}")
            # Skip this topic on error
            continue

    return result


def batch_prefetch_source_links(topic_ids: List[int]) -> Dict[int, Dict]:
    """
    Batch prefetch all article links for multiple topics in a single query.

    This eliminates N+1 queries by fetching all TrendingTopicArticle rows
    along with their NewsArticle and NewsSource data in one shot.

    Args:
        topic_ids: List of TrendingTopic IDs to fetch

    Returns:
        dict: {topic_id: {'left': [...], 'center': [...], 'right': [...]}}
    """
    from sqlalchemy.orm import joinedload
    from app.models import TrendingTopicArticle, NewsArticle

    # Thresholds matching CoverageAnalyzer
    LEFT_THRESHOLD = -0.5
    RIGHT_THRESHOLD = 0.5

    # Initialize empty result for all topics
    result = {tid: {'left': [], 'center': [], 'right': []} for tid in topic_ids}

    if not topic_ids:
        return result

    try:
        # Single query to get all article links with eager loading
        article_links = TrendingTopicArticle.query.filter(
            TrendingTopicArticle.topic_id.in_(topic_ids)
        ).options(
            joinedload(TrendingTopicArticle.article).joinedload(NewsArticle.source)
        ).all()

        for link in article_links:
            article = link.article
            if not article or not article.url:
                continue

            source = article.source
            source_name = source.name if source else 'Unknown'
            leaning = source.political_leaning if source else 0

            link_data = {
                'name': source_name,
                'url': article.url,
                'title': article.title or 'Read Article'
            }

            topic_links = result.get(link.topic_id)
            if not topic_links:
                continue

            if leaning is not None and leaning <= LEFT_THRESHOLD:
                topic_links['left'].append(link_data)
            elif leaning is not None and leaning >= RIGHT_THRESHOLD:
                topic_links['right'].append(link_data)
            else:
                topic_links['center'].append(link_data)

    except Exception as e:
        logger.warning(f"Error batch prefetching source links: {e}")

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
