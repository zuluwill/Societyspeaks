"""
Topic Publisher

Publishes approved trending topics as discussions.
Handles the conversion from TrendingTopic to Discussion + seed Statements.
"""

import logging
import re
from collections import Counter
from datetime import datetime
from typing import Optional

from app import db
from app.models import (
    TrendingTopic, Discussion, Statement, User,
    DiscussionSourceArticle, generate_slug
)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, preserving the text content."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p\s*/?>', ' ', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

logger = logging.getLogger(__name__)


def _extract_geographic_info(topic: TrendingTopic) -> tuple:
    """
    Extract geographic scope and countries from source articles.
    Uses AI-detected geographic info from articles if available,
    otherwise falls back to source country.
    
    Returns (geographic_scope, country_string)
    """
    scopes = []
    countries_list = []
    
    for ta in topic.articles:
        if ta.article:
            if ta.article.geographic_scope and ta.article.geographic_scope != 'unknown':
                scopes.append(ta.article.geographic_scope)
            if ta.article.geographic_countries:
                countries_list.append(ta.article.geographic_countries)
            elif ta.article.source and ta.article.source.country:
                countries_list.append(ta.article.source.country)
    
    if scopes:
        scope_counts = Counter(scopes)
        most_common_scope = scope_counts.most_common(1)[0][0]
        if most_common_scope in ('national', 'local', 'regional'):
            geographic_scope = 'country'
        else:
            geographic_scope = 'global'
    else:
        geographic_scope = 'global'
    
    if countries_list:
        all_countries = []
        for c in countries_list:
            all_countries.extend([x.strip() for x in c.split(',')])
        
        if 'Global' in all_countries:
            country = None
        else:
            country_counts = Counter(all_countries)
            country = country_counts.most_common(1)[0][0]
    else:
        country = None
    
    return geographic_scope, country


def publish_topic(
    topic: TrendingTopic, 
    admin_user: User,
    schedule_bluesky: bool = False,
    bluesky_slot_index: int = 0
) -> Optional[Discussion]:
    """
    Convert a TrendingTopic into a live Discussion.
    Creates the discussion, links source articles, and adds seed statements.
    
    Args:
        topic: The TrendingTopic to publish
        admin_user: Admin user performing the publish
        schedule_bluesky: If True, schedule Bluesky post for later instead of posting immediately
        bluesky_slot_index: Which time slot to use for scheduled posting (0-4)
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
    
    geographic_scope, country = _extract_geographic_info(topic)
    
    clean_description = strip_html_tags(topic.description) if topic.description else ""
    
    discussion = Discussion(
        title=topic.title,
        description=clean_description,
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
        from app.trending.social_poster import share_discussion_to_social, schedule_bluesky_post
        
        if schedule_bluesky:
            # Schedule Bluesky post for later (staggered posting)
            scheduled_time = schedule_bluesky_post(discussion, slot_index=bluesky_slot_index)
            if scheduled_time:
                logger.info(f"Scheduled Bluesky post for {scheduled_time} UTC")
            # Still generate X share URL
            social_results = share_discussion_to_social(discussion, skip_bluesky=True)
        else:
            # Post immediately (for manual publishes)
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
