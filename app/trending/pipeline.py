"""
Trending Topics Pipeline Orchestrator

Coordinates the full pipeline:
1. Fetch news from sources
2. Score articles for sensationalism
3. Cluster similar articles
4. Score topics for civic relevance
5. Generate seed statements
6. Apply publish rules
"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple

from app import db
from app.models import NewsArticle, TrendingTopic, TrendingTopicArticle
from app.trending.news_fetcher import NewsFetcher, seed_default_sources
from app.trending.scorer import score_articles_with_llm, score_topic
from app.trending.clustering import cluster_articles, create_topic_from_cluster
from app.trending.seed_generator import generate_seed_statements

logger = logging.getLogger(__name__)


def run_pipeline(hold_minutes: int = 60) -> Tuple[int, int, int]:
    """
    Run the full trending topics pipeline.
    
    Returns: (articles_fetched, topics_created, topics_ready_for_review)
    """
    logger.info("Starting trending topics pipeline")
    
    seed_default_sources()
    
    fetcher = NewsFetcher()
    articles = fetcher.fetch_all_sources()
    logger.info(f"Fetched {len(articles)} new articles")
    
    if articles:
        try:
            # Use no_autoflush to prevent query-invoked autoflush issues during LLM scoring
            with db.session.no_autoflush:
                articles = score_articles_with_llm(articles)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error scoring articles: {e}")
            db.session.rollback()
    
    try:
        from app.models import NewsSource
        # Use no_autoflush to prevent autoflush during query
        with db.session.no_autoflush:
            premium_unscored = NewsArticle.query.join(NewsSource).filter(
                NewsArticle.relevance_score.is_(None),
                NewsSource.reputation_score >= 0.7,
                NewsArticle.fetched_at >= datetime.utcnow() - timedelta(days=7)
            ).all()
        
        if premium_unscored:
            logger.info(f"Scoring {len(premium_unscored)} unscored premium source articles")
            with db.session.no_autoflush:
                score_articles_with_llm(premium_unscored)
            db.session.commit()
    except Exception as e:
        logger.error(f"Error scoring premium articles: {e}")
        db.session.rollback()
    
    try:
        unprocessed = NewsArticle.query.filter(
            NewsArticle.fetched_at >= datetime.utcnow() - timedelta(hours=6),
            NewsArticle.relevance_score.isnot(None),
            NewsArticle.relevance_score >= 0.4
        ).all()
    except Exception as e:
        logger.error(f"Error querying unprocessed articles: {e}")
        db.session.rollback()
        return len(articles), 0, 0
    
    try:
        processed_ids = set()
        for (article_id,) in db.session.query(TrendingTopicArticle.article_id).distinct().all():
            processed_ids.add(article_id)
    except Exception as e:
        logger.error(f"Error querying processed article IDs: {e}")
        db.session.rollback()
        processed_ids = set()
    
    articles_to_cluster = [a for a in unprocessed if a.id not in processed_ids]
    
    if len(articles_to_cluster) < 2:
        logger.info("Not enough new articles to cluster")
        return len(articles), 0, 0
    
    clusters = cluster_articles(articles_to_cluster, threshold=0.7)
    logger.info(f"Created {len(clusters)} clusters")
    
    topics_created = 0
    for cluster in clusters:
        if len(cluster) >= 2:  # Require at least 2 articles for a new topic
            try:
                topic = create_topic_from_cluster(cluster, hold_minutes=hold_minutes)
                if topic:
                    topics_created += 1
            except Exception as e:
                logger.error(f"Error creating topic from cluster: {e}")
                db.session.rollback()
                continue
        elif len(cluster) == 1:
            # Single articles: try to match to existing topics
            try:
                _backfill_single_article(cluster[0])
            except Exception as e:
                logger.warning(f"Failed to backfill article {cluster[0].id}: {e}")
                db.session.rollback()
    
    ready_count = process_held_topics()
    
    logger.info(f"Pipeline complete: {len(articles)} articles, {topics_created} topics, {ready_count} ready for review")
    
    return len(articles), topics_created, ready_count


def process_held_topics(batch_size: int = 10) -> int:
    """
    Process topics that have completed their hold window.
    Score them and move to pending_review.
    Processes in batches with error handling per topic.
    """
    now = datetime.utcnow()
    
    held_topics = TrendingTopic.query.filter(
        TrendingTopic.status == 'pending',
        TrendingTopic.hold_until <= now
    ).order_by(TrendingTopic.created_at.desc()).limit(batch_size).all()
    
    if not held_topics:
        return 0
    
    logger.info(f"Processing {len(held_topics)} held topics (batch of {batch_size})")
    
    ready_count = 0
    
    for topic in held_topics:
        try:
            topic = score_topic(topic)
            
            seeds = generate_seed_statements(topic, count=7)
            topic.seed_statements = seeds
            
            topic.status = 'pending_review'
            ready_count += 1
            
            db.session.commit()
            
            logger.info(f"Topic {topic.id} ready for review: {topic.title[:50]}...")
            
        except Exception as e:
            logger.error(f"Failed to process topic {topic.id}: {e}")
            db.session.rollback()
            continue
    
    return ready_count


def _get_topic_political_leaning(topic: TrendingTopic) -> str:
    """Get the dominant political leaning of a topic's sources."""
    leanings = []
    for ta in topic.articles:
        if ta.article and ta.article.source and ta.article.source.political_leaning is not None:
            pl = ta.article.source.political_leaning
            if pl <= -1.5:
                leanings.append('left')
            elif pl < -0.5:
                leanings.append('centre-left')
            elif pl <= 0.5:
                leanings.append('centre')
            elif pl < 1.5:
                leanings.append('centre-right')
            else:
                leanings.append('right')
    
    if not leanings:
        return 'centre'
    
    from collections import Counter
    return Counter(leanings).most_common(1)[0][0]


