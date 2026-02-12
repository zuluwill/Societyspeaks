"""
Partner API Endpoints

Provides lookup, snapshot, and create APIs for partner embed integration.
All endpoints return JSON and use standardized error responses.
"""
import re
import html
import json
import hashlib
import secrets
from flask import Blueprint, request, jsonify, current_app
from app import db, limiter, cache, csrf
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.models import (
    Discussion, NewsArticle, DiscussionSourceArticle, ConsensusAnalysis, Statement,
    StatementFlag,
)
from app.discussions.statements import get_statement_vote_fingerprint
from app.api.errors import api_error
from app.api.utils import (
    get_rate_limit_key, get_partner_ref, build_discussion_urls, append_ref_param,
    get_discussion_participant_count, get_discussion_statement_count,
    sanitize_partner_ref, track_partner_event, record_partner_usage,
    is_partner_origin_allowed
)
from app.partner.keys import find_partner_api_key


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
    disabled_refs = current_app.config.get('DISABLED_PARTNER_REFS') or []
    if not isinstance(disabled_refs, list):
        disabled_refs = []
    if ref_normalized and ref_normalized in disabled_refs:
        return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    # Optional API key context (test/live)
    api_key = request.headers.get('X-API-Key')
    if api_key:
        is_valid, partner_id, key_env, partner = _validate_api_key()
        if not is_valid:
            return api_error('invalid_api_key', 'Invalid X-API-Key.', 401)
    else:
        partner_id = None
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
    cache_key = f"lookup:{key_env}:{partner_id or 'public'}:{normalized}"
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

    if key_env == 'test' and partner_id:
        discussion = Discussion.query.filter_by(
            partner_article_url=normalized,
            partner_id=partner_id,
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
            if partner_id:
                query = query.filter_by(partner_id=partner_id)
            discussion = query.first()
            if discussion:
                source = 'partner'

    if not discussion:
        return api_error('no_discussion', 'No discussion found for this article URL.', 404)

    # Note: Discussions don't have is_deleted flag; they are hard-deleted
    # If we need soft-delete in future, add is_deleted column to Discussion model

    # Build response
    urls = build_discussion_urls(discussion, include_ref=False)
    response_data = {
        'discussion_id': discussion.id,
        'slug': discussion.slug,
        'title': discussion.title,
        'embed_url': urls['embed_url'],
        'consensus_url': urls['consensus_url'],
        'snapshot_url': urls['snapshot_url'],
        'source': source,
        'env': discussion.partner_env
    }

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
    if partner_id:
        record_partner_usage(partner_id, key_env, 'lookup')

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
    disabled_refs = current_app.config.get('DISABLED_PARTNER_REFS') or []
    if not isinstance(disabled_refs, list):
        disabled_refs = []
    if ref_normalized and ref_normalized in disabled_refs:
        return api_error('partner_disabled', 'Embed and API access has been revoked for this partner.', 403)

    # Try cache first
    cache_key = f"snapshot:{discussion_id}"
    cached = cache.get(cache_key)
    if cached:
        response_data = cached
        if ref_normalized:
            response_data = dict(cached)
            response_data['consensus_url'] = append_ref_param(response_data['consensus_url'], ref_normalized)
        return jsonify(response_data)

    # Load discussion
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        return api_error('discussion_not_found', 'The requested discussion does not exist.', 404)

    # Restrict test discussions to valid test keys for the owning partner
    if discussion.partner_env == 'test':
        is_valid, partner_id, key_env, _partner = _validate_api_key()
        if not is_valid or key_env != 'test' or partner_id != discussion.partner_id:
            return api_error('forbidden', 'A valid test API key is required for this discussion.', 403)

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
    cache.set(cache_key, response_data, timeout=600)

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
        tuple: (is_valid, partner_id, env, partner)
    """
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False, None, None, None

    record, partner, env = find_partner_api_key(api_key)
    if record and partner:
        return True, partner.slug, env, partner

    # Legacy config keys (default to live)
    api_keys = current_app.config.get('PARTNER_API_KEYS', {})
    if api_key in api_keys:
        return True, api_keys[api_key], 'live', None

    return False, None, None, None


def _normalize_idempotency_key(raw_key):
    if not raw_key or not isinstance(raw_key, str):
        return None
    cleaned = raw_key.strip()
    if not cleaned:
        return None
    return cleaned[:128]


def _idempotency_cache_key(partner_id, key_env, idempotency_key):
    return f"idempotency:create:{key_env}:{partner_id}:{idempotency_key}"


def _request_payload_hash(data):
    payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


@partner_bp.route('/partner/discussions', methods=['POST'])
@limiter.limit("30 per hour", key_func=_get_api_key_rate_limit_key)
def create_discussion():
    """
    Create a new discussion for a partner article.

    This endpoint allows partners to create discussions for articles
    that are not ingested via RSS. Requires API key authentication.

    Headers:
        X-API-Key (required): Partner API key
        Content-Type: application/json

    Request Body:
        article_url (required): The article URL (will be normalized)
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

    # Enforce server-to-server usage for API key protected writes.
    # Browser requests with Origin should not send secret API keys.
    request_origin = request.headers.get('Origin')
    if request_origin:
        return api_error(
            'browser_not_allowed',
            'Create Discussion must be called server-to-server (no browser Origin header).',
            403
        )

    # Validate API key
    is_valid, partner_id, key_env, partner = _validate_api_key()
    if not is_valid:
        return api_error(
            'invalid_api_key',
            'A valid X-API-Key header is required.',
            401
        )

    if key_env == 'live' and partner and partner.billing_status != 'active':
        return api_error(
            'billing_inactive',
            'Live API access requires an active subscription.',
            402
        )
    if partner and partner.status != 'active':
        return api_error(
            'partner_inactive',
            'Partner account is not active.',
            403
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
        idempotency_cache_key = _idempotency_cache_key(partner_id, key_env, idempotency_key)
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
    title = data.get('title')

    if not article_url:
        return api_error('missing_article_url', 'The article_url field is required.', 400)

    if not title:
        return api_error('missing_title', 'The title field is required.', 400)

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

    # Normalize URL
    normalized_url = normalize_url(article_url)
    if not normalized_url:
        return api_error(
            'invalid_url',
            'The provided article_url is not valid or could not be parsed.',
            400
        )

    # Check if discussion already exists for this URL
    existing = Discussion.query.filter_by(
        partner_article_url=normalized_url,
        partner_id=partner_id,
        partner_env=key_env
    ).first()
    if existing:
        return api_error(
            'discussion_exists',
            f'A discussion already exists for this URL (id: {existing.id}).',
            409
        )

    # Also check NewsArticle path (normalized_url + raw url fallback)
    if key_env == 'live':
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
        # Validate provided statements
        valid_positions = ['pro', 'con', 'neutral']
        for i, stmt in enumerate(seed_statements):
            if not isinstance(stmt, dict) or 'content' not in stmt:
                return api_error(
                    'invalid_statement',
                    f'Statement at index {i} must have a content field.',
                    400
                )
            content = stmt.get('content', '').strip()
            if not content or len(content) < 10:
                return api_error(
                    'invalid_statement',
                    f'Statement at index {i} content must be at least 10 characters.',
                    400
                )
            position = stmt.get('position', 'neutral').lower()
            if position not in valid_positions:
                position = 'neutral'
            statements_to_create.append({
                'content': content[:500],  # Max 500 chars
                'position': position
            })
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
            current_app.logger.error(f"Seed generation failed for partner {partner_id}: {e}")
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
                title=title[:200],  # Max 200 chars per model
                description=excerpt[:500] if excerpt else None,
                slug=unique_slug,
                has_native_statements=True,
                geographic_scope='global',
                partner_article_url=normalized_url,
                partner_id=partner_id,
                partner_fk_id=partner.id if partner else None,
                partner_env=key_env
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
                )
                db.session.add(statement)

            db.session.commit()

            current_app.logger.info(
                f"Partner {partner_id} created discussion {discussion.id} for {normalized_url}"
            )
            break

        except IntegrityError as e:
            db.session.rollback()
            err_text = str(getattr(e, "orig", e)).lower()
            is_slug_collision = ("slug" in err_text) or ("ix_discussion_slug" in err_text) or ("discussion.slug" in err_text)
            if not is_slug_collision:
                current_app.logger.error(
                    "Failed to create partner discussion due to non-slug integrity error for partner %s: %s",
                    partner_id,
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
                    partner_id,
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
    urls = build_discussion_urls(discussion, include_ref=False)
    response_data = {
        'discussion_id': discussion.id,
        'slug': discussion.slug,
        'title': discussion.title,
        'embed_url': urls['embed_url'],
        'consensus_url': urls['consensus_url'],
        'snapshot_url': urls['snapshot_url'],
        'source': 'partner',
        'env': discussion.partner_env,
        'statement_count': len(statements_to_create)
    }

    # Track create API event
    track_partner_event('partner_api_create', {
        'discussion_id': discussion.id,
        'partner_id': partner_id,
        'statement_count': len(statements_to_create),
        'used_ai_generation': not bool(seed_statements)
    })
    record_partner_usage(partner_id, key_env, 'create')

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
@csrf.exempt
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
    disabled_refs = current_app.config.get('DISABLED_PARTNER_REFS') or []
    if not isinstance(disabled_refs, list):
        disabled_refs = []
    if ref_str and ref_str in disabled_refs:
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

    return jsonify({'success': True, 'message': 'Flag recorded successfully'}), 201
