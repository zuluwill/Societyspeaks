"""
Shared utilities for Partner API.

Contains rate limiting helpers, request parsing, analytics, and common functions.
"""
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import logging
from typing import Optional

from flask import request, current_app, url_for
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

# Partner ref: max length stored in DB (StatementVote.partner_ref)
PARTNER_REF_MAX_LENGTH = 50
PARTNER_REF_PATTERN = re.compile(r'[^a-z0-9-]')


def sanitize_partner_ref(value: Optional[str]) -> Optional[str]:
    """
    Sanitize partner reference for storage and analytics.

    Rules: lowercase, alphanumeric and hyphen only, max 50 chars.
    Used by vote endpoint and anywhere we store partner_ref.
    """
    if not value or not isinstance(value, str):
        return None
    cleaned = PARTNER_REF_PATTERN.sub('', value.lower().strip()[:PARTNER_REF_MAX_LENGTH])
    return cleaned or None


def get_rate_limit_key():
    """
    Generate rate limit key using IP and partner ref.

    Key format: "ip:ref" so that:
    - One abusive visitor doesn't exhaust limits for all visitors from that IP
    - Partners can have per-partner rate limit tiers in future

    Ref is sanitized and truncated to avoid DoS via very long ref strings.
    """
    ip = get_remote_address()
    ref_raw = get_partner_ref()
    if not ref_raw and request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            ref_raw = data.get('ref')
    if not isinstance(ref_raw, str):
        ref_raw = 'unknown'
    ref = sanitize_partner_ref(ref_raw) if ref_raw and ref_raw != 'unknown' else (ref_raw or 'unknown')
    if not ref:
        ref = 'unknown'
    return f"{ip}:{ref}"


def get_partner_ref():
    """
    Extract partner reference from request.

    Checks query params and headers for partner identification.

    Returns:
        str or None: Partner reference slug if found
    """
    # Check query param first (e.g., ?ref=observer)
    ref = request.args.get('ref')
    if ref:
        return ref

    # Check header (e.g., X-Partner-Ref: observer)
    ref = request.headers.get('X-Partner-Ref')
    if ref:
        return ref

    return None


def build_discussion_urls(discussion, include_ref=True):
    """
    Build standard URLs for a discussion (embed, consensus, snapshot).

    Args:
        discussion: Discussion model instance
        include_ref: Whether to include ref param if partner is known

    Returns:
        dict: Dictionary with embed_url, consensus_url, snapshot_url
    """
    ref = get_partner_ref() if include_ref else None
    ref = sanitize_partner_ref(ref) if ref else None
    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')

    # Build URLs
    embed_url = f"{base_url}/discussions/{discussion.id}/embed"
    consensus_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}/consensus"
    snapshot_url = f"{base_url}/api/discussions/{discussion.id}/snapshot"

    # Add ref parameter if we have partner context
    if ref:
        embed_url = append_ref_param(embed_url, ref)
        consensus_url = append_ref_param(consensus_url, ref)
        snapshot_url = append_ref_param(snapshot_url, ref)

    return {
        'embed_url': embed_url,
        'consensus_url': consensus_url,
        'snapshot_url': snapshot_url
    }


def append_ref_param(url: str, ref: str) -> str:
    """
    Append or replace the ref query parameter on a URL.

    Uses sanitized ref to avoid URL or analytics injection.
    """
    if not url or not ref:
        return url
    sanitized = sanitize_partner_ref(ref)
    if not sanitized:
        return url

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query['ref'] = [sanitized]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def is_partner_origin_allowed(origin, env: Optional[str] = None):
    """
    Check if the request origin is in the partner allowlist.

    Args:
        origin: The Origin header from the request

    Returns:
        bool: True if origin is allowed, False otherwise
    """
    if not origin:
        return False
    allowed_origins = get_partner_allowed_origins(env=env)
    return origin in allowed_origins


