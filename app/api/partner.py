"""
Partner API Endpoints

Provides lookup, snapshot, and create APIs for partner embed integration.
All endpoints return JSON and use standardized error responses.
"""
import re
import html
import json
import csv
import io
import hashlib
import secrets
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app, Response
from app import db, limiter, cache
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import contains_eager

from app.models import (
    Discussion, NewsArticle, DiscussionSourceArticle, ConsensusAnalysis, Statement,
    StatementFlag, StatementVote, PartnerUsageEvent, PartnerWebhookEndpoint, PartnerWebhookDelivery,
)
from app.discussions.statements import get_statement_vote_fingerprint
from app.api.errors import api_error
from app.api.utils import (
    get_rate_limit_key, get_partner_ref, build_discussion_urls, append_ref_param,
    get_discussion_participant_count, get_discussion_statement_count,
    sanitize_partner_ref, partner_ref_is_disabled, track_partner_event, record_partner_usage,
    is_partner_origin_allowed, invalidate_partner_snapshot_cache,
)
from app.partner.keys import find_partner_api_key
from app.lib.counter_utils import increment_counter
from app.lib.time import utcnow_naive
from app.partner.webhooks import emit_partner_event
from app.partner.events import (
    ALL_PARTNER_EVENTS,
    EVENT_DISCUSSION_CREATED,
    EVENT_DISCUSSION_UPDATED,
    serialize_discussion_payload,
)
from app.partner.webhooks import generate_webhook_secret
from flask_babel import gettext as _


partner_bp = Blueprint('partner_api', __name__)


@partner_bp.route('/discussions/by-article-url', methods=['GET'])
@limiter.limit("60 per minute", key_func=get_rate_limit_key)
def lookup_by_article_url():
    """
    Look up a discussion by article URL.

    Query Parameters:
        url (required): The article URL to look up
        ref (optional): Partner reference for analytics

    Returns:
        200: Discussion found with embed/snapshot/consensus URLs
        400: Invalid or missing URL
        404: No discussion found for this URL

    Example:
        GET /api/discussions/by-article-url?url=https://example.com/article&ref=observer
    """
    from app.lib.url_normalizer import normalize_url

    # Check if this partner ref is disabled (kill switch)
    ref = request.args.get('ref', '')
    ref_normalized = sanitize_partner_ref(ref)
    if ref_normalized and partner_ref_is_disabled(ref_normalized):
        return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    # Optional API key context (test/live)
    api_key = request.headers.get('X-API-Key')
    if api_key:
        is_valid, partner_slug, key_env, partner, __ = _validate_api_key()
        if not is_valid:
            return api_error('invalid_api_key', 'Invalid X-API-Key.', 401)
        # Apply account-level kill switches even on read endpoints.
        if partner and partner.status != 'active':
            return api_error('partner_inactive', 'Partner account is not active.', 403)
        if partner and partner.embed_disabled:
            return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)
    else:
        partner_slug = None
        key_env = 'live'

    # Get and validate URL parameter
    url = request.args.get('url')
    if not url:
        return api_error('missing_url', 'The url parameter is required.', 400)

    # Normalize the URL
    normalized = normalize_url(url)
    if not normalized:
        return api_error('invalid_url', 'The provided URL is not valid or could not be parsed.', 400)

    # Try cache first
    cache_key = f"lookup:{key_env}:{partner_slug or 'public'}:{normalized}"
    cached = cache.get(cache_key)
    if cached:
        response_data = cached
        if ref_normalized:
            response_data = dict(cached)
            response_data['embed_url'] = append_ref_param(response_data['embed_url'], ref_normalized)
            response_data['consensus_url'] = append_ref_param(response_data['consensus_url'], ref_normalized)
            response_data['snapshot_url'] = append_ref_param(response_data['snapshot_url'], ref_normalized)
        return jsonify(response_data)

    discussion = None
    source = 'rss'

    if key_env == 'test' and partner_slug:
        discussion = Discussion.query.filter_by(
            partner_article_url=normalized,
            partner_id=partner_slug,
            partner_env='test'
        ).first()
        source = 'partner'
    else:
        # Look up NewsArticle by normalized_url, then fall back to raw url
        article = NewsArticle.query.filter_by(normalized_url=normalized).first()
        if not article:
            article = NewsArticle.query.filter_by(url=url).first()
        if article:
            link = DiscussionSourceArticle.query.filter_by(article_id=article.id).first()
            if link:
                discussion = db.session.get(Discussion, link.discussion_id)

        # Phase 2: Check partner_article_url for live partner discussions
        if not discussion and hasattr(Discussion, 'partner_article_url'):
            query = Discussion.query.filter_by(partner_article_url=normalized, partner_env='live')
            if partner_slug:
                query = query.filter_by(partner_id=partner_slug)
            discussion = query.first()
            if discussion:
                source = 'partner'

    if not discussion:
        return api_error('no_discussion', 'No discussion found for this article URL.', 404)

    # Note: Discussions don't have is_deleted flag; they are hard-deleted
    # If we need soft-delete in future, add is_deleted column to Discussion model

    # Build response
    response_data = _serialize_partner_discussion_response(discussion, source=source)

    # Cache base response (without ref) for 5 minutes
    cache.set(cache_key, response_data, timeout=300)

    # Add ref to URLs for this request only (do not cache ref-specific URLs)
    if ref_normalized:
        response_data = dict(response_data)
        response_data['embed_url'] = append_ref_param(response_data['embed_url'], ref_normalized)
        response_data['consensus_url'] = append_ref_param(response_data['consensus_url'], ref_normalized)
        response_data['snapshot_url'] = append_ref_param(response_data['snapshot_url'], ref_normalized)

    # Track API lookup event
    track_partner_event('partner_api_lookup', {
        'discussion_id': discussion.id,
        'source': source,
        'cache_hit': False
    })
    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'lookup')

    return jsonify(response_data)


