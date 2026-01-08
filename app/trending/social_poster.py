"""
Social Media Poster Service

Posts news discussions to social media platforms:
- Bluesky: Automatic posting via AT Protocol (with staggered scheduling)
- X/Twitter: Generate share links (API requires paid plan)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from urllib.parse import quote

from flask import url_for

logger = logging.getLogger(__name__)

# Staggered posting times (in UTC hours) targeting US audience
# These are: 2pm, 4pm, 6pm, 8pm, 10pm UTC = 9am, 11am, 1pm, 3pm, 5pm EST
BLUESKY_POST_HOURS_UTC = [14, 16, 18, 20, 22]

BLUESKY_HANDLE = "societyspeaks.bsky.social"

PODCAST_HANDLES_X = [
    "@RestIsPolitics",
    "@TheNewsAgents",
    "@triggerpod",
    "@theallinpod",
    "@unhaboretort",
    "@StevenBartlett",
    "@chriswillx",
    "@tferriss",
    "@louistheroux",
]

PODCAST_HANDLES_BLUESKY = [
    "@restispolitics.bsky.social",
    "@triggernometry.bsky.social",
    "@unherd.bsky.social",
    "@stevenbartlett.bsky.social",
    "@timferriss.bsky.social",
]

def get_topic_hashtags(topic: str) -> List[str]:
    """Generate relevant hashtags based on discussion topic."""
    topic_tags = {
        'Politics': ['#Politics', '#Democracy', '#PublicPolicy'],
        'Geopolitics': ['#Geopolitics', '#ForeignPolicy', '#WorldNews'],
        'Economy': ['#Economy', '#Finance', '#Markets'],
        'Business': ['#Business', '#Entrepreneurship', '#Innovation'],
        'Technology': ['#Tech', '#AI', '#Innovation'],
        'Healthcare': ['#Healthcare', '#PublicHealth', '#NHS'],
        'Environment': ['#Climate', '#Environment', '#Sustainability'],
        'Education': ['#Education', '#Learning', '#Schools'],
        'Society': ['#Society', '#Culture', '#Community'],
        'Infrastructure': ['#Infrastructure', '#Transport', '#Cities'],
        'Culture': ['#Culture', '#Arts', '#Media'],
    }
    return topic_tags.get(topic, ['#PublicDebate'])


def generate_post_text(
    title: str,
    topic: str,
    discussion_url: str,
    platform: str = 'bluesky'
) -> str:
    """
    Generate social media post text for a discussion.
    
    Args:
        title: Discussion title
        topic: Discussion topic category
        discussion_url: Full URL to the discussion
        platform: 'bluesky' or 'x'
    """
    hashtags = get_topic_hashtags(topic)
    
    intro_phrases = [
        "New debate",
        "Join the discussion",
        "What do you think?",
        "Have your say",
    ]
    import random
    intro = random.choice(intro_phrases)
    
    max_length = 280 if platform == 'x' else 300
    
    if platform == 'x':
        handles = " ".join(PODCAST_HANDLES_X[:5])
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:3])}\n\nFor fans of {handles}"
    else:
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:3])}"
    
    if len(post) <= max_length:
        return post
    
    if platform == 'x':
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}"
    else:
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{hashtags[0]}"
    
    if len(post) <= max_length:
        return post
    
    post = f"{intro}: {title}\n\n{discussion_url}"
    
    if len(post) <= max_length:
        return post
    
    url_overhead = len(f"{intro}: ...\n\n{discussion_url}")
    max_title_length = max_length - url_overhead - 3
    if max_title_length > 20:
        truncated_title = title[:max_title_length].rsplit(' ', 1)[0] + "..."
        post = f"{intro}: {truncated_title}\n\n{discussion_url}"
    else:
        post = f"New: {discussion_url}"
    
    return post[:max_length]


def post_to_bluesky(
    title: str,
    topic: str,
    discussion_url: str
) -> Optional[str]:
    """
    Post a discussion announcement to Bluesky.
    
    Returns the post URI if successful, None otherwise.
    """
    app_password = os.environ.get('BLUESKY_APP_PASSWORD')
    
    if not app_password:
        logger.warning("BLUESKY_APP_PASSWORD not set, skipping Bluesky post")
        return None
    
    try:
        from atproto import Client, client_utils
        
        client = Client()
        client.login(BLUESKY_HANDLE, app_password)
        
        text = generate_post_text(title, topic, discussion_url, platform='bluesky')
        
        text_builder = client_utils.TextBuilder()
        
        parts = text.split(discussion_url)
        if len(parts) == 2:
            text_builder.text(parts[0])
            text_builder.link(discussion_url, discussion_url)
            text_builder.text(parts[1])
        else:
            text_builder.text(text)
        
        post = client.send_post(text_builder)
        
        logger.info(f"Posted to Bluesky: {post.uri}")
        return post.uri
        
    except Exception as e:
        logger.error(f"Failed to post to Bluesky: {e}")
        return None


def generate_x_share_url(
    title: str,
    topic: str,
    discussion_url: str
) -> str:
    """
    Generate an X/Twitter share URL with pre-filled text.
    
    Returns a URL that when clicked opens X composer with the post ready to send.
    """
    text = generate_post_text(title, topic, discussion_url, platform='x')
    
    encoded_text = quote(text, safe='')
    
    share_url = f"https://twitter.com/intent/tweet?text={encoded_text}"
    
    return share_url


def share_discussion_to_social(
    discussion,
    base_url: str = None,
    skip_bluesky: bool = False
) -> dict:
    """
    Share a discussion to all configured social platforms.
    
    Args:
        discussion: Discussion model instance
        base_url: Base URL of the site (e.g., https://societyspeaks.io)
        skip_bluesky: If True, skip immediate Bluesky posting (for scheduled posts)
    
    Returns:
        Dict with results for each platform
    """
    if not base_url:
        from flask import current_app
        base_url = current_app.config.get('SITE_URL', os.environ.get('SITE_URL', 'https://societyspeaks.io'))
    
    discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"
    
    results = {
        'bluesky': None,
        'x_share_url': None,
    }
    
    if not skip_bluesky:
        bluesky_uri = post_to_bluesky(
            title=discussion.title,
            topic=discussion.topic or 'Society',
            discussion_url=discussion_url
        )
        results['bluesky'] = bluesky_uri
    
    x_url = generate_x_share_url(
        title=discussion.title,
        topic=discussion.topic or 'Society',
        discussion_url=discussion_url
    )
    results['x_share_url'] = x_url
    
    return results


def schedule_bluesky_post(discussion, slot_index: int = 0) -> Optional[datetime]:
    """
    Schedule a discussion for staggered Bluesky posting.
    
    Args:
        discussion: Discussion model instance
        slot_index: Which time slot to use (0-4 for the 5 daily slots)
    
    Returns:
        The scheduled datetime, or None if scheduling failed
    """
    from app import db
    
    now = datetime.utcnow()
    
    # Get the hour for this slot
    slot_index = slot_index % len(BLUESKY_POST_HOURS_UTC)
    target_hour = BLUESKY_POST_HOURS_UTC[slot_index]
    
    # Calculate the scheduled time
    scheduled_time = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    
    # If the time has already passed today, schedule for tomorrow
    if scheduled_time <= now:
        scheduled_time += timedelta(days=1)
    
    discussion.bluesky_scheduled_at = scheduled_time
    db.session.commit()
    
    logger.info(f"Scheduled discussion {discussion.id} for Bluesky at {scheduled_time} UTC")
    return scheduled_time


def process_scheduled_bluesky_posts() -> int:
    """
    Process any discussions that are due to be posted to Bluesky.
    Called by the scheduler every 15 minutes.
    
    Returns:
        Number of posts sent
    """
    from app import db
    from app.models import Discussion
    
    now = datetime.utcnow()
    
    # Find discussions that are scheduled and due (scheduled time has passed, not yet posted)
    due_posts = Discussion.query.filter(
        Discussion.bluesky_scheduled_at.isnot(None),
        Discussion.bluesky_scheduled_at <= now,
        Discussion.bluesky_posted_at.is_(None)
    ).all()
    
    if not due_posts:
        logger.debug("No scheduled Bluesky posts due")
        return 0
    
    logger.info(f"Processing {len(due_posts)} scheduled Bluesky posts")
    
    base_url = os.environ.get('SITE_URL', 'https://societyspeaks.io')
    posted_count = 0
    
    for discussion in due_posts:
        try:
            discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"
            
            uri = post_to_bluesky(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url
            )
            
            if uri:
                discussion.bluesky_post_uri = uri
                discussion.bluesky_posted_at = datetime.utcnow()
                db.session.commit()
                posted_count += 1
                logger.info(f"Posted discussion {discussion.id} to Bluesky: {uri}")
            else:
                logger.warning(f"Failed to post discussion {discussion.id} to Bluesky (no URI returned)")
                
        except Exception as e:
            logger.error(f"Error posting discussion {discussion.id} to Bluesky: {e}")
            db.session.rollback()
            continue
    
    return posted_count