def get_partner_allowed_origins(env: Optional[str] = None):
    """
    Return allowed origins for partner embeds/API, including verified partner domains.
    """
    allowed = set()

    # Add configured origins (backwards compatibility / manual overrides)
    config_origins = current_app.config.get('PARTNER_ORIGINS', [])
    if isinstance(config_origins, str):
        config_origins = [o.strip() for o in config_origins.split(',') if o.strip()]
    for origin in config_origins or []:
        allowed.add(origin)

    try:
        from app.models import PartnerDomain
        query = PartnerDomain.query.filter(
            PartnerDomain.verified_at.isnot(None),
            PartnerDomain.is_active.is_(True)
        )
        if env:
            query = query.filter(PartnerDomain.env == env)
        for row in query.all():
            domain = (row.domain or '').strip().lower()
            if not domain:
                continue
            if domain.startswith('http://') or domain.startswith('https://'):
                allowed.add(domain)
            else:
                allowed.add(f"https://{domain}")
                if domain.startswith('localhost') or domain.startswith('127.0.0.1'):
                    allowed.add(f"http://{domain}")
    except Exception as e:
        logger.warning(f"Partner origin lookup failed: {e}")

    return list(allowed)


def get_discussion_participant_count(discussion):
    """
    Get the number of unique participants in a discussion.

    Counts both authenticated users and anonymous participants (by fingerprint).

    Args:
        discussion: Discussion model instance

    Returns:
        int: Number of unique participants
    """
    from sqlalchemy import func, distinct
    from app import db
    from app.models import StatementVote

    # Count authenticated users
    user_count = db.session.query(
        func.count(distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    # Count anonymous participants by fingerprint
    anon_count = db.session.query(
        func.count(distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id == discussion.id,
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0

    return user_count + anon_count


def get_discussion_statement_count(discussion):
    """
    Get the number of active (non-deleted) statements in a discussion.

    Args:
        discussion: Discussion model instance

    Returns:
        int: Number of active statements
    """
    from app.models import Statement

    return Statement.query.filter(
        Statement.discussion_id == discussion.id,
        Statement.is_deleted == False
    ).count()


def track_partner_event(event_name: str, properties: Optional[dict] = None):
    """
    Track a partner-related analytics event via PostHog.

    Automatically includes partner_ref and request context.

    Args:
        event_name: The event name (e.g., 'partner_embed_loaded', 'partner_api_lookup')
        properties: Additional event properties

    Common events:
        - partner_embed_loaded: When an embed is loaded on a partner site
        - partner_api_lookup: When lookup API is called
        - partner_api_snapshot: When snapshot API is called
        - partner_api_create: When create API is called
        - partner_consensus_view: When consensus page is viewed from partner context
    """
    try:
        import posthog
    except ImportError:
        return

    if not current_app.config.get('POSTHOG_API_KEY'):
        return

    partner_ref = get_partner_ref() or 'unknown'

    # Build base properties
    event_properties = {
        'partner_ref': partner_ref,
        'ip_address': get_remote_address(),
        'user_agent': request.headers.get('User-Agent', ''),
        'referer': request.headers.get('Referer', ''),
    }

    # Add origin if available (for embed tracking)
    origin = request.headers.get('Origin')
    if origin:
        event_properties['origin'] = origin

    # Merge with custom properties
    if properties:
        event_properties.update(properties)

    try:
        if posthog and getattr(posthog, 'project_api_key', None):
            posthog.capture(
                distinct_id=f"partner:{partner_ref}",
                event=event_name,
                properties=event_properties
            )
    except Exception as e:
        logger.warning(f"PostHog tracking error for {event_name}: {e}")


def record_partner_usage(partner_id: str, env: str, event_type: str, quantity: int = 1):
    """
    Record partner usage events for internal reporting.

    Uses after_this_request to commit usage events after the main response
    is sent, avoiding mid-request commits that could interfere with the
    caller's transaction.
    """
    try:
        from flask import after_this_request
        from app.models import Partner, PartnerUsageEvent
        from app import db

        partner = Partner.query.filter_by(slug=partner_id).first()
        if not partner:
            return

        event = PartnerUsageEvent(
            partner_id=partner.id,
            env=env,
            event_type=event_type,
            quantity=quantity
        )
        db.session.add(event)

        # The event will be committed when the main route handler commits,
        # or via after_this_request as a safety net.
        @after_this_request
        def _commit_usage(response):
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            return response

    except Exception as e:
        logger.warning(f"Partner usage recording error: {e}")


def invalidate_partner_snapshot_cache(discussion_id: int):
    """Invalidate cached partner snapshot payload for a discussion."""
    try:
        from app import cache
        cache.delete(f"snapshot:{discussion_id}")
    except Exception as e:
        logger.warning(f"Snapshot cache invalidation failed for discussion {discussion_id}: {e}")