@partner_bp.route('/discussions/<int:discussion_id>/snapshot', methods=['GET'])
@limiter.limit("120 per minute", key_func=get_rate_limit_key)
def get_snapshot(discussion_id):
    """
    Get a snapshot of discussion participation (counts and link only).

    This endpoint returns teaser information for display on partner sites.
    It does NOT return analysis content, statement text, or consensus details.

    Path Parameters:
        discussion_id: The discussion ID

    Query Parameters:
        ref (optional): Partner reference for analytics

    Returns:
        200: Snapshot with participant/statement counts and consensus URL
        404: Discussion not found

    Example:
        GET /api/discussions/123/snapshot?ref=observer
    """
    # Check if this partner ref is disabled (kill switch)
    ref = request.args.get('ref', '')
    ref_normalized = sanitize_partner_ref(ref)
    if ref_normalized and partner_ref_is_disabled(ref_normalized):
        return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    # Load discussion first so test-env auth is enforced before any cache return.
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        return api_error('discussion_not_found', 'The requested discussion does not exist.', 404)

    # Auth: test discussions always require the owning partner's test key.
    # Live discussions are public without a key; if X-API-Key is sent (analytics / tooling),
    # apply the same partner.status / embed_disabled gates as lookup.
    api_key = request.headers.get('X-API-Key')
    if discussion.partner_env == 'test':
        is_valid, partner_slug, key_env, partner, __ = _validate_api_key()
        if not is_valid or key_env != 'test' or partner_slug != discussion.partner_id:
            return api_error('forbidden', 'A valid test API key is required for this discussion.', 403)
        if partner and partner.status != 'active':
            return api_error('partner_inactive', 'Partner account is not active.', 403)
        if partner and partner.embed_disabled:
            return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)
    elif api_key:
        is_valid, partner_slug, key_env, partner, __ = _validate_api_key()
        if not is_valid:
            return api_error('invalid_api_key', 'Invalid X-API-Key.', 401)
        if partner and partner.status != 'active':
            return api_error('partner_inactive', 'Partner account is not active.', 403)
        if partner and partner.embed_disabled:
            return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    # Try cache after auth checks.
    cache_key = f"snapshot:{discussion_id}"
    version_key = f"snapshot:version:{discussion_id}"
    try:
        current_snapshot_version = int(cache.get(version_key) or 0)
    except Exception:
        current_snapshot_version = 0
    cached = cache.get(cache_key)
    if cached:
        cached_version = 0
        if isinstance(cached, dict):
            try:
                cached_version = int(cached.get('_snapshot_version') or 0)
            except Exception:
                cached_version = 0
        if cached_version == current_snapshot_version:
            increment_counter("cache_metrics:snapshot:hit", ttl_seconds=24 * 3600, fallback_cache=cache)
            response_data = dict(cached) if isinstance(cached, dict) else cached
            if isinstance(response_data, dict):
                response_data.pop('_snapshot_version', None)
                if ref_normalized:
                    response_data['consensus_url'] = append_ref_param(response_data['consensus_url'], ref_normalized)
            track_partner_event('partner_api_snapshot', {
                'discussion_id': discussion_id,
                'has_analysis': bool(response_data.get('has_analysis')) if isinstance(response_data, dict) else False,
                'participant_count': response_data.get('participant_count') if isinstance(response_data, dict) else None,
                'cache_hit': True
            })
            return jsonify(response_data)

        increment_counter("cache_metrics:snapshot:stale_read", ttl_seconds=24 * 3600, fallback_cache=cache)
    increment_counter("cache_metrics:snapshot:miss", ttl_seconds=24 * 3600, fallback_cache=cache)

    # Get counts
    participant_count = get_discussion_participant_count(discussion)
    statement_count = get_discussion_statement_count(discussion)

    # Get latest consensus analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()

    # Build response
    urls = build_discussion_urls(discussion, include_ref=False)

    response_data = {
        'discussion_id': discussion.id,
        'discussion_title': discussion.title,
        'participant_count': participant_count,
        'statement_count': statement_count,
        'has_analysis': analysis is not None,
        'consensus_url': urls['consensus_url'],
        'env': discussion.partner_env
    }

    # Add analysis metadata if available (but NOT content)
    if analysis:
        response_data['opinion_groups'] = analysis.num_clusters
        response_data['analyzed_at'] = analysis.created_at.isoformat() if analysis.created_at else None

        # Optional teaser text from AI summary (one line only)
        if analysis.cluster_data and isinstance(analysis.cluster_data, dict):
            ai_summary = analysis.cluster_data.get('ai_summary')
            if ai_summary and isinstance(ai_summary, str):
                # Truncate to first sentence or 150 chars
                teaser = ai_summary.split('.')[0]
                if len(teaser) > 150:
                    teaser = teaser[:147] + '...'
                response_data['teaser_text'] = teaser

    # Cache base response (without ref) for 10 minutes (invalidated when new analysis is created)
    cache_payload = dict(response_data)
    cache_payload['_snapshot_version'] = current_snapshot_version
    cache.set(cache_key, cache_payload, timeout=600)

    # Add ref to consensus_url for this request only
    if ref_normalized:
        response_data = dict(response_data)
        response_data['consensus_url'] = append_ref_param(response_data['consensus_url'], ref_normalized)

    # Track snapshot API event
    track_partner_event('partner_api_snapshot', {
        'discussion_id': discussion.id,
        'has_analysis': response_data['has_analysis'],
        'participant_count': participant_count,
        'cache_hit': False
    })
    if discussion.partner_id:
        record_partner_usage(discussion.partner_id, discussion.partner_env, 'snapshot')

    return jsonify(response_data)


def _get_api_key_rate_limit_key():
    """Rate limit key by API key for create endpoint."""
    api_key = request.headers.get('X-API-Key', 'unknown')
    return f"create:{api_key[:16]}"  # Use prefix of key for privacy


def _validate_api_key():
    """
    Validate partner API key from request header.

    Returns:
        tuple: (is_valid, partner_slug, env, partner, key_record)
        partner_slug is Partner.slug (string), not a numeric id.
        key_record is the PartnerApiKey row for DB-backed keys; None for legacy CONFIG keys.
    """
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False, None, None, None, None

    record, partner, env = find_partner_api_key(api_key)
    if record and partner:
        return True, partner.slug, env, partner, record

    # Optional legacy config-key fallback (migration aid only).
    # Best practice is DB-backed portal keys for kill switches, billing enforcement,
    # and key-level attribution.
    allow_legacy = bool(current_app.config.get('ALLOW_LEGACY_PARTNER_API_KEYS', False))
    if not allow_legacy:
        return False, None, None, None, None

    from app.models import Partner
    api_keys = current_app.config.get('PARTNER_API_KEYS', {})
    partner_slug = api_keys.get(api_key)
    if partner_slug:
        partner = Partner.query.filter_by(slug=partner_slug).first()
        if not partner:
            current_app.logger.error(
                "Legacy PARTNER_API_KEYS mapping rejected: partner slug '%s' has no Partner row",
                partner_slug,
            )
            return False, None, None, None, None
        current_app.logger.warning(
            "Legacy PARTNER_API_KEYS auth accepted for partner '%s'. "
            "Migrate to portal-issued DB keys.",
            partner_slug,
        )
        return True, partner_slug, 'live', partner, None

    return False, None, None, None, None


def _normalize_idempotency_key(raw_key):
    if not raw_key or not isinstance(raw_key, str):
        return None
    cleaned = raw_key.strip()
    if not cleaned:
        return None
    return cleaned[:128]


def _idempotency_cache_key(partner_slug, key_env, idempotency_key):
    return f"idempotency:create:{key_env}:{partner_slug}:{idempotency_key}"


def _request_payload_hash(data):
    payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _partner_api_browser_forbidden():
    """Block browser calls that could leak X-API-Key (same rule as create)."""
    if request.headers.get('Origin'):
        return api_error(
            'browser_not_allowed',
            'Partner API write/read endpoints must be called server-to-server (no browser Origin header).',
            403
        )
    return None


def _discussion_owned_by_partner(discussion, partner_slug, partner):
    if not discussion or not partner_slug:
        return False
    if partner and getattr(discussion, 'partner_fk_id', None) and partner.id == discussion.partner_fk_id:
        return True
    if discussion.partner_id and discussion.partner_id == partner_slug:
        return True
    return False


def _require_partner_api_auth():
    """
    Single auth gate for all partner management API routes.

    Checks (in order): browser origin block, API key validity, account active status,
    and the DB-level embed_disabled kill switch.

    Returns (error_response, partner_slug, key_env, partner, key_record).
    error_response is non-None when auth fails; callers should do:
        err, partner_slug, key_env, partner, key_record = _require_partner_api_auth()
        if err: return err
    """
    err = _partner_api_browser_forbidden()
    if err:
        return err, None, None, None, None

    is_valid, partner_slug, key_env, partner, key_record = _validate_api_key()
    if not is_valid:
        return api_error('invalid_api_key', 'A valid X-API-Key header is required.', 401), None, None, None, None
    if partner and partner.status != 'active':
        return api_error('partner_inactive', 'Partner account is not active.', 403), None, None, None, None
    if partner and partner.embed_disabled:
        return api_error('partner_disabled', 'API access has been revoked for this partner.', 403), None, None, None, None
    return None, partner_slug, key_env, partner, key_record


