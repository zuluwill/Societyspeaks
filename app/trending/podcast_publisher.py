"""
Single-Source Publisher

Converts single-source content (podcasts, newsletters) into discussions.
These sources don't cluster naturally with news, so they get their own discussions.
Reuses patterns from publisher.py and seed_generator.py (DRY principles).
"""

import logging
import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from app import db
from app.models import (
    NewsArticle, NewsSource, Discussion, Statement, User,
    DiscussionSourceArticle, generate_slug
)

logger = logging.getLogger(__name__)


from app.trending.constants import VALID_TOPICS


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and decode HTML entities from text."""
    if not text:
        return ""
    import html
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p\s*/?>', ' ', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def detect_article_category(article: NewsArticle) -> str:
    """
    Detect the appropriate topic category for an article using AI.
    Falls back to 'Society' if detection fails.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            return _detect_category_anthropic(article, api_key)
        return 'Society'
    
    return _detect_category_openai(article, api_key)


def _detect_category_openai(article: NewsArticle, api_key: str) -> str:
    """Detect category using OpenAI."""
    try:
        import openai
    except ImportError:
        return 'Society'
    
    client = openai.OpenAI(api_key=api_key)
    
    title = article.title or ""
    summary = strip_html_tags(article.summary or "")[:500]
    
    prompt = f"""Classify this article into exactly ONE category.

Title: {title}
Summary: {summary}

Categories: {', '.join(VALID_TOPICS)}

Reply with just the category name, nothing else."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0
        )
        category = response.choices[0].message.content.strip()
        if category in VALID_TOPICS:
            return category
        for valid in VALID_TOPICS:
            if valid.lower() in category.lower():
                return valid
        return 'Society'
    except Exception as e:
        logger.warning(f"Category detection failed: {e}")
        return 'Society'


def _detect_category_anthropic(article: NewsArticle, api_key: str) -> str:
    """Detect category using Anthropic."""
    try:
        import anthropic
    except ImportError:
        return 'Society'
    
    client = anthropic.Anthropic(api_key=api_key)
    
    title = article.title or ""
    summary = strip_html_tags(article.summary or "")[:500]
    
    prompt = f"""Classify this article into exactly ONE category.

Title: {title}
Summary: {summary}

Categories: {', '.join(VALID_TOPICS)}

Reply with just the category name, nothing else."""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}]
        )
        category = response.content[0].text.strip()
        if category in VALID_TOPICS:
            return category
        for valid in VALID_TOPICS:
            if valid.lower() in category.lower():
                return valid
        return 'Society'
    except Exception as e:
        logger.warning(f"Category detection failed: {e}")
        return 'Society'


def detect_article_geographic(article: NewsArticle) -> Dict:
    """
    Detect geographic scope and country for an article using AI.
    Returns dict with 'scope' (global/national/local) and 'country'.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    provider = 'openai'
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        provider = 'anthropic'
    if not api_key:
        source_country = article.source.country if article.source else None
        return {'scope': 'global', 'country': source_country}
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        title = article.title or ""
        summary = strip_html_tags(article.summary or "")[:300]
        source_country = article.source.country if article.source else "Unknown"
        
        prompt = f"""Analyze this article's geographic focus.

Title: {title}
Summary: {summary}
Source country: {source_country}

Reply in JSON format:
{{"scope": "global|national|local", "country": "country name or null if truly global", "reason": "brief reason"}}

- Use "national" if the article is primarily about one country's internal affairs
- Use "local" if about a specific city/region
- Use "global" only if the topic genuinely affects multiple countries equally"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0
        )
        
        content = response.choices[0].message.content.strip()
        import json as json_module
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        
        data = json_module.loads(content)
        scope = data.get('scope', 'global')
        country = data.get('country')
        
        if scope not in ('global', 'national', 'local'):
            scope = 'global'
        
        return {'scope': scope, 'country': country}
        
    except Exception as e:
        logger.warning(f"Geographic detection failed: {e}")
        source_country = article.source.country if article.source else None
        return {'scope': 'global', 'country': source_country}


def generate_article_description(article: NewsArticle) -> str:
    """
    Generate a brief contextual description for an article discussion.
    Provides context that helps users understand what the discussion is about.
    """
    summary = strip_html_tags(article.summary or "")
    if summary and len(summary) > 50:
        if len(summary) > 500:
            return summary[:497] + "..."
        return summary
    
    api_key = os.environ.get('OPENAI_API_KEY')
    provider = 'openai'
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        provider = 'anthropic'
    if not api_key:
        return summary or ""
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        title = article.title or ""
        source_name = article.source.name if article.source else "Unknown"
        
        prompt = f"""Write a 1-2 sentence description for this article that provides context for public discussion.

