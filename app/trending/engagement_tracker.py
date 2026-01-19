"""
Social Media Engagement Tracker

Fetches and tracks engagement metrics (likes, reposts, replies) for social posts
on X and Bluesky. Used for measuring post performance and A/B testing.

Note: Requires database migration for SocialPostEngagement model.
If table doesn't exist, functions gracefully return None/empty results.
"""

import os
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from app.db_retry import with_db_retry, cleanup_db_session

logger = logging.getLogger(__name__)

# Flag to track if table exists (checked once per process)
_table_exists: Optional[bool] = None

# Rate limit tracking - stop fetching when we hit X rate limits
_x_rate_limited_until: Optional[datetime] = None


def reset_x_rate_limit_if_expired() -> None:
    """
    Reset the X rate limit cooldown if the window has passed.
    Call this at the start of each scheduler run.
    """
    global _x_rate_limited_until
    if _x_rate_limited_until and datetime.utcnow() >= _x_rate_limited_until:
        logger.info("X rate limit cooldown expired, resetting")
        _x_rate_limited_until = None


def _check_table_exists() -> bool:
    """Check if SocialPostEngagement table exists. Caches result."""
    global _table_exists
    if _table_exists is not None:
        return _table_exists

    try:
        from app import db
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        _table_exists = 'social_post_engagement' in inspector.get_table_names()
        if not _table_exists:
            logger.warning(
                "SocialPostEngagement table not found. "
                "Run 'flask db migrate' and 'flask db upgrade' to create it."
            )
        return _table_exists
    except Exception as e:
        logger.debug(f"Could not check table existence: {e}")
        return False


def record_post(
    platform: str,
    post_id: str,
    content_type: str = 'discussion',
    discussion_id: Optional[int] = None,
    hook_variant: Optional[str] = None,
    posted_at: Optional[datetime] = None
) -> Optional[int]:
    """
    Record a new social post for engagement tracking.

    Args:
        platform: 'x' or 'bluesky'
        post_id: Tweet ID or Bluesky URI
        content_type: 'discussion', 'daily_question', 'daily_brief', 'weekly_insights'
        discussion_id: Optional discussion ID if post is about a discussion
        hook_variant: Optional A/B test variant identifier
        posted_at: When the post was made (defaults to now)

    Returns:
        The engagement record ID, or None if failed
    """
    # Check if table exists before attempting to write
    if not _check_table_exists():
        return None

    from app import db
    from app.models import SocialPostEngagement

    try:
        # Check if already exists
        existing = SocialPostEngagement.query.filter_by(
            platform=platform,
            post_id=post_id
        ).first()

        if existing:
            logger.debug(f"Post already tracked: {platform}/{post_id}")
            return existing.id

        engagement = SocialPostEngagement(
            platform=platform,
            post_id=post_id,
            content_type=content_type,
            discussion_id=discussion_id,
            hook_variant=hook_variant,
            posted_at=posted_at or datetime.utcnow()
        )

        db.session.add(engagement)
        db.session.commit()

        logger.info(f"Recorded post for tracking: {platform}/{post_id} (variant: {hook_variant})")
        return engagement.id

    except Exception as e:
        logger.error(f"Failed to record post for tracking: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def fetch_x_engagement(tweet_id: str) -> Optional[Dict]:
    """
    Fetch engagement metrics for a tweet from X API.

    Returns dict with likes, retweets, replies, quotes, impressions.
    """
    global _x_rate_limited_until
    
    # Check if we're currently rate limited - skip all X fetches until reset
    if _x_rate_limited_until and datetime.utcnow() < _x_rate_limited_until:
        logger.debug(f"X rate limited until {_x_rate_limited_until}, skipping fetch for {tweet_id}")
        return None
    
    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_SECRET')
    access_token = os.environ.get('X_ACCESS_TOKEN')
    access_token_secret = os.environ.get('X_ACCESS_TOKEN_SECRET')

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logger.warning("X API credentials not set, skipping engagement fetch")
        return None

    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=False  # Don't block on rate limits - causes DB connection timeouts
        )

        # Fetch tweet with public metrics
        # Note: organic_metrics and non_public_metrics require paid API access
        # Free tier only provides public_metrics
        response = client.get_tweet(
            tweet_id,
            tweet_fields=['public_metrics'],
            user_auth=True
        )

        if not response or not response.data:
            logger.warning(f"No data returned for tweet {tweet_id}")
            return None

        # Access public_metrics from the tweet data object
        tweet_data = response.data
        metrics = getattr(tweet_data, 'public_metrics', {}) or {}

        # Note: We don't clear _x_rate_limited_until here - it's cleared at the 
        # start of new scheduler runs to ensure 15-min cooldown is honored within a batch
        
        return {
            'likes': metrics.get('like_count', 0),
            'reposts': metrics.get('retweet_count', 0),
            'replies': metrics.get('reply_count', 0),
            'quotes': metrics.get('quote_count', 0),
            'impressions': metrics.get('impression_count', 0),
        }

    except Exception as e:
        error_str = str(e).lower()
        # Handle rate limiting gracefully - skip this fetch and set cooldown
        if '429' in str(e) or 'rate limit' in error_str or 'too many requests' in error_str:
            # Set rate limit cooldown for 15 minutes (X rate limit window)
            global _x_rate_limited_until
            _x_rate_limited_until = datetime.utcnow() + timedelta(minutes=15)
            logger.warning(f"X rate limited while fetching engagement for {tweet_id}, pausing until {_x_rate_limited_until}")
            return None
        logger.error(f"Failed to fetch X engagement for {tweet_id}: {e}")
        return None