_VALID_SEED_POSITIONS = frozenset(['pro', 'con', 'neutral'])
_MAX_SEED_STATEMENTS_PER_REQUEST = 50

# Input size limits for create_discussion — applied before any DB write or LLM call.
_CREATE_MAX_ARTICLE_URL = 2048
_CREATE_MAX_TITLE = 200  # matches Discussion.title column
_CREATE_MAX_EXCERPT = 5000
_CREATE_MAX_SOURCE_NAME = 200
_CREATE_MAX_EXTERNAL_ID = 128


def _partner_discussions_query(partner_slug, partner):
    """Return a Discussion query scoped to the authenticated partner."""
    q = Discussion.query
    if partner:
        return q.filter(
            db.or_(
                Discussion.partner_fk_id == partner.id,
                Discussion.partner_id == partner.slug,
            )
        )
    return q.filter(Discussion.partner_id == partner_slug)


def _serialize_partner_discussion_response(
    discussion,
    *,
    source='partner',
    statement_count=None,
    vote_count=None,
    has_consensus_analysis=None,
):
    """Canonical discussion response payload used across partner endpoints."""
    urls = build_discussion_urls(discussion, include_ref=False)
    payload = {
        'discussion_id': discussion.id,
        'slug': discussion.slug,
        'title': discussion.title,
        'partner_article_url': discussion.partner_article_url,
        'external_id': discussion.partner_external_id,
        'embed_statement_submissions_enabled': bool(getattr(discussion, 'embed_statement_submissions_enabled', False)),
        'embed_url': urls['embed_url'],
        'consensus_url': urls['consensus_url'],
        'snapshot_url': urls['snapshot_url'],
        'source': source,
        'env': discussion.partner_env,
    }
    if statement_count is not None:
        payload['statement_count'] = int(statement_count)
    if vote_count is not None:
        payload['vote_count'] = int(vote_count)
    if has_consensus_analysis is not None:
        payload['has_consensus_analysis'] = bool(has_consensus_analysis)
    return payload


def _validate_seed_statements(stmts):
    """
    Validate and normalise a seed_statements list from a partner API request.

    Enforces: max batch size, content length 10–500 chars, position enum.
    Returns (error_response_or_None, validated_list).
    """
    if len(stmts) > _MAX_SEED_STATEMENTS_PER_REQUEST:
        return api_error(
            'too_many_statements',
            f'At most {_MAX_SEED_STATEMENTS_PER_REQUEST} statements may be submitted per request.',
            400
        ), []
    to_add = []
    for i, stmt in enumerate(stmts):
        if not isinstance(stmt, dict) or 'content' not in stmt:
            return api_error('invalid_statement', f'Statement at index {i} must have a content field.', 400), []
        content = (stmt.get('content') or '').strip()
        if len(content) < 10:
            return api_error('invalid_statement', f'Statement at index {i} must be at least 10 characters.', 400), []
        if len(content) > 500:
            return api_error('invalid_statement', f'Statement at index {i} must be at most 500 characters.', 400), []
        position = (stmt.get('position') or 'neutral').lower()
        if position not in _VALID_SEED_POSITIONS:
            position = 'neutral'
        to_add.append({'content': content[:500], 'position': position})
    return None, to_add


@partner_bp.route('/partner/discussions', methods=['GET'])
@limiter.limit("120 per hour", key_func=_get_api_key_rate_limit_key)
def list_partner_discussions():
    """
    List discussions created by this partner (partner_fk_id or legacy partner_id slug).

    When the API key is a legacy CONFIG-only mapping (no Partner row), we only match
    Discussion.partner_id == slug. Discussions with only partner_fk_id require a real Partner account.

    Billing policy: listing existing discussions is intentionally allowed even when
    billing_status is inactive — partners can still audit/manage their content after
    a billing lapse. Only new discussion creation (POST /partner/discussions) requires
    active billing.

    Query: env=test|live|all (default all), page (default 1), per_page (default 30, max 100)
    """
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    env_filter = (request.args.get('env') or 'all').lower()
    if env_filter not in ('test', 'live', 'all'):
        env_filter = 'all'

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.args.get('per_page', 30))))
    except (TypeError, ValueError):
        per_page = 30

    q = _partner_discussions_query(partner_slug, partner)

    if env_filter != 'all':
        q = q.filter(Discussion.partner_env == env_filter)

    pagination = q.order_by(Discussion.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    page_ids = [d.id for d in pagination.items]

    # Batch vote totals — 1 query for the whole page instead of 1 per discussion
    vote_totals = {}
    if page_ids:
        rows = db.session.query(
            StatementVote.discussion_id,
            func.count(StatementVote.id),
        ).filter(
            StatementVote.discussion_id.in_(page_ids)
        ).group_by(StatementVote.discussion_id).all()
        vote_totals = {disc_id: count for disc_id, count in rows}

    # Batch consensus presence — 1 query for the whole page
    has_consensus = set()
    if page_ids:
        consensus_rows = db.session.query(ConsensusAnalysis.discussion_id).filter(
            ConsensusAnalysis.discussion_id.in_(page_ids)
        ).distinct().all()
        has_consensus = {row[0] for row in consensus_rows}

    items = []
    for d in pagination.items:
        item = _serialize_partner_discussion_response(
            d,
            vote_count=vote_totals.get(d.id, 0),
            has_consensus_analysis=(d.id in has_consensus),
        )
        item.update({
            'is_closed': d.is_closed,
            'integrity_mode': d.integrity_mode,
            'created_at': d.created_at.isoformat() if d.created_at else None,
        })
        items.append(item)

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'list_discussions')

    return jsonify({
        'items': items,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@partner_bp.route('/partner/discussions/by-external-id', methods=['GET'])
@limiter.limit("120 per hour", key_func=_get_api_key_rate_limit_key)
def lookup_partner_discussion_by_external_id():
    """Look up a partner-owned discussion by external_id."""
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    external_id = request.args.get('external_id')
    if external_id is None:
        return api_error('missing_external_id', 'The external_id parameter is required.', 400)
    if not isinstance(external_id, str):
        return api_error('invalid_external_id', 'The external_id must be a string.', 400)
    external_id = external_id.strip()
    if not external_id:
        return api_error('invalid_external_id', 'The external_id must not be empty.', 400)
    if len(external_id) > _CREATE_MAX_EXTERNAL_ID:
        return api_error(
            'invalid_external_id',
            f'The external_id must be at most {_CREATE_MAX_EXTERNAL_ID} characters.',
            400,
        )

    env_filter = (request.args.get('env') or key_env or 'all').lower()
    if env_filter not in ('test', 'live', 'all'):
        env_filter = key_env if key_env in ('test', 'live') else 'all'

    q = _partner_discussions_query(partner_slug, partner).filter(
        Discussion.partner_external_id == external_id
    )
    if env_filter != 'all':
        q = q.filter(Discussion.partner_env == env_filter)

    discussion = q.order_by(Discussion.created_at.desc()).first()
    if not discussion:
        return api_error('no_discussion', 'No discussion found for this external_id.', 404)

    if discussion.partner_env == 'test' and key_env != 'test':
        return api_error('forbidden', 'A valid test API key is required for this discussion.', 403)

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'lookup_external_id')

    return jsonify(_serialize_partner_discussion_response(discussion))


@partner_bp.route('/partner/analytics/usage-export', methods=['GET'])
@limiter.limit("60 per hour", key_func=_get_api_key_rate_limit_key)
def partner_usage_export():
    """Export partner usage events for BI/reporting (JSON or CSV)."""
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    if not partner:
        return api_error(
            'partner_not_found',
            'Usage export requires a portal-backed partner account.',
            400
        )

    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    days = min(365, max(1, days))

    env_filter = (request.args.get('env') or 'all').lower()
    if env_filter not in ('test', 'live', 'all'):
        env_filter = 'all'

    format_type = (request.args.get('format') or 'json').lower()
    if format_type not in ('json', 'csv'):
        return api_error('invalid_format', 'The format must be one of: json, csv.', 400)
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(500, max(1, int(request.args.get('per_page', 100))))
    except (TypeError, ValueError):
        per_page = 100

    from datetime import timedelta
    since_ts = utcnow_naive() - timedelta(days=days)

    q = PartnerUsageEvent.query.filter(
        PartnerUsageEvent.partner_id == partner.id,
        PartnerUsageEvent.created_at >= since_ts,
    )
    if env_filter != 'all':
        q = q.filter(PartnerUsageEvent.env == env_filter)

    pagination = q.order_by(
        PartnerUsageEvent.created_at.asc(),
        PartnerUsageEvent.id.asc(),
    ).paginate(page=page, per_page=per_page, error_out=False)
    rows = pagination.items
    items = [{
        'id': row.id,
        'event_type': row.event_type,
        'env': row.env,
        'quantity': row.quantity,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in rows]

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'usage_export')

    if format_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id', 'event_type', 'env', 'quantity', 'created_at'])
        for item in items:
            writer.writerow([
                item['id'],
                item['event_type'],
                item['env'],
                item['quantity'],
                item['created_at'],
            ])
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=partner-usage-{partner.slug}-{days}d.csv'
            }
        )

    return jsonify({
        'partner': partner.slug,
        'days': days,
        'env': env_filter,
        'count': len(items),
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'items': items,
    })


