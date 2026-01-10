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
from typing import Optional, List, Tuple
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
    discussion_url: str,
    retry_count: int = 0
) -> Optional[str]:
    """
    Post a discussion announcement to Bluesky with retry logic.
    
    Returns the post URI if successful, None otherwise.
    
    Features:
    - Exponential backoff retry on transient errors
    - Graceful handling of rate limits and API errors
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
        error_str = str(e).lower()
        logger.error(f"Failed to post to Bluesky (attempt {retry_count + 1}): {e}")
        
        # Check for rate limit or transient errors that warrant retry
        is_rate_limit = 'rate' in error_str or '429' in error_str or 'too many' in error_str
        is_transient = 'timeout' in error_str or '500' in error_str or '502' in error_str or '503' in error_str
        
        if (is_rate_limit or is_transient) and retry_count < BLUESKY_RETRY_ATTEMPTS:
            wait_seconds = BLUESKY_RETRY_BASE_DELAY * (2 ** retry_count)
            logger.info(f"Bluesky transient error. Waiting {wait_seconds}s before retry {retry_count + 1}/{BLUESKY_RETRY_ATTEMPTS}")
            time.sleep(wait_seconds)
            return post_to_bluesky(title, topic, discussion_url, retry_count + 1)
        
        # Check for authentication errors (don't retry these)
        if 'auth' in error_str or 'invalid' in error_str or 'password' in error_str:
            logger.error("Bluesky authentication error - check BLUESKY_APP_PASSWORD")
            return None
        
        return None


def post_to_x(
    title: str,
    topic: str,
    discussion_url: str,
    retry_count: int = 0
) -> Optional[str]:
    """
    Post a discussion announcement to X/Twitter with rate limit handling.
    
    Returns the tweet ID if successful, None otherwise.
    
    Features:
    - Proactive rate limit checking (daily post count)
    - Exponential backoff retry on transient rate limits
    - Graceful handling of API errors
    
    Requires environment variables:
    - X_API_KEY: Consumer API key
    - X_API_SECRET: Consumer API secret
    - X_ACCESS_TOKEN: Access token for @societyspeaksio
    - X_ACCESS_TOKEN_SECRET: Access token secret
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
            wait_on_rate_limit=False  # We handle rate limits ourselves
        )
        
        text = generate_post_text(title, topic, discussion_url, platform='x')
        
        # Post the tweet
        response = client.create_tweet(text=text)
        
        tweet_id = response.data['id']
        logger.info(f"Posted to X: https://x.com/{X_HANDLE}/status/{tweet_id}")
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
            return post_to_x(title, topic, discussion_url, retry_count + 1)
        
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
    base_url: str = None,
    skip_bluesky: bool = False,
    skip_x: bool = False
) -> dict:
    """
    Share a discussion to all configured social platforms.
    
    Args:
        discussion: Discussion model instance
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
    if not skip_bluesky:
        try:
            bluesky_uri = post_to_bluesky(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url
            )
            results['bluesky'] = bluesky_uri
        except Exception as e:
            logger.error(f"Unexpected error posting to Bluesky: {e}")
    
    if not skip_x:
        try:
            x_tweet_id = post_to_x(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url
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
            
            uri = post_to_bluesky(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url
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
            
            tweet_id = post_to_x(
                title=discussion.title,
                topic=discussion.topic or 'Society',
                discussion_url=discussion_url
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
