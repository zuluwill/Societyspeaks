"""
Social Media Poster Service

Posts news discussions to social media platforms:
- Bluesky: Automatic posting via AT Protocol (with staggered scheduling)
- X/Twitter: Automatic posting via Twitter API v2 (with staggered scheduling)

Includes rate limit handling for both platforms.
"""

import os
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict
from urllib.parse import quote

from flask import url_for

logger = logging.getLogger(__name__)

# X/Twitter account handle
X_HANDLE = "societyspeaksio"

# =============================================================================
# RATE LIMIT CONFIGURATION
# =============================================================================

# X API Free Tier Limits (as of 2025):
# - 500 posts per month
# - ~17 posts per day (to stay safe)
# - Rate limit resets are per 15-minute window
X_DAILY_POST_LIMIT = 15  # Conservative daily limit (500/month ≈ 16.6/day)
X_MONTHLY_POST_LIMIT = 500  # Hard monthly limit from X API
X_RETRY_ATTEMPTS = 3
X_RETRY_BASE_DELAY = 60  # Base delay in seconds for exponential backoff
X_MAX_RETRY_WAIT = 900  # 15 minutes max retry wait (caps header-based waits)

# Bluesky rate limits (AT Protocol):
# - 1666 points per hour (posts cost 3 points each ≈ 555 posts/hour)
# - Much more generous than X
BLUESKY_RETRY_ATTEMPTS = 3
BLUESKY_RETRY_BASE_DELAY = 30

# Platform character limits
BLUESKY_CHAR_LIMIT = 300
X_CHAR_LIMIT = 280
X_URL_CHAR_COUNT = 23  # t.co shortening always uses 23 chars

# Bluesky handle
BLUESKY_HANDLE = "societyspeaks.bsky.social"


def _count_chars(text: str) -> int:
    """
    Count the number of characters in text.
    Counts all characters including newlines and spaces.
    """
    return len(text)


def _enforce_char_limit(text: str, max_chars: int, suffix: str = "...") -> str:
    """
    Enforce character limit by truncating text.
    
    Tries to keep text readable by truncating at word boundary.
    """
    if _count_chars(text) <= max_chars:
        return text
    
    # Calculate how much we need to trim
    target = max_chars - len(suffix)
    if target <= 0:
        return text[:max_chars]
    
    # Truncate at word boundary
    truncated = text[:target]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    
    return truncated.rstrip() + suffix


def _get_x_daily_post_count() -> Tuple[int, datetime]:
    """
    Get the number of X posts made today and when the count resets.
    Uses database to track posts across restarts.
    
    Returns:
        Tuple of (post_count_today, reset_time)
    """
    from app.models import Discussion
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    
    try:
        count = Discussion.query.filter(
            Discussion.x_posted_at.isnot(None),
            Discussion.x_posted_at >= today_start,
            Discussion.x_posted_at < tomorrow_start
        ).count()
        return count, tomorrow_start
    except Exception as e:
        logger.error(f"Error getting X daily post count: {e}")
        return 0, tomorrow_start


def _get_x_monthly_post_count() -> Tuple[int, datetime]:
    """
    Get the number of X posts made this month and when the count resets.
    Tracks against the 500/month X API limit.
    
    Returns:
        Tuple of (post_count_this_month, reset_time)
    """
    from app.models import Discussion
    
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Calculate next month start
    if now.month == 12:
        next_month_start = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=now.month + 1)
    
    try:
        count = Discussion.query.filter(
            Discussion.x_posted_at.isnot(None),
            Discussion.x_posted_at >= month_start,
            Discussion.x_posted_at < next_month_start
        ).count()
        return count, next_month_start
    except Exception as e:
        logger.error(f"Error getting X monthly post count: {e}")
        return 0, next_month_start


def _is_x_rate_limited() -> Tuple[bool, str]:
    """
    Check if we're approaching X rate limits (both daily and monthly).
    
    Returns:
        Tuple of (is_limited, reason_message)
    """
    # Check monthly limit first (hard limit from X API)
    monthly_count, monthly_reset = _get_x_monthly_post_count()
    if monthly_count >= X_MONTHLY_POST_LIMIT:
        days_until_reset = (monthly_reset - datetime.utcnow()).days
        return True, f"Monthly limit reached ({monthly_count}/{X_MONTHLY_POST_LIMIT}). Resets in {days_until_reset} days."
    
    # Warn if approaching monthly limit (90% threshold)
    if monthly_count >= X_MONTHLY_POST_LIMIT * 0.9:
        remaining = X_MONTHLY_POST_LIMIT - monthly_count
        logger.warning(f"Approaching X monthly limit: {monthly_count}/{X_MONTHLY_POST_LIMIT} ({remaining} remaining)")
    
    # Check daily limit
    daily_count, daily_reset = _get_x_daily_post_count()
    if daily_count >= X_DAILY_POST_LIMIT:
        hours_until_reset = (daily_reset - datetime.utcnow()).total_seconds() / 3600
        return True, f"Daily limit reached ({daily_count}/{X_DAILY_POST_LIMIT}). Resets in {hours_until_reset:.1f} hours."
    
    return False, ""