@partner_bp.route('/partner/webhooks', methods=['GET'])
@limiter.limit("120 per hour", key_func=_get_api_key_rate_limit_key)
def list_partner_webhooks():
    err, __, __, partner, __ = _require_partner_api_auth()
    if err:
        return err
    if not partner:
        return api_error('partner_not_found', 'Webhook management requires a portal-backed partner account.', 400)

    endpoints = PartnerWebhookEndpoint.query.filter_by(partner_id=partner.id).order_by(
        PartnerWebhookEndpoint.created_at.desc()
    ).all()
    return jsonify({
        'items': [{
            'id': ep.id,
            'url': ep.url,
            'status': ep.status,
            'event_types': ep.event_types or [],
            'secret_last4': ep.secret_last4,
            'last_delivery_at': ep.last_delivery_at.isoformat() if ep.last_delivery_at else None,
            'last_error': ep.last_error,
            'created_at': ep.created_at.isoformat() if ep.created_at else None,
        } for ep in endpoints]
    })


@partner_bp.route('/partner/webhooks', methods=['POST'])
@limiter.limit("30 per hour", key_func=_get_api_key_rate_limit_key)
def create_partner_webhook():
    err, __, __, partner, __ = _require_partner_api_auth()
    if err:
        return err
    if not partner:
        return api_error('partner_not_found', 'Webhook management requires a portal-backed partner account.', 400)

    data = request.get_json() or {}
    endpoint_url = (data.get('url') or '').strip()
    parsed = urlparse(endpoint_url)
    if not endpoint_url or parsed.scheme != 'https':
        return api_error('invalid_url', 'Webhook url must be a valid HTTPS URL.', 400)
    event_types = data.get('event_types') or []
    if not isinstance(event_types, list) or not event_types:
        return api_error('invalid_event_types', 'event_types must be a non-empty array.', 400)
    event_types = [e for e in event_types if e in ALL_PARTNER_EVENTS]
    if not event_types:
        return api_error('invalid_event_types', 'No supported event_types provided.', 400)

    try:
        secret_plain, secret_enc, secret_last4 = generate_webhook_secret()
    except Exception as exc:
        current_app.logger.error("create_partner_webhook secret generation failed: %s", exc)
        return api_error('secret_generation_failed', 'Could not generate webhook secret.', 500)

    endpoint = PartnerWebhookEndpoint(
        partner_id=partner.id,
        url=endpoint_url[:1000],
        status='active',
        event_types=event_types,
        encrypted_signing_secret=secret_enc,
        secret_last4=secret_last4,
    )
    try:
        db.session.add(endpoint)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("create_partner_webhook failed: %s", exc)
        return api_error('create_failed', 'Could not create webhook endpoint.', 500)

    return jsonify({
        'id': endpoint.id,
        'url': endpoint.url,
        'status': endpoint.status,
        'event_types': endpoint.event_types,
        'signing_secret': secret_plain,
        'secret_last4': endpoint.secret_last4,
    }), 201


@partner_bp.route('/partner/webhooks/<int:endpoint_id>', methods=['PATCH'])
@limiter.limit("60 per hour", key_func=_get_api_key_rate_limit_key)
def patch_partner_webhook(endpoint_id):
    err, __, __, partner, __ = _require_partner_api_auth()
    if err:
        return err
    if not partner:
        return api_error('partner_not_found', 'Webhook management requires a portal-backed partner account.', 400)

    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first()
    if not endpoint:
        return api_error('webhook_not_found', 'Webhook endpoint was not found.', 404)

    data = request.get_json() or {}
    if 'status' in data:
        status = (data.get('status') or '').strip().lower()
        if status not in ('active', 'paused', 'disabled'):
            return api_error('invalid_status', 'status must be active, paused, or disabled.', 400)
        endpoint.status = status
    if 'event_types' in data:
        event_types = data.get('event_types')
        if not isinstance(event_types, list) or not event_types:
            return api_error('invalid_event_types', 'event_types must be a non-empty array.', 400)
        event_types = [e for e in event_types if e in ALL_PARTNER_EVENTS]
        if not event_types:
            return api_error('invalid_event_types', 'No supported event_types provided.', 400)
        endpoint.event_types = event_types

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("patch_partner_webhook failed: %s", exc)
        return api_error('update_failed', 'Could not update webhook endpoint.', 500)
    return jsonify({
        'id': endpoint.id,
        'url': endpoint.url,
        'status': endpoint.status,
        'event_types': endpoint.event_types,
        'secret_last4': endpoint.secret_last4,
    })