Source: {source_name}
Title: {title}

The description should help readers understand what the article is about and why it matters for public debate.
Keep it under 200 characters. Do not use quotes or attribution."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.3
        )
        
        desc = response.choices[0].message.content.strip()
        if len(desc) > 500:
            desc = desc[:497] + "..."
        return desc
        
    except Exception as e:
        logger.warning(f"Description generation failed: {e}")
        return summary or ""


def generate_single_source_seed_statements(article: NewsArticle, count: int = 5) -> List[Dict]:
    """
    Generate seed statements for a single-source article discussion.
    
    Works for podcasts, newsletters, and other single-source content.
    Uses the same LLM approach as trending topics.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            return _generate_with_anthropic(article, count, api_key)
        logger.warning("No LLM API key available for seed generation")
        return []
    
    return _generate_with_openai(article, count, api_key)


def _generate_with_openai(article: NewsArticle, count: int, api_key: str) -> List[Dict]:
    """Generate seeds using OpenAI."""
    try:
        import openai
    except ImportError:
        logger.error("OpenAI library not installed")
        return []
    
    try:
        client = openai.OpenAI(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create OpenAI client: {e}")
        return []
    
    source_name = article.source.name if article.source else "Unknown Source"
    source_type = article.source.source_category if article.source else "article"
    summary = strip_html_tags(article.summary or "")[:500]
    
    prompt = f"""Generate {count} diverse seed statements for a public deliberation based on this {source_type}:

Source: {source_name}
Title: {article.title}
{f"Summary: {summary}" if summary else ""}

Requirements:
- Generate statements representing DIFFERENT viewpoints (pro, con, neutral)
- Each statement should be a clear, debatable claim (not a question)
- Statements should encourage thoughtful discussion
- Keep each statement under 200 characters
- Focus on the key topics/themes discussed in this episode

Return JSON array: [{{"content": "statement text", "position": "pro/con/neutral"}}]
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            content = json_match.group()
        
        statements = json.loads(content)
        
        valid_statements = []
        for stmt in statements:
            if isinstance(stmt, dict) and 'content' in stmt:
                text = stmt['content'].strip()
                if 20 <= len(text) <= 500:
                    valid_statements.append({
                        'content': text,
                        'position': stmt.get('position', 'neutral')
                    })
        
        return valid_statements[:count]
        
    except Exception as e:
        logger.error(f"OpenAI seed generation failed: {e}")
        return []


def _generate_with_anthropic(article: NewsArticle, count: int, api_key: str) -> List[Dict]:
    """Generate seeds using Anthropic."""
    try:
        import anthropic
    except ImportError:
        logger.error("Anthropic library not installed")
        return []
    
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    except Exception as e:
        logger.error(f"Failed to create Anthropic client: {e}")
        return []
    
    source_name = article.source.name if article.source else "Unknown Source"
    source_type = article.source.source_category if article.source else "article"
    summary = strip_html_tags(article.summary or "")[:500]
    
    prompt = f"""Generate {count} diverse seed statements for a public deliberation based on this {source_type}:

Source: {source_name}
Title: {article.title}
{f"Summary: {summary}" if summary else ""}

Requirements:
- Generate statements representing DIFFERENT viewpoints (pro, con, neutral)
- Each statement should be a clear, debatable claim (not a question)
- Statements should encourage thoughtful discussion
- Keep each statement under 200 characters
- Focus on the key topics/themes discussed in this episode

Return ONLY a JSON array: [{{"content": "statement text", "position": "pro/con/neutral"}}]
"""
    
    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        content = response.content[0].text.strip()
        
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            content = json_match.group()
        
        statements = json.loads(content)
        
        valid_statements = []
        for stmt in statements:
            if isinstance(stmt, dict) and 'content' in stmt:
                text = stmt['content'].strip()
                if 20 <= len(text) <= 500:
                    valid_statements.append({
                        'content': text,
                        'position': stmt.get('position', 'neutral')
                    })
        
        return valid_statements[:count]
        
    except Exception as e:
        logger.error(f"Anthropic seed generation failed: {e}")
        return []


