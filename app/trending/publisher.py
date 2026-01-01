"""
Topic Publisher

Publishes approved trending topics as discussions.
Handles the conversion from TrendingTopic to Discussion + seed Statements.
"""

import logging
from datetime import datetime
from typing import Optional

from app import db
from app.models import (
    TrendingTopic, Discussion, Statement, User,
    generate_slug
)

logger = logging.getLogger(__name__)


def publish_topic(topic: TrendingTopic, admin_user: User) -> Optional[Discussion]:
    """
    Convert a TrendingTopic into a live Discussion.
    Creates the discussion and seed statements.
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
    
    article_urls = []
    for ta in topic.articles:
        if ta.article:
            article_urls.append(f"- [{ta.article.source.name}]({ta.article.url})")
    
    description = topic.description or ""
    if article_urls:
        description += "\n\n**Source Articles:**\n" + "\n".join(article_urls[:5])
    
    discussion = Discussion(
        title=topic.title,
        description=description,
        slug=slug,
        has_native_statements=True,
        creator_id=admin_user.id,
        topic=topic.primary_topic or 'Society',
        geographic_scope='global',
        is_featured=False
    )
    
    db.session.add(discussion)
    db.session.flush()
    
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
    article_urls = []
    for ta in topic.articles:
        if ta.article:
            article_urls.append(f"- [{ta.article.source.name}]({ta.article.url})")
    
    if article_urls:
        update_text = "\n\n**Update - Additional Sources:**\n" + "\n".join(article_urls[:3])
        if discussion.description:
            discussion.description += update_text
        else:
            discussion.description = update_text
    
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