@partner_bp.route('/partner/webhooks/<int:endpoint_id>/rotate-secret', methods=['POST'])
@limiter.limit("20 per hour", key_func=_get_api_key_rate_limit_key)
def rotate_partner_webhook_secret(endpoint_id):
    err, __, __, partner, __ = _require_partner_api_auth()
    if err:
        return err
    if not partner:
        return api_error('partner_not_found', 'Webhook management requires a portal-backed partner account.', 400)
    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first()
    if not endpoint:
        return api_error('webhook_not_found', 'Webhook endpoint was not found.', 404)
    try:
        secret_plain, secret_enc, secret_last4 = generate_webhook_secret()
    except Exception as exc:
        current_app.logger.error("rotate_partner_webhook_secret generation failed: %s", exc)
        return api_error('secret_generation_failed', 'Could not generate webhook secret.', 500)
    endpoint.encrypted_signing_secret = secret_enc
    endpoint.secret_last4 = secret_last4
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("rotate_partner_webhook_secret save failed: %s", exc)
        return api_error('update_failed', 'Could not rotate webhook secret.', 500)
    return jsonify({
        'id': endpoint.id,
        'signing_secret': secret_plain,
        'secret_last4': endpoint.secret_last4,
    })


@partner_bp.route('/partner/webhooks/<int:endpoint_id>', methods=['DELETE'])
@limiter.limit("20 per hour", key_func=_get_api_key_rate_limit_key)
def delete_partner_webhook(endpoint_id):
    err, __, __, partner, __ = _require_partner_api_auth()
    if err:
        return err
    if not partner:
        return api_error('partner_not_found', 'Webhook management requires a portal-backed partner account.', 400)
    endpoint = PartnerWebhookEndpoint.query.filter_by(id=endpoint_id, partner_id=partner.id).first()
    if not endpoint:
        return api_error('webhook_not_found', 'Webhook endpoint was not found.', 404)
    try:
        PartnerWebhookDelivery.query.filter_by(endpoint_id=endpoint.id).delete(synchronize_session=False)
        db.session.delete(endpoint)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("delete_partner_webhook failed: %s", exc)
        return api_error('delete_failed', 'Could not delete webhook endpoint.', 500)
    return jsonify({'success': True})


@partner_bp.route('/partner/discussions/<int:discussion_id>', methods=['PATCH'])
@limiter.limit("60 per hour", key_func=_get_api_key_rate_limit_key)
def patch_partner_discussion(discussion_id):
    """Update partner-owned discussion (is_closed, integrity_mode, embed_statement_submissions_enabled).

    Billing policy: managing existing discussions is intentionally allowed even when
    billing_status is inactive — partners can still close/reopen discussions after a
    billing lapse. Only new discussion creation requires active billing.
    """
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        return api_error('discussion_not_found', 'The requested discussion does not exist.', 404)

    if not _discussion_owned_by_partner(discussion, partner_slug, partner):
        return api_error('forbidden', 'This discussion does not belong to your partner account.', 403)

    if discussion.partner_env == 'test' and (not partner or key_env != 'test'):
        return api_error('forbidden', 'A valid test API key is required for this discussion.', 403)

    data = request.get_json()
    if not data or not isinstance(data, dict):
        return api_error('invalid_request', 'Request body must be a JSON object.', 400)

    changed = False
    if 'is_closed' in data:
        val = data['is_closed']
        if not isinstance(val, bool):
            return api_error('invalid_request', '"is_closed" must be a JSON boolean (true or false).', 400)
        discussion.is_closed = val
        changed = True
    if 'integrity_mode' in data:
        val = data['integrity_mode']
        if not isinstance(val, bool):
            return api_error('invalid_request', '"integrity_mode" must be a JSON boolean (true or false).', 400)
        discussion.integrity_mode = val
        changed = True
    if 'embed_statement_submissions_enabled' in data:
        val = data['embed_statement_submissions_enabled']
        if not isinstance(val, bool):
            return api_error(
                'invalid_request',
                '"embed_statement_submissions_enabled" must be a JSON boolean (true or false).',
                400,
            )
        discussion.embed_statement_submissions_enabled = val
        changed = True

    if not changed:
        return api_error(
            'invalid_request',
            'No supported fields to update (is_closed, integrity_mode, embed_statement_submissions_enabled).',
            400,
        )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"patch_partner_discussion: {e}")
        return api_error('update_failed', 'Could not update discussion.', 500)
    try:
        if partner:
            emit_partner_event(
                partner_id=partner.id,
                event_type=EVENT_DISCUSSION_UPDATED,
                data=serialize_discussion_payload(discussion),
            )
    except Exception:
        current_app.logger.exception("Failed to emit discussion.updated webhook event")

    invalidate_partner_snapshot_cache(discussion_id)

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'patch_discussion')

    payload = _serialize_partner_discussion_response(discussion)
    payload.update({
        'is_closed': discussion.is_closed,
        'integrity_mode': discussion.integrity_mode,
    })
    return jsonify(payload)


@partner_bp.route('/partner/discussions/<int:discussion_id>/statements', methods=['POST'])
@limiter.limit("60 per hour", key_func=_get_api_key_rate_limit_key)
def add_partner_discussion_statements(discussion_id):
    """Append seed statements to an existing partner discussion.

    Billing policy: appending statements to an existing discussion is intentionally
    allowed even when billing_status is inactive — partners can seed content they
    already own. Only new discussion creation requires active billing.
    """
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    discussion = db.session.get(Discussion, discussion_id)
    if not discussion or not discussion.has_native_statements:
        return api_error('discussion_not_found', 'Discussion not found or not a native statement discussion.', 404)

    if not _discussion_owned_by_partner(discussion, partner_slug, partner):
        return api_error('forbidden', 'This discussion does not belong to your partner account.', 403)

    if discussion.partner_env == 'test' and (not partner or key_env != 'test'):
        return api_error('forbidden', 'A valid test API key is required for this discussion.', 403)

    data = request.get_json()
    if not data or not isinstance(data, dict):
        return api_error('invalid_request', 'Request body must be a JSON object.', 400)

    seed_statements = data.get('seed_statements')
    if not seed_statements or not isinstance(seed_statements, list):
        return api_error('invalid_request', 'seed_statements array is required.', 400)

    err, to_add = _validate_seed_statements(seed_statements)
    if err:
        return err

    max_st = current_app.config.get('MAX_STATEMENTS_PER_DISCUSSION', 5000)
    current_count = Statement.query.filter_by(discussion_id=discussion_id, is_deleted=False).count()
    if current_count >= max_st:
        return api_error('limit_reached', 'This discussion has reached the maximum number of statements.', 429)

    remaining = max_st - current_count
    if len(to_add) > remaining:
        return api_error(
            'too_many_statements',
            f'Can add at most {remaining} more statements (discussion limit {max_st}).',
            400
        )

    try:
        for stmt_data in to_add:
            db.session.add(Statement(
                discussion_id=discussion_id,
                content=stmt_data['content'],
                statement_type='claim',
                is_seed=True,
                mod_status=1,
                source='partner_provided',
                seed_stance=stmt_data.get('position'),
            ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"add_partner_discussion_statements: {e}")
        return api_error('creation_failed', 'Failed to add statements.', 500)

    invalidate_partner_snapshot_cache(discussion_id)

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'add_statements')

    return jsonify({
        'discussion_id': discussion_id,
        'added': len(to_add),
        'statement_count': Statement.query.filter_by(discussion_id=discussion_id, is_deleted=False).count(),
    }), 201