def _handle_x_rate_limit_error(error) -> Tuple[bool, int]:
    """
    Parse X API rate limit error and determine retry strategy.
    Logs detailed rate limit headers for debugging.
    
    Returns:
        Tuple of (should_retry, wait_seconds)
    """
    error_str = str(error).lower()
    
    # Check for rate limit indicators
    if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
        # Try to extract reset time and log headers for debugging
        if hasattr(error, 'response') and error.response is not None:
            headers = error.response.headers
            
            # Log all rate limit headers for debugging
            rate_limit = headers.get('x-rate-limit-limit')
            rate_remaining = headers.get('x-rate-limit-remaining')
            rate_reset = headers.get('x-rate-limit-reset')
            
            logger.warning(
                f"X rate limit headers: limit={rate_limit}, "
                f"remaining={rate_remaining}, reset={rate_reset}"
            )
            
            if rate_reset:
                try:
                    wait_seconds = int(rate_reset) - int(time.time())
                    if wait_seconds > 0:
                        # Cap at X_MAX_RETRY_WAIT, add 5s buffer
                        return True, min(wait_seconds + 5, X_MAX_RETRY_WAIT)
                except (ValueError, TypeError):
                    pass
        
        # Default: wait 15 minutes for rate limit reset
        return True, X_MAX_RETRY_WAIT
    
    # Check for daily limit exceeded
    if 'daily' in error_str and 'limit' in error_str:
        logger.warning("X daily API limit exceeded - no retry, wait until tomorrow")
        return False, 0  # Don't retry, wait until tomorrow
    
    return False, 0

# Staggered posting times (in UTC hours) targeting US audience
# These are: 2pm, 4pm, 6pm, 8pm, 10pm UTC = 9am, 11am, 1pm, 3pm, 5pm EST
BLUESKY_POST_HOURS_UTC = [14, 16, 18, 20, 22]

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


def get_social_posting_status() -> dict:
    """
    Get current status of social media posting capabilities.
    Useful for admin dashboard monitoring.
    
    Returns:
        Dict with status for each platform including rate limit info
    """
    status = {
        'bluesky': {
            'configured': bool(os.environ.get('BLUESKY_APP_PASSWORD')),
            'handle': BLUESKY_HANDLE,
        },
        'x': {
            'configured': all([
                os.environ.get('X_API_KEY'),
                os.environ.get('X_API_SECRET'),
                os.environ.get('X_ACCESS_TOKEN'),
                os.environ.get('X_ACCESS_TOKEN_SECRET'),
            ]),
            'handle': f'@{X_HANDLE}',
            'daily_limit': X_DAILY_POST_LIMIT,
            'monthly_limit': X_MONTHLY_POST_LIMIT,
        }
    }
    
    # Add X rate limit status if configured
    if status['x']['configured']:
        try:
            # Daily stats
            daily_count, daily_reset = _get_x_daily_post_count()
            status['x']['posts_today'] = daily_count
            status['x']['daily_remaining'] = max(0, X_DAILY_POST_LIMIT - daily_count)
            status['x']['daily_reset_time'] = daily_reset.isoformat()
            
            # Monthly stats
            monthly_count, monthly_reset = _get_x_monthly_post_count()
            status['x']['posts_this_month'] = monthly_count
            status['x']['monthly_remaining'] = max(0, X_MONTHLY_POST_LIMIT - monthly_count)
            status['x']['monthly_reset_time'] = monthly_reset.isoformat()
            status['x']['monthly_usage_percent'] = round((monthly_count / X_MONTHLY_POST_LIMIT) * 100, 1)
            
            # Overall rate limit status
            is_limited, reason = _is_x_rate_limited()
            status['x']['is_rate_limited'] = is_limited
            if is_limited:
                status['x']['rate_limit_reason'] = reason
            
            # Warning flags
            status['x']['approaching_monthly_limit'] = monthly_count >= X_MONTHLY_POST_LIMIT * 0.9
            
        except Exception as e:
            status['x']['error'] = str(e)
    
    return status