def fetch_bluesky_engagement(post_uri: str) -> Optional[Dict]:
    """
    Fetch engagement metrics for a Bluesky post.

    Returns dict with likes, reposts, replies.
    """
    app_password = os.environ.get('BLUESKY_APP_PASSWORD')

    if not app_password:
        logger.warning("BLUESKY_APP_PASSWORD not set, skipping engagement fetch")
        return None

    try:
        from atproto import Client

        client = Client()
        client.login("societyspeaks.bsky.social", app_password)

        # Get post thread which includes engagement counts
        # The atproto library's get_post_thread returns a ThreadViewPost
        response = client.get_post_thread(uri=post_uri, depth=0)

        if not response:
            logger.warning(f"No data returned for Bluesky post {post_uri}")
            return None

        # Navigate the response structure
        # response.thread is a ThreadViewPost which has a 'post' attribute
        thread = getattr(response, 'thread', None)
        if not thread:
            logger.warning(f"No thread data for Bluesky post {post_uri}")
            return None

        post = getattr(thread, 'post', None)
        if not post:
            logger.warning(f"No post data in thread for {post_uri}")
            return None

        # Get engagement counts - these are on the post object
        likes = getattr(post, 'like_count', 0) or 0
        reposts = getattr(post, 'repost_count', 0) or 0
        replies = getattr(post, 'reply_count', 0) or 0
        quotes = getattr(post, 'quote_count', 0) or 0

        return {
            'likes': likes,
            'reposts': reposts,
            'replies': replies,
            'quotes': quotes,
            'impressions': 0,  # Bluesky doesn't expose impressions
        }

    except Exception as e:
        logger.error(f"Failed to fetch Bluesky engagement for {post_uri}: {e}")
        return None