def publish_single_source_article(
    article: NewsArticle,
    admin_user: User,
    seed_statements: Optional[List[Dict]] = None,
    require_seeds: bool = True
) -> Optional[Discussion]:
    """
    Convert a single-source article (podcast/newsletter) into a Discussion.
    
    Creates the discussion, links the source article, and adds seed statements.
    Reuses patterns from publisher.publish_topic() (DRY).
    
    Args:
        article: The NewsArticle to publish
        admin_user: Admin user performing the publish
        seed_statements: Optional pre-generated seed statements
        require_seeds: If True, abort if no seeds can be generated (default: True)
    """
    existing = Discussion.query.join(DiscussionSourceArticle).filter(
        DiscussionSourceArticle.article_id == article.id
    ).first()
    
    if existing:
        logger.info(f"Article {article.id} already has discussion {existing.id}")
        return existing
    
    statements_to_add = seed_statements
    if not statements_to_add:
        statements_to_add = generate_single_source_seed_statements(article)
    
    if require_seeds and not statements_to_add:
        logger.warning(f"Skipping article {article.id} - no seed statements generated")
        return None
    
    slug = generate_slug(article.title)
    
    counter = 1
    base_slug = slug
    while Discussion.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    source_name = article.source.name if article.source else "Unknown"
    source_type = article.source.source_category if article.source else "article"
    
    topic_category = detect_article_category(article)
    logger.info(f"Detected category '{topic_category}' for article: {article.title[:50]}...")
    
    geo_info = detect_article_geographic(article)
    geographic_scope = geo_info.get('scope', 'global')
    country = geo_info.get('country') or (article.source.country if article.source else None)
    logger.info(f"Detected geography: {geographic_scope}, country: {country}")
    
    description = generate_article_description(article)
    
    discussion = Discussion(
        title=strip_html_tags(article.title),
        description=description,
        slug=slug,
        has_native_statements=True,
        creator_id=admin_user.id,
        topic=topic_category,
        geographic_scope=geographic_scope,
        country=country,
        is_featured=False
    )
    
    db.session.add(discussion)
    db.session.flush()
    
    source_link = DiscussionSourceArticle(
        discussion_id=discussion.id,
        article_id=article.id
    )
    db.session.add(source_link)
    
    for stmt_data in statements_to_add:
        statement = Statement(
            discussion_id=discussion.id,
            user_id=admin_user.id,
            content=stmt_data.get('content', '')[:500],
            statement_type='claim',
            is_seed=True,
            mod_status=1
        )
        db.session.add(statement)
    
    db.session.commit()
    
    logger.info(f"Published {source_type} article {article.id} as discussion {discussion.id}")
    
    return discussion


# Backward-compatible alias
def publish_podcast_episode(episode: NewsArticle, admin_user: User, seed_statements: Optional[List[Dict]] = None) -> Optional[Discussion]:
    """Deprecated: Use publish_single_source_article instead."""
    return publish_single_source_article(episode, admin_user, seed_statements)