def get_topic_hashtags(topic: str, max_count: int = 2) -> List[str]:
    """
    Generate relevant hashtags based on discussion topic.
    
    Best practice (2025): 1-2 hashtags max for optimal engagement.
    """
    topic_tags = {
        'Politics': ['#Politics', '#Democracy'],
        'Geopolitics': ['#Geopolitics', '#WorldNews'],
        'Economy': ['#Economy', '#Finance'],
        'Business': ['#Business', '#Innovation'],
        'Technology': ['#Tech', '#AI'],
        'Healthcare': ['#Healthcare', '#PublicHealth'],
        'Environment': ['#Climate', '#Environment'],
        'Education': ['#Education', '#Schools'],
        'Society': ['#Society', '#Community'],
        'Infrastructure': ['#Infrastructure', '#Cities'],
        'Culture': ['#Culture', '#Media'],
    }
    tags = topic_tags.get(topic, ['#PublicDebate'])
    return tags[:max_count]


def generate_post_text(
    title: str,
    topic: str,
    discussion_url: str,
    platform: str = 'bluesky',
    discussion=None  # Optional: pass Discussion object to use insights
) -> str:
    """
    Generate social media post text for a discussion.
    
    If discussion object is provided, leverages existing consensus/vote data
    to create more engaging, mission-aligned posts.
    
    Args:
        title: Discussion title
        topic: Discussion topic category
        discussion_url: Full URL to the discussion
        platform: 'bluesky' or 'x'
        discussion: Optional Discussion object (enables data-driven posts)
    """
    # If discussion object provided, use insights module (DRY: reuse existing data)
    if discussion:
        try:
            from app.trending.social_insights import generate_data_driven_post
            return generate_data_driven_post(discussion, platform=platform, use_insights=True)
        except Exception as e:
            logger.warning(f"Failed to generate data-driven post, falling back to basic: {e}")
    
    # Fallback to basic format (backwards compatible)
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


def _fetch_link_card_metadata(url: str) -> Optional[Dict]:
    """
    Fetch OpenGraph metadata for link card preview.
    Returns dict with title, description, and optional image URL.
    """
    import requests
    from bs4 import BeautifulSoup
    
    try:
        headers = {'User-Agent': 'SocietySpeaksBot/1.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        metadata = {
            'uri': url,
            'title': '',
            'description': '',
            'image_url': None
        }
        
        # Get OpenGraph tags
        og_title = soup.find('meta', property='og:title')
        og_desc = soup.find('meta', property='og:description')
        og_image = soup.find('meta', property='og:image')
        
        # Fallback to standard tags
        title_tag = soup.find('title')
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        
        metadata['title'] = (og_title.get('content', '') if og_title else 
                            title_tag.text if title_tag else url)[:300]
        metadata['description'] = (og_desc.get('content', '') if og_desc else 
                                   desc_tag.get('content', '') if desc_tag else '')[:500]
        if og_image:
            metadata['image_url'] = og_image.get('content', '')
        
        return metadata
    except Exception as e:
        logger.warning(f"Failed to fetch link card metadata: {e}")
        return None


def _generate_bluesky_post_text(
    title: str,
    topic: str,
    discussion=None,
    custom_text: Optional[str] = None,
    max_chars: int = BLUESKY_CHAR_LIMIT
) -> Tuple[str, Optional[str]]:
    """
    Generate Bluesky post text within character limit.
    
    Best practices (2025):
    - 300 character limit
    - URL NOT included in text (will be in link card embed)
    - 1-2 hashtags max, placed mid-text or at end
    - Never start with hashtag
    
    Returns (text, hook_variant)
    """
    import re
    hook_variant = None
    
    if custom_text:
        # Remove any URL from custom text (will be in link card)
        text = re.sub(r'https?://\S+', '', custom_text).strip()
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
    elif discussion:
        try:
            from app.trending.social_insights import generate_data_driven_post
            post_text, hook_variant = generate_data_driven_post(
                discussion,
                platform='bluesky',
                return_variant=True
            )
            # Remove URL from generated text (will be in link card)
            text = re.sub(r'https?://\S+', '', post_text).strip()
            text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
        except Exception as e:
            logger.warning(f"Failed to generate data-driven post: {e}")
            text = f"New debate: {title}\n\nWhere do YOU stand? Join the discussion."
            hook_variant = 'fallback'
    else:
        # Simple format without URL - limit hashtags to 1
        hashtags = get_topic_hashtags(topic, max_count=1)
        hashtag_text = f" {hashtags[0]}" if hashtags else ""
        text = f"New debate: {title}\n\nWhere do YOU stand? Join the discussion.{hashtag_text}"
        hook_variant = 'simple'
    
    # Final character limit enforcement using shared helper
    text = _enforce_char_limit(text, max_chars)
    
    return text, hook_variant


