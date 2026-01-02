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
            articles = score_articles_with_llm(articles)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error scoring articles: {e}")
            db.session.rollback()
    
    try:
        from app.models import NewsSource
        premium_unscored = NewsArticle.query.join(NewsSource).filter(
            NewsArticle.sensationalism_score.is_(None),
            NewsSource.reputation_score >= 0.7,
            NewsArticle.fetched_at >= datetime.utcnow() - timedelta(days=7)
        ).all()
        
        if premium_unscored:
            logger.info(f"Scoring {len(premium_unscored)} unscored premium source articles")
            score_articles_with_llm(premium_unscored)
            db.session.commit()
    except Exception as e:
        logger.error(f"Error scoring premium articles: {e}")
        db.session.rollback()
    
    try:
        unprocessed = NewsArticle.query.filter(
            NewsArticle.fetched_at >= datetime.utcnow() - timedelta(hours=6),
            NewsArticle.sensationalism_score.isnot(None),
            NewsArticle.sensationalism_score <= 0.5
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
        if len(cluster) >= 1:
            try:
                topic = create_topic_from_cluster(cluster, hold_minutes=hold_minutes)
                if topic:
                    topics_created += 1
            except Exception as e:
                logger.error(f"Error creating topic from cluster: {e}")
                db.session.rollback()
                continue
    
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


def auto_publish_high_confidence() -> int:
    """
    Auto-publish topics that meet very high confidence criteria.
    Conservative V1: requires wire service + another source.
    """
    from app.models import User
    from app.trending.publisher import publish_topic
    
    topics = TrendingTopic.query.filter_by(status='pending_review').all()
    
    published = 0
    for topic in topics:
        if topic.should_auto_publish:
            admin = User.query.filter_by(is_admin=True).first()
            if admin:
                publish_topic(topic, admin)
                published += 1
                logger.info(f"Auto-published topic {topic.id}: {topic.title[:50]}...")
    
    return published


def get_review_queue() -> List[TrendingTopic]:
    """Get all topics pending review."""
    return TrendingTopic.query.filter_by(
        status='pending_review'
    ).order_by(TrendingTopic.created_at.desc()).all()


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