def process_recent_podcast_episodes(
    days: int = 7,
    max_per_source: int = 3,
    admin_user: Optional[User] = None
) -> Dict:
    """
    Process recent podcast episodes and create discussions for them.
    
    Only processes episodes that:
    - Are from active podcast sources
    - Were published within the last N days
    - Don't already have a linked discussion
    - Have a meaningful title (> 20 chars)
    
    Args:
        days: Look back period for episodes
        max_per_source: Maximum episodes to process per source (prevents flooding)
        admin_user: Admin user to attribute discussions to
        
    Returns:
        Dict with processing stats
    """
    if not admin_user:
        admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            logger.error("No admin user found for podcast publishing")
            return {'error': 'No admin user found'}
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    podcast_sources = NewsSource.query.filter_by(
        is_active=True,
        source_category='podcast'
    ).all()
    
    stats = {
        'sources_processed': 0,
        'episodes_found': 0,
        'discussions_created': 0,
        'already_published': 0,
        'skipped': 0,
        'errors': 0
    }
    
    for source in podcast_sources:
        stats['sources_processed'] += 1
        
        episodes = NewsArticle.query.filter(
            NewsArticle.source_id == source.id,
            NewsArticle.fetched_at >= cutoff_date
        ).order_by(NewsArticle.published_at.desc()).limit(max_per_source * 2).all()
        
        published_count = 0
        
        for episode in episodes:
            if published_count >= max_per_source:
                break
                
            stats['episodes_found'] += 1
            
            if len(episode.title or '') < 20:
                stats['skipped'] += 1
                continue
            
            existing = Discussion.query.join(DiscussionSourceArticle).filter(
                DiscussionSourceArticle.article_id == episode.id
            ).first()
            
            if existing:
                stats['already_published'] += 1
                continue
            
            try:
                discussion = publish_single_source_article(episode, admin_user)
                if discussion:
                    stats['discussions_created'] += 1
                    published_count += 1
                else:
                    stats['skipped'] += 1
            except Exception as e:
                logger.error(f"Error publishing episode {episode.id}: {e}")
                stats['errors'] += 1
                db.session.rollback()
    
    logger.info(f"Podcast processing complete: {stats}")
    return stats


def process_single_source_articles(
    source_categories: List[str],
    days: int = 14,
    max_per_source: int = 3,
    admin_user: Optional[User] = None
) -> Dict:
    """
    Process articles from single-source content (podcasts, newsletters, etc.) 
    and create discussions for them.
    
    Generalized version that handles multiple source categories (DRY).
    
    Args:
        source_categories: List of source categories to process (e.g., ['podcast', 'newsletter'])
        days: Look back period for articles
        max_per_source: Maximum articles to process per source (prevents flooding)
        admin_user: Admin user to attribute discussions to
        
    Returns:
        Dict with processing stats
    """
    if not admin_user:
        admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            logger.error("No admin user found for single-source publishing")
            return {'error': 'No admin user found'}
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    sources = NewsSource.query.filter(
        NewsSource.is_active == True,
        NewsSource.source_category.in_(source_categories)
    ).all()
    
    stats = {
        'source_categories': source_categories,
        'sources_processed': 0,
        'articles_found': 0,
        'discussions_created': 0,
        'already_published': 0,
        'skipped': 0,
        'errors': 0
    }
    
    for source in sources:
        stats['sources_processed'] += 1
        
        articles = NewsArticle.query.filter(
            NewsArticle.source_id == source.id,
            NewsArticle.fetched_at >= cutoff_date
        ).order_by(NewsArticle.published_at.desc()).limit(max_per_source * 2).all()
        
        published_count = 0
        
        for article in articles:
            if published_count >= max_per_source:
                break
                
            stats['articles_found'] += 1
            
            if len(article.title or '') < 20:
                stats['skipped'] += 1
                continue
            
            existing = Discussion.query.join(DiscussionSourceArticle).filter(
                DiscussionSourceArticle.article_id == article.id
            ).first()
            
            if existing:
                stats['already_published'] += 1
                continue
            
            try:
                discussion = publish_single_source_article(article, admin_user)
                if discussion:
                    stats['discussions_created'] += 1
                    published_count += 1
                else:
                    stats['skipped'] += 1
            except Exception as e:
                logger.error(f"Error publishing article {article.id}: {e}")
                stats['errors'] += 1
                db.session.rollback()
    
    logger.info(f"Single-source processing complete: {stats}")
    return stats


def run_podcast_to_discussion_pipeline():
    """
    Main entry point for the podcast-to-discussion pipeline.
    Called by scheduler or manually.
    """
    logger.info("Starting podcast-to-discussion pipeline")
    
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            stats = process_recent_podcast_episodes(
                days=14,
                max_per_source=5
            )
            return stats
    except Exception as e:
        logger.error(f"Podcast pipeline error: {e}")
        return {'error': str(e)}