def post_to_bluesky(
    title: str,
    topic: str,
    discussion_url: str,
    retry_count: int = 0,
    discussion=None,
    custom_text: Optional[str] = None
) -> Optional[str]:
    """
    Post to Bluesky with proper link card embed and facets.
    
    Best practices (2025):
    - 300 character limit for text
    - Use external embed for link cards (rich preview)
    - If embed fails, include URL in text with facet for clickability
    - Always ensure link is accessible to users
    
    Returns the post URI if successful, None otherwise.
    """
    app_password = os.environ.get('BLUESKY_APP_PASSWORD')
    
    if not app_password:
        logger.warning("BLUESKY_APP_PASSWORD not set, skipping Bluesky post")
        return None
    
    try:
        from atproto import Client, models, client_utils
        import requests
        
        client = Client()
        client.login(BLUESKY_HANDLE, app_password)
        
        # Generate post text (without URL initially - URL may go in embed)
        text, hook_variant = _generate_bluesky_post_text(
            title, topic, discussion, custom_text, max_chars=280  # Leave room for URL fallback
        )
        
        # Build external embed (link card)
        embed = None
        embed_success = False
        try:
            metadata = _fetch_link_card_metadata(discussion_url)
            if metadata:
                thumb_blob = None
                
                # Upload thumbnail if available
                if metadata.get('image_url'):
                    try:
                        img_response = requests.get(
                            metadata['image_url'],
                            headers={'User-Agent': 'SocietySpeaksBot/1.0'},
                            timeout=10
                        )
                        if img_response.status_code == 200:
                            img_data = img_response.content
                            upload_response = client.upload_blob(img_data)
                            thumb_blob = upload_response.blob
                    except Exception as e:
                        logger.debug(f"Failed to upload thumbnail: {e}")
                
                # Create external embed (link card)
                external = models.AppBskyEmbedExternal.External(
                    uri=discussion_url,
                    title=metadata.get('title', title)[:300],
                    description=metadata.get('description', '')[:500],
                    thumb=thumb_blob
                )
                embed = models.AppBskyEmbedExternal.Main(external=external)
                embed_success = True
        except Exception as e:
            logger.warning(f"Failed to create link card embed: {e}")
        
        # If embed failed, add URL to text with facet for clickability
        if not embed_success:
            url_length = _count_chars(discussion_url)
            
            # Absolute guard: if URL alone exceeds limit, we cannot post safely
            if url_length > BLUESKY_CHAR_LIMIT:
                logger.error(f"URL too long for Bluesky ({url_length} chars > {BLUESKY_CHAR_LIMIT}), cannot post")
                return None
            
            # Calculate space: URL + newlines
            url_space = url_length + 2  # \n\n before URL
            available_for_text = BLUESKY_CHAR_LIMIT - url_space
            
            # Handle edge case: URL leaves no room for meaningful text
            if available_for_text < 15:
                # Very long URL - post just the URL with minimal text
                text = "Join"
                logger.warning(f"URL very long ({url_length} chars), using minimal text")
            elif available_for_text < 50:
                # Long URL - use short text
                text = "Join the debate"
                logger.warning(f"URL long ({url_length} chars), using short text")
            else:
                # Normal case - enforce limit on text portion
                text = _enforce_char_limit(text, available_for_text)
            
            # Final assembly with guaranteed length check loop
            final_text = f"{text}\n\n{discussion_url}"
            while _count_chars(final_text) > BLUESKY_CHAR_LIMIT:
                if len(text) <= 4:
                    # Absolute minimum - just post the URL
                    text = ""
                    final_text = discussion_url
                    break
                # Keep trimming until we fit
                text = text[:-4].rstrip()
                if text and not text.endswith("..."):
                    text = text.rsplit(' ', 1)[0] + "..." if ' ' in text else text + "..."
                final_text = f"{text}\n\n{discussion_url}" if text else discussion_url
            
            # Build with facets for clickable link
            text_builder = client_utils.TextBuilder()
            if text:
                text_builder.text(text + "\n\n")
            text_builder.link(discussion_url, discussion_url)
            
            post = client.send_post(text_builder)
            logger.info(f"Posted to Bluesky with URL in text (embed failed): {post.uri}")
        else:
            # With embed, text can use full limit
            text = _enforce_char_limit(text, BLUESKY_CHAR_LIMIT)
            post = client.send_post(text=text, embed=embed)
        
        logger.info(f"Posted to Bluesky with link card: {post.uri}")

        # Record for engagement tracking
        try:
            from app.trending.engagement_tracker import record_post
            record_post(
                platform='bluesky',
                post_id=post.uri,
                content_type='discussion' if discussion else 'other',
                discussion_id=discussion.id if discussion else None,
                hook_variant=hook_variant,
            )
        except Exception as e:
            logger.warning(f"Engagement tracking error: {e}")

        # Track with PostHog
        try:
            import posthog
            if posthog:
                posthog.capture(
                    distinct_id='system',
                    event='social_post_created',
                    properties={
                        'platform': 'bluesky',
                        'post_uri': post.uri,
                        'has_discussion': discussion is not None,
                        'has_custom_text': custom_text is not None,
                        'topic': topic,
                        'hook_variant': hook_variant,
                    }
                )
        except Exception as e:
            logger.warning(f"PostHog tracking error: {e}")

        return post.uri
        
    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"Failed to post to Bluesky (attempt {retry_count + 1}): {e}")
        
        # Check for rate limit or transient errors that warrant retry
        is_rate_limit = 'rate' in error_str or '429' in error_str or 'too many' in error_str
        is_transient = 'timeout' in error_str or '500' in error_str or '502' in error_str or '503' in error_str
        
        if (is_rate_limit or is_transient) and retry_count < BLUESKY_RETRY_ATTEMPTS:
            wait_seconds = BLUESKY_RETRY_BASE_DELAY * (2 ** retry_count)
            logger.info(f"Bluesky transient error. Waiting {wait_seconds}s before retry {retry_count + 1}/{BLUESKY_RETRY_ATTEMPTS}")
            time.sleep(wait_seconds)
            return post_to_bluesky(title, topic, discussion_url, retry_count + 1, discussion, custom_text)
        
        # Check for authentication errors (don't retry these)
        if 'auth' in error_str or 'invalid' in error_str or 'password' in error_str:
            logger.error("Bluesky authentication error - check BLUESKY_APP_PASSWORD")
            return None
        
        return None