@with_db_retry()
def update_engagement(engagement_id: int) -> bool:
    """
    Update engagement metrics for a specific tracked post.

    Args:
        engagement_id: ID of the SocialPostEngagement record

    Returns:
        True if updated successfully
    """
    from app import db
    from app.models import SocialPostEngagement

    try:
        engagement = SocialPostEngagement.query.get(engagement_id)
        if not engagement:
            logger.warning(f"Engagement record {engagement_id} not found")
            return False

        if engagement.platform == 'x':
            metrics = fetch_x_engagement(engagement.post_id)
        elif engagement.platform == 'bluesky':
            metrics = fetch_bluesky_engagement(engagement.post_id)
        else:
            logger.warning(f"Unknown platform: {engagement.platform}")
            return False

        if not metrics:
            return False

        engagement.likes = metrics.get('likes', 0)
        engagement.reposts = metrics.get('reposts', 0)
        engagement.replies = metrics.get('replies', 0)
        engagement.quotes = metrics.get('quotes', 0)
        engagement.impressions = metrics.get('impressions', 0)
        engagement.last_updated = datetime.utcnow()

        db.session.commit()

        logger.info(
            f"Updated engagement for {engagement.platform}/{engagement.post_id}: "
            f"likes={engagement.likes}, reposts={engagement.reposts}, replies={engagement.replies}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to update engagement {engagement_id}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return False
    finally:
        cleanup_db_session()


def update_recent_engagements(hours: int = 48, limit: int = 50) -> int:
    """
    Update engagement metrics for recently posted content.

    Fetches engagement for posts made in the last N hours.
    Call this from a scheduler job.

    Args:
        hours: How far back to look for posts (default 48)
        limit: Maximum number of posts to update (default 50)

    Returns:
        Number of posts updated
    """
    # Check if table exists
    if not _check_table_exists():
        return 0

    from app.models import SocialPostEngagement

    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Get recent posts that haven't been updated in the last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)

        # Extract IDs first to avoid session detachment issues
        # (update_engagement calls cleanup_db_session which detaches objects)
        post_ids = [
            post.id for post in SocialPostEngagement.query.filter(
                SocialPostEngagement.posted_at >= cutoff,
                (SocialPostEngagement.last_updated < one_hour_ago) |
                (SocialPostEngagement.last_updated.is_(None))
            ).order_by(SocialPostEngagement.posted_at.desc()).limit(limit).all()
        ]

        if not post_ids:
            logger.debug("No posts to update")
            return 0

        # Reset rate limit if cooldown has expired (start of new batch)
        reset_x_rate_limit_if_expired()

        logger.info(f"Updating engagement for {len(post_ids)} recent posts")

        import time
        global _x_rate_limited_until
        updated_count = 0
        for i, post_id in enumerate(post_ids):
            # Check if rate limited - abort the entire batch to honor cooldown
            if _x_rate_limited_until and datetime.utcnow() < _x_rate_limited_until:
                logger.warning(f"X rate limited, aborting engagement batch ({i}/{len(post_ids)} processed)")
                break
            
            if update_engagement(post_id):
                updated_count += 1
            # Add delay between API calls to avoid rate limiting
            # X Free tier has strict rate limits - 2 second delay between fetches
            if i < len(post_ids) - 1:
                time.sleep(2)

        return updated_count

    except Exception as e:
        logger.error(f"Failed to update recent engagements: {e}")
        return 0


def get_engagement_summary(
    content_type: Optional[str] = None,
    days: int = 7
) -> Dict:
    """
    Get engagement summary statistics.

    Args:
        content_type: Filter by content type (optional)
        days: Number of days to analyze (default 7)

    Returns:
        Dict with summary statistics
    """
    # Return empty summary if table doesn't exist
    if not _check_table_exists():
        return {
            'total_posts': 0,
            'total_likes': 0,
            'total_reposts': 0,
            'total_replies': 0,
            'avg_engagement': 0,
            'top_posts': [],
            'by_platform': {},
            'by_variant': {},
        }

    from app.models import SocialPostEngagement
    from sqlalchemy import func

    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        query = SocialPostEngagement.query.filter(
            SocialPostEngagement.posted_at >= cutoff
        )

        if content_type:
            query = query.filter(SocialPostEngagement.content_type == content_type)

        posts = query.all()

        if not posts:
            return {
                'total_posts': 0,
                'total_likes': 0,
                'total_reposts': 0,
                'total_replies': 0,
                'avg_engagement': 0,
                'top_posts': [],
                'by_platform': {},
                'by_variant': {},
            }

        # Calculate totals
        total_likes = sum(p.likes or 0 for p in posts)
        total_reposts = sum(p.reposts or 0 for p in posts)
        total_replies = sum(p.replies or 0 for p in posts)
        total_engagement = sum(p.total_engagement for p in posts)

        # Top posts by engagement
        top_posts = sorted(posts, key=lambda p: p.total_engagement, reverse=True)[:5]

        # By platform
        by_platform = {}
        for p in posts:
            if p.platform not in by_platform:
                by_platform[p.platform] = {'posts': 0, 'engagement': 0}
            by_platform[p.platform]['posts'] += 1
            by_platform[p.platform]['engagement'] += p.total_engagement

        # By variant (for A/B testing)
        by_variant = {}
        for p in posts:
            variant = p.hook_variant or 'default'
            if variant not in by_variant:
                by_variant[variant] = {'posts': 0, 'engagement': 0, 'avg_engagement': 0}
            by_variant[variant]['posts'] += 1
            by_variant[variant]['engagement'] += p.total_engagement

        # Calculate average per variant
        for variant in by_variant:
            if by_variant[variant]['posts'] > 0:
                by_variant[variant]['avg_engagement'] = (
                    by_variant[variant]['engagement'] / by_variant[variant]['posts']
                )

        return {
            'total_posts': len(posts),
            'total_likes': total_likes,
            'total_reposts': total_reposts,
            'total_replies': total_replies,
            'avg_engagement': total_engagement / len(posts) if posts else 0,
            'top_posts': [p.to_dict() for p in top_posts],
            'by_platform': by_platform,
            'by_variant': by_variant,
        }

    except Exception as e:
        logger.error(f"Failed to get engagement summary: {e}")
        return {'error': str(e)}


def get_best_performing_variant(content_type: str = 'discussion', days: int = 30) -> Optional[str]:
    """
    Get the best performing hook variant based on engagement.

    Used for A/B testing to determine which variant to favor.

    Args:
        content_type: Content type to analyze
        days: Number of days to analyze

    Returns:
        The variant name with highest average engagement, or None
    """
    summary = get_engagement_summary(content_type=content_type, days=days)

    by_variant = summary.get('by_variant', {})

    if not by_variant:
        return None

    # Find variant with highest average engagement (minimum 5 posts)
    best_variant = None
    best_avg = 0

    for variant, stats in by_variant.items():
        if stats['posts'] >= 5 and stats['avg_engagement'] > best_avg:
            best_avg = stats['avg_engagement']
            best_variant = variant

    return best_variant
