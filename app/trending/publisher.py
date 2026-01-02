"""
Topic Publisher

Publishes approved trending topics as discussions.
Handles the conversion from TrendingTopic to Discussion + seed Statements.
"""

import logging
from collections import Counter
from datetime import datetime
from typing import Optional

from app import db
from app.models import (
    TrendingTopic, Discussion, Statement, User,
    DiscussionSourceArticle, generate_slug
)

logger = logging.getLogger(__name__)


def _extract_country_from_articles(topic: TrendingTopic) -> Optional[str]:
    """
    Extract the most common country from source articles.
    Returns None if no country info available (falls back to global).
    """
    countries = []
    for ta in topic.articles:
        if ta.article and ta.article.source and ta.article.source.country:
            countries.append(ta.article.source.country)
    
    if not countries:
        return None
    
    country_counts = Counter(countries)
    most_common = country_counts.most_common(1)[0][0]
    return most_common


def publish_topic(topic: TrendingTopic, admin_user: User) -> Optional[Discussion]:
    """
    Convert a TrendingTopic into a live Discussion.
    Creates the discussion, links source articles, and adds seed statements.
    """
    if topic.discussion_id:
        logger.warning(f"Topic {topic.id} already published to discussion {topic.discussion_id}")
        return Discussion.query.get(topic.discussion_id)
    
    slug = generate_slug(topic.title)
    
    counter = 1
    base_slug = slug
    while Discussion.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    country = _extract_country_from_articles(topic)
    if country:
        geographic_scope = 'country'
    else:
        geographic_scope = 'global'
    
    discussion = Discussion(
        title=topic.title,
        description=topic.description or "",
        slug=slug,
        has_native_statements=True,
        creator_id=admin_user.id,
        topic=topic.primary_topic or 'Society',
        geographic_scope=geographic_scope,
        country=country,
        is_featured=False
    )
    
    db.session.add(discussion)
    db.session.flush()
    
    for ta in topic.articles:
        if ta.article:
            source_link = DiscussionSourceArticle(
                discussion_id=discussion.id,
                article_id=ta.article.id
            )
            db.session.add(source_link)
    
    if topic.seed_statements:
        for stmt_data in topic.seed_statements:
            statement = Statement(
                discussion_id=discussion.id,
                user_id=admin_user.id,
                content=stmt_data.get('content', '')[:500],
                statement_type='claim',
                is_seed=True,
                mod_status=1
            )
            db.session.add(statement)
    
    topic.discussion_id = discussion.id
    topic.status = 'published'
    topic.published_at = datetime.utcnow()
    topic.reviewed_by_id = admin_user.id
    topic.reviewed_at = datetime.utcnow()
    
    db.session.commit()
    
    logger.info(f"Published topic {topic.id} as discussion {discussion.id}")
    
    try:
        from app.trending.social_poster import share_discussion_to_social
        social_results = share_discussion_to_social(discussion)
        if social_results.get('bluesky'):
            logger.info(f"Shared to Bluesky: {social_results['bluesky']}")
    except Exception as e:
        logger.error(f"Failed to share to social media: {e}")
    
    return discussion


def merge_topic_into_discussion(
    topic: TrendingTopic,
    discussion: Discussion,
    admin_user: User,
    add_new_seeds: bool = True
) -> Discussion:
    """
    Merge a trending topic into an existing discussion.
    Adds new source articles and optionally new seed statements.
    """
    for ta in topic.articles:
        if ta.article:
            existing_link = DiscussionSourceArticle.query.filter_by(
                discussion_id=discussion.id,
                article_id=ta.article.id
            ).first()
            if not existing_link:
                source_link = DiscussionSourceArticle(
                    discussion_id=discussion.id,
                    article_id=ta.article.id
                )
                db.session.add(source_link)
    
    if add_new_seeds and topic.seed_statements:
        for stmt_data in topic.seed_statements[:2]:
            existing = Statement.query.filter_by(
                discussion_id=discussion.id,
                content=stmt_data.get('content', '')[:500]
            ).first()
            
            if not existing:
                statement = Statement(
                    discussion_id=discussion.id,
                    user_id=admin_user.id,
                    content=stmt_data.get('content', '')[:500],
                    statement_type='claim',
                    is_seed=True,
                    mod_status=1
                )
                db.session.add(statement)
    
    topic.merged_into_discussion_id = discussion.id
    topic.status = 'merged'
    topic.reviewed_by_id = admin_user.id
    topic.reviewed_at = datetime.utcnow()
    
    db.session.commit()
    
    logger.info(f"Merged topic {topic.id} into discussion {discussion.id}")
    
    return discussion