def _count_x_chars(text: str, url: str = None) -> int:
    """
    Count X/Twitter character length accounting for t.co URL shortening.
    All URLs are shortened to exactly 23 characters.
    """
    import re
    if url and url in text:
        # Replace URL with placeholder of t.co length
        text = text.replace(url, 'X' * X_URL_CHAR_COUNT)
    else:
        # Replace any URL with placeholder
        text = re.sub(r'https?://\S+', 'X' * X_URL_CHAR_COUNT, text)
    return _count_chars(text)


def _generate_x_post_text(
    title: str,
    topic: str,
    discussion_url: str,
    discussion=None,
    custom_text: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    """
    Generate X/Twitter post text within character limit.
    
    Best practices (2025):
    - 280 character limit total
    - URLs count as exactly 23 characters (t.co shortening)
    - 1-2 hashtags max, mid-text placement (never start with hashtag)
    - URL at end for rich preview card
    
    Returns (text, hook_variant)
    """
    import re
    
    hook_variant = None
    
    # Get 1-2 relevant hashtags (enforced limit)
    hashtags = get_topic_hashtags(topic, max_count=2)
    hashtag_text = ' '.join(hashtags) if hashtags else ''
    
    # Calculate available space for text (URL + separator)
    available_for_text = X_CHAR_LIMIT - X_URL_CHAR_COUNT - 2  # 2 for \n\n
    
    if custom_text:
        # Clean up custom text
        text = re.sub(r'https?://\S+', '', custom_text).strip()
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
        
        # Enforce length
        text = _enforce_char_limit(text, available_for_text)
        final_text = f"{text}\n\n{discussion_url}"
            
    elif discussion:
        try:
            from app.trending.social_insights import generate_data_driven_post
            post_text, hook_variant = generate_data_driven_post(
                discussion,
                platform='x',
                return_variant=True
            )
            # Clean and rebuild
            text = re.sub(r'https?://\S+', '', post_text).strip()
            text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
            
            # Ensure hashtags are present (mid-text, not at start)
            if hashtag_text and hashtag_text not in text:
                # Add hashtags before last paragraph
                if '\n\n' in text:
                    parts = text.rsplit('\n\n', 1)
                    text = f"{parts[0]} {hashtag_text}\n\n{parts[1]}"
                else:
                    text = f"{text} {hashtag_text}"
            
            # Enforce length
            text = _enforce_char_limit(text, available_for_text)
            final_text = f"{text}\n\n{discussion_url}"
            
        except Exception as e:
            logger.warning(f"Failed to generate data-driven post for X: {e}")
            hook_variant = 'fallback'
            cta = "Where do YOU stand?"
            # Calculate space: URL(23) + separator(2) + cta + hashtags + buffers
            cta_space = _count_chars(cta) + _count_chars(hashtag_text) + 4
            title_space = available_for_text - cta_space
            title_text = _enforce_char_limit(title, title_space)
            final_text = f"{title_text} {hashtag_text}\n\n{cta}\n\n{discussion_url}"
    else:
        # Simple format with hashtags
        hook_variant = 'simple'
        cta = "Where do YOU stand?"
        # Calculate space for title
        prefix = "New debate: "
        cta_space = _count_chars(cta) + _count_chars(hashtag_text) + _count_chars(prefix) + 4
        title_space = available_for_text - cta_space
        title_text = _enforce_char_limit(title, title_space)
        final_text = f"{prefix}{title_text} {hashtag_text}\n\n{cta}\n\n{discussion_url}"
    
    # Final safety check with X-specific counting
    final_length = _count_x_chars(final_text, discussion_url)
    if final_length > X_CHAR_LIMIT:
        logger.warning(f"X post too long ({final_length} chars), applying final truncation")
        # Extract text portion and truncate further
        text_part = final_text.rsplit('\n\n' + discussion_url, 1)[0] if discussion_url in final_text else final_text
        overage = final_length - X_CHAR_LIMIT + 3
        text_part = text_part[:-overage].rsplit(' ', 1)[0] + "..."
        final_text = f"{text_part}\n\n{discussion_url}"
    
    return final_text, hook_variant


def post_to_x(
    title: str,
    topic: str,
    discussion_url: str,
    retry_count: int = 0,
    discussion=None,
    custom_text: Optional[str] = None
) -> Optional[str]:
    """
    Post to X/Twitter with proper character limits and link card support.
    
    Best practices (2025):
    - 280 character limit
    - URLs count as 23 characters (t.co shortening)
    - 1-2 hashtags max, never start with hashtag
    - URL at end gets rich link card preview
    
    Returns the tweet ID if successful, None otherwise.
    """
    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_SECRET')
    access_token = os.environ.get('X_ACCESS_TOKEN')
    access_token_secret = os.environ.get('X_ACCESS_TOKEN_SECRET')
    
    if not all([api_key, api_secret, access_token, access_token_secret]):
        logger.warning("X API credentials not set, skipping X post")
        return None
    
    # Check proactive rate limit before attempting
    is_limited, limit_reason = _is_x_rate_limited()
    if is_limited:
        logger.warning(f"X rate limit check failed: {limit_reason}")
        return None
    
    try:
        import tweepy
        
        # Create OAuth 1.0a client for posting
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=False
        )

        # Generate properly formatted text with character limits
        text, hook_variant = _generate_x_post_text(
            title, topic, discussion_url, discussion, custom_text
            )

        # Post the tweet
        response = client.create_tweet(text=text)

        tweet_id = response.data['id']
        logger.info(f"Posted to X: https://x.com/{X_HANDLE}/status/{tweet_id}")

        # Record for engagement tracking
        try:
            from app.trending.engagement_tracker import record_post
            record_post(
                platform='x',
                post_id=tweet_id,
                content_type='discussion' if discussion else 'other',
                discussion_id=discussion.id if discussion else None,
                hook_variant=hook_variant,
            )
        except Exception as e:
            logger.warning(f"Engagement tracking error: {e}")

        # Track with PostHog
        if response and response.data:
            try:
                import posthog
                if posthog:
                    posthog.capture(
                        distinct_id='system',
                        event='social_post_created',
                        properties={
                            'platform': 'x',
                            'tweet_id': tweet_id,
                            'has_discussion': discussion is not None,
                            'has_custom_text': custom_text is not None,
                            'topic': topic,
                            'hook_variant': hook_variant,
                        }
                    )
            except Exception as e:
                logger.warning(f"PostHog tracking error: {e}")

        return tweet_id
    
    except Exception as e:
        error_str = str(e)
        logger.error(f"Failed to post to X (attempt {retry_count + 1}): {e}")
        
        # Check if this is a rate limit error we should retry
        should_retry, wait_seconds = _handle_x_rate_limit_error(e)

        if should_retry and retry_count < X_RETRY_ATTEMPTS:
            # Exponential backoff: base_delay * 2^retry_count
            actual_wait = min(wait_seconds, X_RETRY_BASE_DELAY * (2 ** retry_count))
            logger.info(f"X rate limited. Waiting {actual_wait}s before retry {retry_count + 1}/{X_RETRY_ATTEMPTS}")
            time.sleep(actual_wait)
            return post_to_x(title, topic, discussion_url, retry_count + 1, discussion, custom_text)
        
        # Check for duplicate tweet error (not a failure, just skip)
        if 'duplicate' in error_str.lower() or 'already posted' in error_str.lower():
            logger.warning("X rejected as duplicate tweet - already posted")
            return None
        
        # Check for authentication errors (don't retry these)
        if '401' in error_str or '403' in error_str or 'unauthorized' in error_str.lower():
            logger.error("X authentication error - check API credentials")
            return None
        
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
    base_url: Optional[str] = None,
    skip_bluesky: bool = False,
    skip_x: bool = False
) -> dict:
    """
    Share a discussion to all configured social platforms.
    
    Leverages existing discussion data (consensus, votes, statements) to create
    engaging posts that stay true to our mission.
    
    Args:
        discussion: Discussion model instance (enables data-driven posts)
        base_url: Base URL of the site (e.g., https://societyspeaks.io)
        skip_bluesky: If True, skip immediate Bluesky posting (for scheduled posts)
        skip_x: If True, skip immediate X posting (for scheduled posts)
    
    Returns:
        Dict with results for each platform
    """
    if not base_url:
        from flask import current_app
        base_url = current_app.config.get('SITE_URL', os.environ.get('SITE_URL', 'https://societyspeaks.io'))
    
    discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"
    
    results = {
        'bluesky': None,
        'x': None,
        'x_share_url': None,
    }
    
    # Each platform is isolated - failure in one doesn't affect others
    # Discussion object is passed to leverage insights (DRY: reuse existing data)
    if not skip_bluesky:
        try:
            # Pass discussion object to leverage insights (DRY: reuse existing data)
            bluesky_uri = post_to_bluesky(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url,
                discussion=discussion
            )
            results['bluesky'] = bluesky_uri
        except Exception as e:
            logger.error(f"Unexpected error posting to Bluesky: {e}")
    
    if not skip_x:
        try:
            # Pass discussion object to leverage insights (DRY: reuse existing data)
            x_tweet_id = post_to_x(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url,
                discussion=discussion
            )
            results['x'] = x_tweet_id
        except Exception as e:
            logger.error(f"Unexpected error posting to X: {e}")
    
    # Always generate share URL for manual sharing (low risk, but still protected)
    try:
        x_url = generate_x_share_url(
            title=discussion.title,
            topic=discussion.topic or 'Society',
            discussion_url=discussion_url
        )
        results['x_share_url'] = x_url
    except Exception as e:
        logger.error(f"Unexpected error generating X share URL: {e}")
    
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
    
    try:
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
    except Exception as e:
        logger.error(f"Failed to schedule Bluesky post for discussion {discussion.id}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def process_scheduled_bluesky_posts() -> int:
    """
    Process any discussions that are due to be posted to Bluesky.
    Called by the scheduler every 15 minutes.
    
    Uses mark-before-post pattern to prevent double-posting if multiple
    scheduler instances run concurrently.
    
    Returns:
        Number of posts sent
    """
    from app import db
    from app.models import Discussion
    
    try:
        now = datetime.utcnow()
        
        # Find discussions that are scheduled and due (scheduled time has passed, not yet posted)
        due_posts = Discussion.query.filter(
            Discussion.bluesky_scheduled_at.isnot(None),
            Discussion.bluesky_scheduled_at <= now,
            Discussion.bluesky_posted_at.is_(None)
        ).all()
    except Exception as e:
        logger.error(f"Error querying scheduled Bluesky posts: {e}")
        return 0
    
    if not due_posts:
        logger.debug("No scheduled Bluesky posts due")
        return 0
    
    logger.info(f"Processing {len(due_posts)} scheduled Bluesky posts")
    
    base_url = os.environ.get('SITE_URL', 'https://societyspeaks.io')
    posted_count = 0
    
    for discussion in due_posts:
        try:
            # CONCURRENT POST HANDLING: Mark as "in progress" before posting
            # This prevents double-posting if another scheduler instance picks up the same post
            discussion.bluesky_posted_at = datetime.utcnow()
            db.session.commit()
            
            discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"

            # Pass discussion object to leverage insights (DRY: reuse existing data)
            uri = post_to_bluesky(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url,
                discussion=discussion
            )
            
            if uri:
                # Update with actual post URI (bluesky_posted_at already set above)
                discussion.bluesky_post_uri = uri
                db.session.commit()
                posted_count += 1
                logger.info(f"Posted discussion {discussion.id} to Bluesky: {uri}")
            else:
                # Post failed - clear the bluesky_posted_at so it can be retried
                discussion.bluesky_posted_at = None
                db.session.commit()
                logger.warning(f"Failed to post discussion {discussion.id} to Bluesky (no URI returned) - will retry")
                
        except Exception as e:
            logger.error(f"Error posting discussion {discussion.id} to Bluesky: {e}")
            try:
                # Clear bluesky_posted_at on error so it can be retried
                discussion.bluesky_posted_at = None
                db.session.commit()
            except Exception:
                db.session.rollback()
            continue
    
    return posted_count


# Staggered posting times for X (same as Bluesky for consistency)
X_POST_HOURS_UTC = [14, 16, 18, 20, 22]


def schedule_x_post(discussion, slot_index: int = 0) -> Optional[datetime]:
    """
    Schedule a discussion for staggered X posting.
    
    Args:
        discussion: Discussion model instance
        slot_index: Which time slot to use (0-4 for the 5 daily slots)
    
    Returns:
        The scheduled datetime, or None if scheduling failed
    """
    from app import db
    
    try:
        now = datetime.utcnow()
        
        # Get the hour for this slot
        slot_index = slot_index % len(X_POST_HOURS_UTC)
        target_hour = X_POST_HOURS_UTC[slot_index]
        
        # Calculate the scheduled time
        scheduled_time = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        
        # If the time has already passed today, schedule for tomorrow
        if scheduled_time <= now:
            scheduled_time += timedelta(days=1)
        
        discussion.x_scheduled_at = scheduled_time
        db.session.commit()
        
        logger.info(f"Scheduled discussion {discussion.id} for X at {scheduled_time} UTC")
        return scheduled_time
    except Exception as e:
        logger.error(f"Failed to schedule X post for discussion {discussion.id}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def process_scheduled_x_posts() -> int:
    """
    Process any discussions that are due to be posted to X.
    Called by the scheduler every 15 minutes.
    
    Uses mark-before-post pattern to prevent double-posting if multiple
    scheduler instances run concurrently.
    
    Returns:
        Number of posts sent
    """
    from app import db
    from app.models import Discussion
    
    # Check rate limit once at the start (optimization)
    is_limited, limit_reason = _is_x_rate_limited()
    if is_limited:
        logger.warning(f"X rate limit reached, skipping all scheduled posts: {limit_reason}")
        return 0
    
    try:
        now = datetime.utcnow()
        
        # Find discussions that are scheduled and due (scheduled time has passed, not yet posted)
        due_posts = Discussion.query.filter(
            Discussion.x_scheduled_at.isnot(None),
            Discussion.x_scheduled_at <= now,
            Discussion.x_posted_at.is_(None)
        ).all()
    except Exception as e:
        logger.error(f"Error querying scheduled X posts: {e}")
        return 0
    
    if not due_posts:
        logger.debug("No scheduled X posts due")
        return 0
    
    logger.info(f"Processing {len(due_posts)} scheduled X posts")
    
    base_url = os.environ.get('SITE_URL', 'https://societyspeaks.io')
    posted_count = 0
    
    for discussion in due_posts:
        try:
            # CONCURRENT POST HANDLING: Mark as "in progress" before posting
            # This prevents double-posting if another scheduler instance picks up the same post
            discussion.x_posted_at = datetime.utcnow()
            db.session.commit()
            
            discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"

            # Pass discussion object to leverage insights (DRY: reuse existing data)
            tweet_id = post_to_x(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url,
                discussion=discussion
            )
            
            if tweet_id:
                # Update with actual tweet ID (x_posted_at already set above)
                discussion.x_post_id = tweet_id
                db.session.commit()
                posted_count += 1
                logger.info(f"Posted discussion {discussion.id} to X: {tweet_id}")
            else:
                # Post failed - clear the x_posted_at so it can be retried
                discussion.x_posted_at = None
                db.session.commit()
                logger.warning(f"Failed to post discussion {discussion.id} to X (no ID returned) - will retry")
                
        except Exception as e:
            logger.error(f"Error posting discussion {discussion.id} to X: {e}")
            try:
                # Clear x_posted_at on error so it can be retried
                discussion.x_posted_at = None
                db.session.commit()
            except Exception:
                db.session.rollback()
            continue
    
    return posted_count
