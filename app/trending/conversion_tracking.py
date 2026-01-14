"""
Conversion Tracking for Social Media Posts

Tracks conversions from social media using PostHog.
Events tracked:
- social_post_clicked (when user clicks link from social)
- discussion_participated (when user votes/participates)
- daily_question_subscribed (when user subscribes)
- daily_brief_subscribed (when user subscribes)
"""

import logging
from typing import Optional, Dict
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def track_social_conversion(
    event_name: str,
    properties: Dict,
    distinct_id: Optional[str] = None
) -> None:
    """
    Track conversion event with PostHog.
    
    Args:
        event_name: Name of the event (e.g., 'social_post_clicked')
        properties: Event properties (platform, campaign, etc.)
        distinct_id: User ID (if available, otherwise 'anonymous')
    """
    try:
        import posthog
        if not posthog:
            return
        
        posthog.capture(
            distinct_id=distinct_id or 'anonymous',
            event=event_name,
            properties=properties
        )
    except Exception as e:
        logger.warning(f"PostHog tracking error: {e}")


def extract_utm_params(url: str) -> Dict[str, str]:
    """
    Extract UTM parameters from URL.
    
    Returns dict with utm_source, utm_medium, utm_campaign
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    return {
        'utm_source': params.get('utm_source', [None])[0],
        'utm_medium': params.get('utm_medium', [None])[0],
        'utm_campaign': params.get('utm_campaign', [None])[0]
    }


def track_social_click(request, user_id: Optional[str] = None) -> None:
    """
    Track when user clicks a link from social media.
    
    Call this in route handlers that receive traffic from social media.
    """
    referer = request.headers.get('Referer', '')
    url = request.url
    
    # Check if this is from social media
    is_social = any(domain in referer for domain in ['twitter.com', 'x.com', 'bsky.social', 'bluesky.social'])
    
    if is_social or 'utm_source' in url:
        utm_params = extract_utm_params(url)
        
        track_social_conversion(
            event_name='social_post_clicked',
            properties={
                'referer': referer,
                'url': url,
                **utm_params
            },
            distinct_id=str(user_id) if user_id else None
        )