@partner_bp.route('/partner/discussions/<int:discussion_id>/flags', methods=['GET'])
@limiter.limit("120 per hour", key_func=_get_api_key_rate_limit_key)
def list_partner_discussion_flags(discussion_id):
    """List moderation flags for statements in this discussion (partner inbox)."""
    err, partner_slug, key_env, partner, __ = _require_partner_api_auth()
    if err:
        return err

    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        return api_error('discussion_not_found', 'The requested discussion does not exist.', 404)

    if not _discussion_owned_by_partner(discussion, partner_slug, partner):
        return api_error('forbidden', 'This discussion does not belong to your partner account.', 403)

    status_filter = (request.args.get('status') or 'pending').lower()
    if status_filter not in ('pending', 'reviewed', 'dismissed', 'all'):
        status_filter = 'pending'

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.args.get('per_page', 30))))
    except (TypeError, ValueError):
        per_page = 30

    q = (
        StatementFlag.query.join(Statement, StatementFlag.statement_id == Statement.id)
        .filter(Statement.discussion_id == discussion_id)
        .options(contains_eager(StatementFlag.statement))
    )
    if status_filter != 'all':
        q = q.filter(StatementFlag.status == status_filter)

    pagination = q.order_by(StatementFlag.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    out = []
    for fl in pagination.items:
        st = fl.statement
        out.append({
            'flag_id': fl.id,
            'statement_id': fl.statement_id,
            'statement_excerpt': (st.content[:120] + '…') if st and len(st.content) > 120 else (st.content if st else ''),
            'flag_reason': fl.flag_reason,
            'status': fl.status,
            'created_at': fl.created_at.isoformat() if fl.created_at else None,
            'additional_context': fl.additional_context,
        })

    if partner_slug:
        record_partner_usage(partner_slug, key_env, 'list_flags')

    return jsonify({
        'discussion_id': discussion_id,
        'items': out,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@partner_bp.route('/partner/discussions', methods=['POST'])
@limiter.limit("30 per hour", key_func=_get_api_key_rate_limit_key)
def create_discussion():
    """
    Create a new discussion for a partner article or partner external context.

    This endpoint allows partners to create discussions for articles
    that are not ingested via RSS. Requires API key authentication.

    Headers:
        X-API-Key (required): Partner API key
        Content-Type: application/json

    Request Body:
        article_url (optional): The article URL (will be normalized)
        external_id (optional): Stable partner-defined identifier (required when article_url omitted)
        embed_statement_submissions_enabled (optional): Allow reader statement submissions directly in embed
        title (required): Discussion title
        excerpt (optional): Article excerpt for seed statement generation
        source_name (optional): Partner/source name for attribution
        seed_statements (optional): Array of {content, position} statements

    Note: Either excerpt or seed_statements must be provided.

    Returns:
        201: Discussion created with embed/snapshot/consensus URLs
        400: Invalid request (missing fields, validation errors)
        401: Invalid or missing API key
        409: Discussion already exists for this URL
        429: Rate limit exceeded

    Example:
        POST /api/partner/discussions
        {
            "article_url": "https://example.com/article",
            "title": "Should cities ban cars?",
            "excerpt": "A new study shows...",
            "source_name": "Example News"
        }
    """
    from app.lib.url_normalizer import normalize_url
    from app.trending.seed_generator import generate_seed_statements_from_content
    from app.trending.constants import get_unique_slug
    from app.models import generate_slug

    err, partner_slug, key_env, partner, key_record = _require_partner_api_auth()
    if err:
        return err

    created_by_key_id = key_record.id if key_record else None

    if key_env == 'live' and partner and partner.billing_status != 'active':
        return api_error(
            'billing_inactive',
            'Live API access requires an active subscription.',
            402
        )

    # Enforce discussion creation limits per tier
    if partner:
        tier_limits = current_app.config.get('PARTNER_TIER_LIMITS', {})
        partner_tier = getattr(partner, 'tier', 'free') or 'free'
        tier_limit = tier_limits.get(partner_tier, 25)  # default conservative

        if tier_limit is not None:  # None = unlimited (enterprise)
            from datetime import datetime, timezone
            if key_env == 'test':
                # Test: lifetime cap
                env_count = Discussion.query.filter_by(
                    partner_fk_id=partner.id, partner_env='test'
                ).count()
            else:
                # Live: calendar-month cap
                month_start = datetime.now(timezone.utc).replace(
                    tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0
                )
                env_count = Discussion.query.filter(
                    Discussion.partner_fk_id == partner.id,
                    Discussion.partner_env == 'live',
                    Discussion.created_at >= month_start
                ).count()

            if env_count >= tier_limit:
                limit_label = f"{tier_limit} discussions" + (" this month" if key_env == 'live' else "")
                return api_error(
                    f'{key_env}_limit_reached',
                    f'Your {partner_tier.title()} plan is limited to {limit_label}. '
                    f'Upgrade your plan for higher limits.',
                    429
                )

    # Parse JSON body
    data = request.get_json()
    if not data:
        return api_error(
            'invalid_request',
            'Request body must be valid JSON.',
            400
        )
    if not isinstance(data, dict):
        return api_error('invalid_request', 'Request body must be a JSON object.', 400)

    idempotency_key = _normalize_idempotency_key(request.headers.get('Idempotency-Key'))
    request_hash = _request_payload_hash(data)
    idempotency_cache_key = None
    if idempotency_key:
        idempotency_cache_key = _idempotency_cache_key(partner_slug, key_env, idempotency_key)
        prior = cache.get(idempotency_cache_key)
        if prior:
            if prior.get('request_hash') != request_hash:
                return api_error(
                    'idempotency_key_reused',
                    'This Idempotency-Key was already used with a different request payload.',
                    409
                )
            return jsonify(prior.get('response', {})), int(prior.get('status_code', 201))

    # Validate required fields
    article_url = data.get('article_url')
    external_id = data.get('external_id')
    embed_statement_submissions_enabled = data.get('embed_statement_submissions_enabled', False)
    title = data.get('title')

    if not isinstance(embed_statement_submissions_enabled, bool):
        return api_error(
            'invalid_request',
            '"embed_statement_submissions_enabled" must be a JSON boolean (true or false).',
            400,
        )

    normalized_url = None
    if article_url is not None:
        if not isinstance(article_url, str):
            return api_error('invalid_article_url', 'The article_url must be a string.', 400)
        if len(article_url) > _CREATE_MAX_ARTICLE_URL:
            return api_error(
                'invalid_article_url',
                f'The article_url must be at most {_CREATE_MAX_ARTICLE_URL} characters.',
                400,
            )
        article_url = article_url.strip()
        if article_url:
            normalized_url = normalize_url(article_url)
            if not normalized_url:
                return api_error(
                    'invalid_url',
                    'The provided article_url is not valid or could not be parsed.',
                    400
                )
        else:
            article_url = None

    if external_id is not None:
        if not isinstance(external_id, str):
            return api_error('invalid_external_id', 'The external_id must be a string.', 400)
        external_id = external_id.strip()
        if not external_id:
            external_id = None
        elif len(external_id) > _CREATE_MAX_EXTERNAL_ID:
            return api_error(
                'invalid_external_id',
                f'The external_id must be at most {_CREATE_MAX_EXTERNAL_ID} characters.',
                400
            )

    if not normalized_url and not external_id:
        return api_error(
            'missing_identifier',
            'Provide at least one identifier: article_url or external_id.',
            400
        )

    if not title:
        return api_error('missing_title', 'The title field is required.', 400)
    if not isinstance(title, str):
        return api_error('invalid_title', 'The title must be a string.', 400)
    if len(title) > _CREATE_MAX_TITLE:
        return api_error(
            'invalid_title',
            f'The title must be at most {_CREATE_MAX_TITLE} characters.',
            400,
        )

    # Validate: need either excerpt or seed_statements
    excerpt = data.get('excerpt')
    seed_statements = data.get('seed_statements')
    source_name = data.get('source_name')

    if not excerpt and not seed_statements:
        return api_error(
            'missing_content',
            'Either excerpt or seed_statements must be provided.',
            400
        )

    # Enforce length caps on inputs passed to the AI generator.
    # Without these, an oversized payload would still hit the LLM even though the
    # final DB write is capped — wasting tokens and risking cost/DoS.
    if excerpt and not isinstance(excerpt, str):
        return api_error('invalid_excerpt', 'The excerpt must be a string.', 400)
    if excerpt and len(excerpt) > _CREATE_MAX_EXCERPT:
        return api_error(
            'invalid_excerpt',
            f'The excerpt must be at most {_CREATE_MAX_EXCERPT} characters.',
            400
        )
    if source_name and not isinstance(source_name, str):
        return api_error('invalid_source_name', 'The source_name must be a string.', 400)
    if source_name and len(source_name) > _CREATE_MAX_SOURCE_NAME:
        return api_error(
            'invalid_source_name',
            f'The source_name must be at most {_CREATE_MAX_SOURCE_NAME} characters.',
            400
        )

    # Check if discussion already exists for this URL and/or external_id.
    if normalized_url:
        existing = Discussion.query.filter_by(
            partner_article_url=normalized_url,
            partner_id=partner_slug,
            partner_env=key_env
        ).first()
        if existing:
            return api_error(
                'discussion_exists',
                f'A discussion already exists for this URL (id: {existing.id}).',
                409
            )

    if external_id:
        existing = _partner_discussions_query(partner_slug, partner).filter_by(
            partner_external_id=external_id,
            partner_env=key_env,
        ).first()
        if existing:
            return api_error(
                'discussion_exists',
                f'A discussion already exists for this external_id (id: {existing.id}).',
                409
            )

    # Also check NewsArticle path (normalized_url + raw url fallback)
    if key_env == 'live' and normalized_url:
        article = NewsArticle.query.filter_by(normalized_url=normalized_url).first()
        if not article:
            article = NewsArticle.query.filter_by(url=article_url).first()
        if article:
            link = DiscussionSourceArticle.query.filter_by(article_id=article.id).first()
            if link:
                return api_error(
                    'discussion_exists',
                    f'A discussion already exists for this URL via RSS (id: {link.discussion_id}).',
                    409
                )

    # Generate seed statements if not provided
    statements_to_create = []
    if seed_statements:
        err, statements_to_create = _validate_seed_statements(seed_statements)
        if err:
            return err
    else:
        # Generate from excerpt using AI
        try:
            statements_to_create = generate_seed_statements_from_content(
                title=title,
                excerpt=excerpt,
                source_name=source_name,
                count=5
            )
        except Exception as e:
            current_app.logger.error(f"Seed generation failed for partner {partner_slug}: {e}")
            return api_error(
                'generation_failed',
                'Failed to generate seed statements. Please try again or provide seed_statements.',
                500
            )

        if not statements_to_create:
            return api_error(
                'generation_failed',
                'Could not generate seed statements from the provided content. Please provide seed_statements.',
                500
            )

    # Create discussion
    # Two-tier uniqueness strategy:
    # 1) get_unique_slug() resolves known conflicts already committed in the DB.
    # 2) outer retry handles race conditions where a competing request commits
    #    the same slug between our uniqueness check and flush().
    max_slug_retries = 3
    discussion = None
    base_slug = generate_slug(title) or 'discussion'
    for attempt in range(max_slug_retries):
        try:
            slug_seed = base_slug if attempt == 0 else f"{base_slug}-{secrets.token_hex(2)}"
            unique_slug = get_unique_slug(Discussion, slug_seed)

            discussion = Discussion(
                title=title[:_CREATE_MAX_TITLE],
                description=excerpt[:500] if excerpt else None,
                slug=unique_slug,
                has_native_statements=True,
                geographic_scope='global',
                partner_article_url=normalized_url,
                partner_external_id=external_id,
                embed_statement_submissions_enabled=embed_statement_submissions_enabled,
                partner_id=partner_slug,
                partner_fk_id=partner.id if partner else None,
                partner_env=key_env,
                created_by_key_id=created_by_key_id,
            )
            db.session.add(discussion)
            db.session.flush()  # Get the discussion ID

            # Create seed statements with source tracking
            # Determine source: partner_provided if statements came from API, ai_generated if from LLM
            statement_source = 'partner_provided' if seed_statements else 'ai_generated'
            for stmt_data in statements_to_create:
                statement = Statement(
                    discussion_id=discussion.id,
                    content=stmt_data['content'],
                    statement_type='claim',
                    is_seed=True,
                    mod_status=1,  # Seed statements are pre-approved
                    source=statement_source,
                    seed_stance=stmt_data.get('position'),
                )
                db.session.add(statement)

            db.session.commit()

            current_app.logger.info(
                f"Partner {partner_slug} created discussion {discussion.id} "
                f"for {normalized_url or external_id}"
            )
            if partner:
                try:
                    emit_partner_event(
                        partner_id=partner.id,
                        event_type=EVENT_DISCUSSION_CREATED,
                        data=serialize_discussion_payload(discussion),
                    )
                except Exception:
                    current_app.logger.exception("Failed to emit discussion.created webhook event")
            break

        except IntegrityError as e:
            db.session.rollback()
            err_text = str(getattr(e, "orig", e)).lower()
            is_slug_collision = ("slug" in err_text) or ("ix_discussion_slug" in err_text) or ("discussion.slug" in err_text)
            if not is_slug_collision:
                current_app.logger.error(
                    "Failed to create partner discussion due to non-slug integrity error for partner %s: %s",
                    partner_slug,
                    e,
                )
                return api_error(
                    'creation_failed',
                    'Failed to create discussion. Please check inputs and try again.',
                    500
                )
            if attempt == max_slug_retries - 1:
                current_app.logger.error(
                    "Failed to create partner discussion after slug retries for partner %s: %s",
                    partner_slug,
                    e,
                )
                return api_error(
                    'creation_failed',
                    'Failed to create discussion due to a temporary conflict. Please retry.',
                    500
                )
            current_app.logger.warning(
                "Slug conflict while creating partner discussion (attempt %s/%s): %s",
                attempt + 1,
                max_slug_retries,
                e,
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to create partner discussion: {e}")
            return api_error(
                'creation_failed',
                'Failed to create discussion. Please try again.',
                500
            )

    # Build response (same shape as lookup)
    response_data = _serialize_partner_discussion_response(
        discussion,
        statement_count=len(statements_to_create),
    )

    # Track create API event
    track_partner_event('partner_api_create', {
        'discussion_id': discussion.id,
        'partner_id': partner_slug,
        'statement_count': len(statements_to_create),
        'used_ai_generation': not bool(seed_statements)
    })
    record_partner_usage(partner_slug, key_env, 'create')

    if idempotency_cache_key:
        cache.set(
            idempotency_cache_key,
            {
                'request_hash': request_hash,
                'response': response_data,
                'status_code': 201
            },
            timeout=86400
        )

    return jsonify(response_data), 201


@partner_bp.route('/oembed', methods=['GET'])
@limiter.limit("120 per minute", key_func=get_rate_limit_key)
def oembed():
    """
    oEmbed provider endpoint.

    Returns oEmbed JSON response for Society Speaks discussion URLs.
    Supports both discussion pages and consensus pages.

    Query Parameters:
        url (required): The Society Speaks discussion URL
        maxwidth (optional): Maximum width for the embed
        maxheight (optional): Maximum height for the embed
        format (optional): Response format (only 'json' supported)

    Returns:
        200: oEmbed response with iframe HTML
        400: Invalid or missing URL
        404: Discussion not found
        501: Unsupported format (if not 'json')

    Example:
        GET /api/oembed?url=https://societyspeaks.io/discussions/123/my-discussion/consensus
    """
    url = request.args.get('url')
    if not url:
        return api_error('missing_url', 'The url parameter is required.', 400)

    # Check format parameter (only json supported)
    format_param = request.args.get('format', 'json').lower()
    if format_param != 'json':
        return api_error('unsupported_format', 'Only JSON format is supported.', 501)

    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')

    # Parse the URL to extract discussion ID
    # Supported patterns:
    # - /discussions/{id}/embed
    # - /discussions/{id}/{slug}
    # - /discussions/{id}/{slug}/consensus
    patterns = [
        rf'^{re.escape(base_url)}/discussions/(\d+)/embed',
        rf'^{re.escape(base_url)}/discussions/(\d+)/[^/]+/consensus',
        rf'^{re.escape(base_url)}/discussions/(\d+)/[^/]+$',
        rf'^{re.escape(base_url)}/discussions/(\d+)$',
    ]

    discussion_id = None
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            discussion_id = int(match.group(1))
            break

    if not discussion_id:
        return api_error(
            'invalid_url',
            'The URL does not match a Society Speaks discussion format.',
            400
        )

    # Look up the discussion
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        return api_error('discussion_not_found', 'The requested discussion does not exist.', 404)

    # Get optional size constraints
    max_width = request.args.get('maxwidth', type=int)
    max_height = request.args.get('maxheight', type=int)

    # Default dimensions
    width = 600
    height = 400

    # Apply constraints
    if max_width and max_width < width:
        width = max_width
    if max_height and max_height < height:
        height = max_height

    # Build embed URL
    embed_url = f"{base_url}/discussions/{discussion.id}/embed"

    # Build iframe HTML (escape title to prevent XSS in oEmbed consumer)
    safe_title = html.escape(discussion.title, quote=True)

    iframe_html = (
        f'<iframe src="{embed_url}" '
        f'width="{width}" height="{height}" '
        f'frameborder="0" '
        f'title="Society Speaks: {safe_title}" '
        f'loading="lazy" '
        f'allow="clipboard-write">'
        f'</iframe>'
    )

    # Build oEmbed response
    response_data = {
        'type': 'rich',
        'version': '1.0',
        'title': safe_title,
        'provider_name': 'Society Speaks',
        'provider_url': base_url,
        'html': iframe_html,
        'width': width,
        'height': height,
        'thumbnail_url': None,  # Could add discussion thumbnail in future
        'cache_age': 3600  # Cache for 1 hour
    }

    return jsonify(response_data)


@partner_bp.route('/embed/flag', methods=['POST'])
@limiter.limit("10 per minute", key_func=get_rate_limit_key)
def flag_statement_from_embed():
    """
    Flag a statement from the embed widget.

    This endpoint allows users to report problematic statements directly
    from embedded discussions on partner sites.

    Request Body:
        statement_id (required): ID of the statement to flag
        flag_reason (required): Reason for flagging (spam, harassment, misinformation, off_topic)
        ref (optional): Partner reference for tracking

    Returns:
        201: Flag recorded successfully
        400: Invalid request
        404: Statement not found
        409: Already flagged (from same session)

    Example:
        POST /api/embed/flag
        {"statement_id": 123, "flag_reason": "spam"}
    """
    # Validate request origin against partner allowlist
    origin = request.headers.get('Origin')
    if not origin:
        return api_error('origin_required', 'Origin header is required for embed flagging.', 403)
    if not is_partner_origin_allowed(origin):
        current_app.logger.warning(f"Embed flag rejected: origin {origin} not in allowlist")
        return api_error('origin_not_allowed', 'Origin not allowed.', 403)

    data = request.get_json()
    if not data:
        return api_error('invalid_request', 'Request body must be valid JSON.', 400)

    statement_id = data.get('statement_id')
    flag_reason = data.get('flag_reason')
    partner_ref = data.get('ref', '')

    # Reject flags from disabled partner refs (kill switch)
    ref_str = sanitize_partner_ref(partner_ref)
    if ref_str and partner_ref_is_disabled(ref_str):
        return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    if not statement_id:
        return api_error('missing_statement_id', 'The statement_id field is required.', 400)

    valid_reasons = ['spam', 'harassment', 'misinformation', 'off_topic']
    if not flag_reason or flag_reason not in valid_reasons:
        return api_error('invalid_reason', f'flag_reason must be one of: {", ".join(valid_reasons)}', 400)

    # Find the statement
    statement = db.session.get(Statement, statement_id)
    if not statement:
        return api_error('statement_not_found', 'The requested statement does not exist.', 404)

    # Get user identifier (required: at least one of user_id or session_fingerprint)
    user_id = current_user.id if current_user.is_authenticated else None
    # Prefer embed-provided fingerprint for iframe reliability (cookies may be blocked)
    embed_fingerprint = data.get('embed_fingerprint')
    if embed_fingerprint and isinstance(embed_fingerprint, str):
        from app.discussions.statements import normalize_embed_fingerprint
        session_fingerprint = normalize_embed_fingerprint(embed_fingerprint)
    else:
        session_fingerprint = get_statement_vote_fingerprint() if not user_id else None
    if not user_id and not session_fingerprint:
        return api_error(
            'identifier_required',
            'Unable to identify your session. Please ensure cookies are enabled and try again.',
            400,
        )

    # Check for existing flag from same user/session
    existing_flag = None
    if user_id:
        existing_flag = StatementFlag.query.filter_by(
            statement_id=statement_id,
            flagger_user_id=user_id
        ).first()
    elif session_fingerprint:
        existing_flag = StatementFlag.query.filter_by(
            statement_id=statement_id,
            session_fingerprint=session_fingerprint
        ).first()

    if existing_flag:
        return api_error('already_flagged', 'You have already flagged this statement.', 409)

    # Create the flag
    try:
        flag = StatementFlag(
            statement_id=statement_id,
            flagger_user_id=user_id,
            session_fingerprint=session_fingerprint,
            flag_reason=flag_reason,
            additional_context=f"Reported from embed (ref: {ref_str})" if ref_str else "Reported from embed"
        )
        db.session.add(flag)
        db.session.commit()

        # Log for monitoring
        current_app.logger.info(
            f"Embed flag: statement={statement_id}, reason={flag_reason}, "
            f"user_id={user_id}, fingerprint={session_fingerprint[:8] if session_fingerprint else None}"
        )

        # Track flag event
        track_partner_event('embed_statement_flagged', {
            'statement_id': statement_id,
            'discussion_id': statement.discussion_id,
            'flag_reason': flag_reason,
            'partner_ref': ref_str or partner_ref
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to create flag: {e}")
        return api_error('flag_failed', 'Failed to record flag. Please try again.', 500)

    return jsonify({'success': True, 'message': _('Flag recorded successfully')}), 201
