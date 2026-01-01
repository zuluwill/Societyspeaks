"""
Social Media Poster Service

Posts news discussions to social media platforms:
- Bluesky: Automatic posting via AT Protocol
- X/Twitter: Generate share links (API requires paid plan)
"""

import os
import logging
from typing import Optional, List
from urllib.parse import quote

from flask import url_for

logger = logging.getLogger(__name__)

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
    
    if platform == 'x':
        handles = " ".join(PODCAST_HANDLES_X[:5])
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:3])}\n\nFor fans of {handles}"
    else:
        handles = " ".join(PODCAST_HANDLES_BLUESKY[:3])
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:3])}"
    
    if platform == 'x' and len(post) > 280:
        post = f"{intro}: {title}\n\n{discussion_url}\n\n{' '.join(hashtags[:2])}"
    elif platform == 'bluesky' and len(post) > 300:
        post = f"{intro}: {title}\n\n{discussion_url}"
    
    return post


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
    base_url: str = None
) -> dict:
    """
    Share a discussion to all configured social platforms.
    
    Args:
        discussion: Discussion model instance
        base_url: Base URL of the site (e.g., https://societyspeaks.io)
    
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