def auto_publish_daily(max_topics: int = 15, schedule_bluesky: bool = True, schedule_x: bool = True) -> int:
    """
    Auto-publish up to max_topics diverse topics daily.
    Selects topics from trusted sources with civic relevance.
    Ensures diversity by checking title similarity AND political leaning balance.
    Enforces once-per-day limit by checking already-published today.
    
    Args:
        max_topics: Maximum topics to publish
        schedule_bluesky: If True, schedule Bluesky posts for staggered times throughout the day
                         (2pm, 4pm, 6pm, 8pm, 10pm UTC = 9am, 11am, 1pm, 3pm, 5pm EST)
        schedule_x: If True, schedule X posts for staggered times throughout the day
    """
    from app.models import User
    from app.trending.publisher import publish_topic
    from collections import Counter
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    already_published_today = TrendingTopic.query.filter(
        TrendingTopic.status == 'published',
        TrendingTopic.published_at >= today_start
    ).count()
    
    if already_published_today >= max_topics:
        logger.info(f"Already published {already_published_today} topics today, skipping auto-publish")
        return 0
    
    remaining_slots = max_topics - already_published_today
    
    topics = TrendingTopic.query.filter_by(status='pending_review').order_by(
        TrendingTopic.civic_score.desc().nullslast(),
        TrendingTopic.created_at.desc()
    ).all()
    
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        logger.error("No admin user found for auto-publish")
        return 0
    
    published = 0
    published_keywords = set()
    published_leanings = Counter()
    skipped_similar = 0
    skipped_criteria = 0
    skipped_balance = 0
    
    for topic in topics:
        if published >= remaining_slots:
            break
            
        if not topic.should_auto_publish:
            skipped_criteria += 1
            continue
        
        title_words = set(topic.title.lower().split())
        title_words -= {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by'}
        
        if published_keywords and len(title_words & published_keywords) >= 3:
            logger.info(f"Skipping topic {topic.id} - too similar to already published: {topic.title[:40]}...")
            skipped_similar += 1
            continue
        
        topic_leaning = _get_topic_political_leaning(topic)
        
        left_count = published_leanings.get('left', 0) + published_leanings.get('centre-left', 0)
        right_count = published_leanings.get('right', 0) + published_leanings.get('centre-right', 0)
        
        if topic_leaning in ('left', 'centre-left'):
            new_left = left_count + 1
            if new_left > right_count + 1:
                logger.info(f"Skipping topic {topic.id} - would create political imbalance ({new_left}:{right_count} L:R): {topic.title[:40]}...")
                skipped_balance += 1
                continue
        elif topic_leaning in ('right', 'centre-right'):
            new_right = right_count + 1
            if new_right > left_count + 1:
                logger.info(f"Skipping topic {topic.id} - would create political imbalance ({left_count}:{new_right} L:R): {topic.title[:40]}...")
                skipped_balance += 1
                continue
        
        try:
            publish_topic(
                topic, 
                admin,
                schedule_bluesky=schedule_bluesky,
                schedule_x=schedule_x,
                bluesky_slot_index=published,
                x_slot_index=published
            )
            published += 1
            published_keywords.update(title_words)
            published_leanings[topic_leaning] += 1
            logger.info(f"Auto-published topic {topic.id} ({topic_leaning}): {topic.title[:50]}...")
        except Exception as e:
            logger.error(f"Failed to auto-publish topic {topic.id}: {e}")
            db.session.rollback()
            continue
    
    logger.info(f"Auto-publish summary: {published} published, {skipped_similar} similar, {skipped_criteria} criteria, {skipped_balance} balance")
    logger.info(f"Political balance: {dict(published_leanings)}")
    return published


def auto_publish_high_confidence() -> int:
    """Legacy function - calls auto_publish_daily for backwards compatibility."""
    return auto_publish_daily(max_topics=15)


def get_review_queue(page: int = 1, per_page: int = 50):
    """
    Get a paginated review queue.

    The dashboard only needs topic-level fields for list rendering, so we avoid
    eager-loading dynamic relationships here and rely on pagination to bound
    query time and payload size.
    """
    safe_page = max(1, int(page or 1))
    safe_per_page = max(1, min(int(per_page or 50), 100))

    return TrendingTopic.query.filter_by(
        status='pending_review'
    ).order_by(
        TrendingTopic.created_at.desc()
    ).paginate(
        page=safe_page,
        per_page=safe_per_page,
        error_out=False
    )


def get_pipeline_stats() -> dict:
    """Get statistics for the trending topics system."""
    from app.models import NewsSource, NewsArticle
    
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    
    return {
        'sources': {
            'total': NewsSource.query.count(),
            'active': NewsSource.query.filter_by(is_active=True).count()
        },
        'articles': {
            'total': NewsArticle.query.count(),
            'last_24h': NewsArticle.query.filter(NewsArticle.fetched_at >= day_ago).count(),
            'last_7d': NewsArticle.query.filter(NewsArticle.fetched_at >= week_ago).count()
        },
        'topics': {
            'pending': TrendingTopic.query.filter_by(status='pending').count(),
            'pending_review': TrendingTopic.query.filter_by(status='pending_review').count(),
            'published': TrendingTopic.query.filter_by(status='published').count(),
            'merged': TrendingTopic.query.filter_by(status='merged').count(),
            'discarded': TrendingTopic.query.filter_by(status='discarded').count()
        }
    }


def _backfill_single_article(
    article: NewsArticle,
    topic_embeddings_cache: dict = None
) -> bool:
    """
    Try to match a single article to an existing topic.
    Uses a lower similarity threshold than topic creation.
    
    Args:
        article: The article to backfill
        topic_embeddings_cache: Optional pre-computed dict of {topic_id: (topic, embedding_array)}
    
    Returns True if article was added to an existing topic.
    """
    import numpy as np
    from app.trending.clustering import get_embeddings
    
    if not article.title_embedding:
        text = f"{article.title}. {article.summary or ''}"
        embeddings = get_embeddings([text])
        if embeddings:
            article.title_embedding = embeddings[0] if isinstance(embeddings[0], list) else embeddings[0].tolist()
            db.session.commit()
        else:
            return False
    
    article_embedding = np.array(article.title_embedding)
    
    BACKFILL_THRESHOLD = 0.75
    best_match = None
    best_similarity = 0.0
    
    if topic_embeddings_cache:
        for topic_id, (topic, topic_embedding) in topic_embeddings_cache.items():
            similarity = np.dot(article_embedding, topic_embedding) / (
                np.linalg.norm(article_embedding) * np.linalg.norm(topic_embedding)
            )
            
            if similarity > best_similarity and similarity >= BACKFILL_THRESHOLD:
                best_similarity = float(similarity)
                best_match = topic
    else:
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_topics = TrendingTopic.query.filter(
            TrendingTopic.created_at >= cutoff,
            TrendingTopic.topic_embedding.isnot(None),
            TrendingTopic.status.in_(['pending', 'pending_review', 'approved', 'published'])
        ).all()
        
        for topic in recent_topics:
            if topic.topic_embedding:
                topic_embedding = np.array(topic.topic_embedding)
                similarity = np.dot(article_embedding, topic_embedding) / (
                    np.linalg.norm(article_embedding) * np.linalg.norm(topic_embedding)
                )
                
                if similarity > best_similarity and similarity >= BACKFILL_THRESHOLD:
                    best_similarity = float(similarity)
                    best_match = topic
    
    if best_match:
        existing_link = TrendingTopicArticle.query.filter_by(
            topic_id=best_match.id,
            article_id=article.id
        ).first()
        
        if not existing_link:
            link = TrendingTopicArticle(
                topic_id=best_match.id,
                article_id=article.id,
                similarity_score=best_similarity
            )
            db.session.add(link)
            
            best_match.source_count = len(set(
                ta.article.source_id for ta in best_match.articles if ta.article
            ))
            db.session.commit()
            
            logger.info(f"Backfilled article {article.id} to topic {best_match.id} (similarity: {best_similarity:.2f})")
            return True
    
    return False


def backfill_orphan_articles(limit: int = 100) -> int:
    """
    Find articles not linked to any topic and try to match them to existing topics.
    Runs periodically to enrich topics with more sources.
    
    Returns: Number of articles successfully backfilled.
    """
    import numpy as np
    
    cutoff = datetime.utcnow() - timedelta(days=7)
    
    linked_article_ids = db.session.query(TrendingTopicArticle.article_id).distinct()
    
    orphan_articles = NewsArticle.query.filter(
        NewsArticle.fetched_at >= cutoff,
        NewsArticle.relevance_score.isnot(None),
        NewsArticle.relevance_score >= 0.4,
        ~NewsArticle.id.in_(linked_article_ids)
    ).order_by(NewsArticle.fetched_at.desc()).limit(limit).all()
    
    if not orphan_articles:
        logger.info("No orphan articles to backfill")
        return 0
    
    logger.info(f"Attempting to backfill {len(orphan_articles)} orphan articles")
    
    recent_topics = TrendingTopic.query.filter(
        TrendingTopic.created_at >= cutoff,
        TrendingTopic.topic_embedding.isnot(None),
        TrendingTopic.status.in_(['pending', 'pending_review', 'approved', 'published'])
    ).all()
    
    topic_embeddings_cache = {}
    for topic in recent_topics:
        if topic.topic_embedding:
            topic_embeddings_cache[topic.id] = (topic, np.array(topic.topic_embedding))
    
    logger.info(f"Loaded {len(topic_embeddings_cache)} topic embeddings for similarity matching")
    
    backfilled = 0
    for article in orphan_articles:
        try:
            if _backfill_single_article(article, topic_embeddings_cache):
                backfilled += 1
        except Exception as e:
            logger.warning(f"Failed to backfill article {article.id}: {e}")
            try:
                db.session.rollback()
            except Exception:
                pass
            continue
    
    logger.info(f"Backfilled {backfilled} of {len(orphan_articles)} orphan articles")
    return backfilled
