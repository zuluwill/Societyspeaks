# app/discussions/statements.py
"""
Routes for Native Statement System (Phase 1)

Adapted from pol.is patterns with Society Speaks enhancements
"""
from flask import abort, render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app, session
from flask_login import login_required, current_user
from app import db, limiter, csrf, cache
from app.db_retry import with_db_retry
from app.discussions.statement_forms import StatementForm, VoteForm, ResponseForm, FlagStatementForm
from app.models import Discussion, Statement, StatementVote, Response, StatementFlag, DiscussionParticipant
from app.email_utils import create_discussion_notification
from app.discussions.follower_notifications import notify_discussion_followers
from app.programmes.permissions import can_view_programme
from app.programmes.utils import validate_cohort_for_discussion
from app.discussions.sorting import apply_statement_sort
from app.analytics.events import record_event
from app.lib.counter_utils import increment_counter
from sqlalchemy import func, desc, or_, text
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
import hashlib
import re
import secrets
import json
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import validate_csrf, CSRFError
from wtforms import ValidationError as WTFormsValidationError
try:
    import posthog
except ImportError:
    posthog = None

statements_bp = Blueprint('statements', __name__)

STATEMENT_CLIENT_COOKIE_NAME = 'statement_client_id'
STATEMENT_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
EMBED_FINGERPRINT_MAX_LENGTH = 128


def _enforce_programme_visibility_for_discussion(discussion):
    if discussion and discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)


def _notify_discussion_owner_about_response_activity(discussion, actor_user_id=None, response_count=None):
    if not discussion or not discussion.creator_id:
        return
    if actor_user_id and discussion.creator_id == actor_user_id:
        return
    create_discussion_notification(
        user_id=discussion.creator_id,
        discussion_id=discussion.id,
        notification_type='new_response',
        additional_data={'response_count': response_count or 0},
    )
    notify_discussion_followers(
        discussion,
        'new_response',
        actor_user_id=actor_user_id,
        skip_discussion_creator=True,
        cooldown_hours=4,
    )


def _apply_vote_counter_delta(statement_id, old_vote, new_vote):
    """
    Atomically update statement vote counters using SQL delta arithmetic.

    Replaces Python read-modify-write (race-prone) with a single SQL UPDATE.
    Returns a Row with (vote_count_agree, vote_count_disagree, vote_count_unsure)
    from RETURNING so the caller can refresh the in-memory object without a
    second SELECT. Returns None when old_vote == new_vote (no counter change).
    """
    agree_delta = disagree_delta = unsure_delta = 0
    if old_vote == 1:
        agree_delta -= 1
    elif old_vote == -1:
        disagree_delta -= 1
    elif old_vote == 0:
        unsure_delta -= 1
    if new_vote == 1:
        agree_delta += 1
    elif new_vote == -1:
        disagree_delta += 1
    elif new_vote == 0:
        unsure_delta += 1
    if agree_delta == 0 and disagree_delta == 0 and unsure_delta == 0:
        return None
    return db.session.execute(text("""
        UPDATE statement
        SET
            vote_count_agree    = GREATEST(0, vote_count_agree    + :agree_delta),
            vote_count_disagree = GREATEST(0, vote_count_disagree + :disagree_delta),
            vote_count_unsure   = GREATEST(0, vote_count_unsure   + :unsure_delta)
        WHERE id = :statement_id
        RETURNING vote_count_agree, vote_count_disagree, vote_count_unsure
    """), {
        'agree_delta': agree_delta,
        'disagree_delta': disagree_delta,
        'unsure_delta': unsure_delta,
        'statement_id': statement_id,
    }).fetchone()


def _lock_vote_identity(statement_id, user_id=None, session_fingerprint=None):
    """
    Acquire a transaction-scoped advisory lock for one vote identity.

    This serializes concurrent updates for the same `(statement_id, voter)` key
    in Postgres, preventing race windows where two requests compute deltas from
    stale old_vote values.
    """
    bind = db.session.get_bind()
    if not bind or bind.dialect.name != 'postgresql':
        return

    if user_id is not None:
        key = f"vote:{statement_id}:u:{user_id}"
    else:
        key = f"vote:{statement_id}:a:{session_fingerprint or ''}"

    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": key}
    )


def _upsert_statement_vote_row(
    statement_id,
    discussion_id,
    vote_value,
    confidence,
    partner_ref,
    cohort_slug,
    user_id=None,
    session_fingerprint=None
):
    """
    Persist vote row via INSERT ... ON CONFLICT ... DO UPDATE.
    """
    bind = db.session.get_bind()
    dialect_name = bind.dialect.name if bind else ''

    if dialect_name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect_name == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        raise RuntimeError(f"Unsupported database dialect for vote upsert: {dialect_name}")

    now = utcnow_naive()
    insert_values = {
        'statement_id': statement_id,
        'discussion_id': discussion_id,
        'vote': vote_value,
        'confidence': confidence,
        'partner_ref': partner_ref,
        'cohort_slug': cohort_slug,
        # created_at must be set explicitly: raw dialect insert() does not
        # trigger SQLAlchemy ORM column defaults, so omitting it produces NULL.
        'created_at': now,
        'updated_at': now,
    }
    if user_id is not None:
        insert_values['user_id'] = user_id
    else:
        insert_values['session_fingerprint'] = session_fingerprint

    stmt = dialect_insert(StatementVote).values(**insert_values)
    set_values = {
        'vote': vote_value,
        'confidence': confidence,
        'partner_ref': partner_ref,
        'cohort_slug': cohort_slug,
        'updated_at': now,
    }

    if user_id is not None:
        stmt = stmt.on_conflict_do_update(
            index_elements=[StatementVote.statement_id, StatementVote.user_id],
            index_where=StatementVote.user_id.isnot(None),
            set_=set_values
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=[StatementVote.statement_id, StatementVote.session_fingerprint],
            index_where=StatementVote.session_fingerprint.isnot(None),
            set_=set_values
        )

    db.session.execute(stmt)


def _persist_vote_with_upsert(
    statement,
    vote_value,
    confidence,
    partner_ref,
    cohort_slug,
    user_id=None,
    session_fingerprint=None
):
    """
    Persist vote and update denormalized counters in one transaction.
    """
    _lock_vote_identity(
        statement_id=statement.id,
        user_id=user_id,
        session_fingerprint=session_fingerprint
    )

    vote_lookup = StatementVote.query.filter(StatementVote.statement_id == statement.id)
    if user_id is not None:
        vote_lookup = vote_lookup.filter(StatementVote.user_id == user_id)
    else:
        vote_lookup = vote_lookup.filter(StatementVote.session_fingerprint == session_fingerprint)

    existing_vote = vote_lookup.with_entities(StatementVote.vote).first()
    old_vote = existing_vote[0] if existing_vote else None

    _upsert_statement_vote_row(
        statement_id=statement.id,
        discussion_id=statement.discussion_id,
        vote_value=vote_value,
        confidence=confidence,
        partner_ref=partner_ref,
        cohort_slug=cohort_slug,
        user_id=user_id,
        session_fingerprint=session_fingerprint
    )

    counts = _apply_vote_counter_delta(statement.id, old_vote, vote_value)
    db.session.commit()
    if counts:
        statement.vote_count_agree = counts[0]
        statement.vote_count_disagree = counts[1]
        statement.vote_count_unsure = counts[2]


def calculate_wilson_score(agree, disagree, confidence=0.95):
    """
    Wilson score confidence interval for statement ranking
    Better than simple ratio for sparse data
    """
    from math import sqrt
    try:
        from scipy import stats
        n = agree + disagree
        if n == 0:
            return 0
        
        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        phat = agree / n
        
        return (phat + z*z/(2*n) - z * sqrt((phat*(1-phat)+z*z/(4*n))/n))/(1+z*z/n)
    except ImportError:
        # Fallback if scipy not available
        n = agree + disagree
        if n == 0:
            return 0
        return agree / n


def get_user_identifier():
    """
    Get identifier for current user (authenticated or anonymous)
    
    Returns dict with:
    - user_id: ID if authenticated, None if anonymous
    - session_fingerprint: Cookie-based fingerprint for anonymous tracking
    
    Uses long-lived cookie for anonymous users to prevent fingerprint collisions
    when multiple users share the same network/browser type.
    """
    if current_user.is_authenticated:
        return {
            'user_id': current_user.id,
            'session_fingerprint': None
        }
    else:
        client_id, _ = get_or_create_statement_client_id()
        fingerprint = hashlib.sha256(client_id.encode()).hexdigest()
        
        if session.get('fingerprint') != fingerprint:
            session['fingerprint'] = fingerprint
            session.modified = True
        
        return {
            'user_id': None,
            'session_fingerprint': fingerprint
        }


def embed_statement_submissions_allowed(discussion):
    """Whether reader statement submissions are allowed directly from embed."""
    return bool(getattr(discussion, 'embed_statement_submissions_enabled', False))


def check_statement_rate_limit(identifier):
    """
    Check if user has exceeded statement rate limit.

    Rate limits (per hour):
    - Anonymous users: 5 statements
    - Authenticated users: 10 statements

    Primary path: Redis INCR with ~1-hour TTL — atomic, no DB query.
    Fallback path: DB COUNT (original behaviour) if Redis is unavailable.

    Returns: (allowed: bool, remaining: int, message: str)
    """
    if identifier['user_id']:
        rate_limit = 10
        actor_key = f"u:{identifier['user_id']}"
    else:
        rate_limit = 5
        actor_key = f"a:{(identifier['session_fingerprint'] or '')[:16]}"

    now = utcnow_naive()
    hour_bucket = now.strftime('%Y%m%d%H')
    redis_key = f"stmt_rl:{actor_key}:{hour_bucket}"

    try:
        from datetime import timedelta as _td
        from app.lib.counter_utils import _get_redis_client as _get_rl_redis
        rl_redis = _get_rl_redis()
        if rl_redis is not None:
            # Increment current bucket and read previous bucket in one pipeline.
            # Summing both prevents the boundary exploit where a user posts at
            # HH:59:59 and again at (HH+1):00:00 for 2x the limit in ~1 second.
            prev_bucket = (now - _td(hours=1)).strftime('%Y%m%d%H')
            prev_key = f"stmt_rl:{actor_key}:{prev_bucket}"
            pipe = rl_redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 3601)
            pipe.get(prev_key)
            results = pipe.execute()
            current_count = int(results[0])
            prev_count = int(results[2] or 0)
            # Weight previous bucket by how far we are into the current hour.
            minutes_into_hour = now.minute + now.second / 60.0
            prev_weight = max(0.0, 1.0 - minutes_into_hour / 60.0)
            weighted_count = current_count + int(prev_count * prev_weight)
            remaining = max(0, rate_limit - weighted_count)
            allowed = weighted_count <= rate_limit
            if not allowed:
                user_type = "logged-in users" if identifier['user_id'] else "anonymous users"
                message = f"Rate limit exceeded. {user_type.capitalize()} can post {rate_limit} statements per hour. Please try again later."
            else:
                message = None
            return allowed, remaining, message
        # Redis client unavailable — fall through to DB
    except Exception:
        pass

    # Fallback: DB COUNT when Redis is unavailable
    one_hour_ago = utcnow_naive() - timedelta(hours=1)
    if identifier['user_id']:
        recent_count = Statement.query.filter(
            Statement.user_id == identifier['user_id'],
            Statement.created_at > one_hour_ago
        ).count()
    else:
        recent_count = Statement.query.filter(
            Statement.session_fingerprint == identifier['session_fingerprint'],
            Statement.created_at > one_hour_ago
        ).count()

    remaining = max(0, rate_limit - recent_count)
    allowed = recent_count < rate_limit
    if not allowed:
        user_type = "logged-in users" if identifier['user_id'] else "anonymous users"
        message = f"Rate limit exceeded. {user_type.capitalize()} can post {rate_limit} statements per hour. Please try again later."
    else:
        message = None
    return allowed, remaining, message


@statements_bp.route('/discussions/<int:discussion_id>/statements/create', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # Removed @login_required to allow anonymous statements like pol.is
def create_statement(discussion_id):
    """Create a new statement in a native discussion (authenticated or anonymous)"""
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    if not discussion.has_native_statements:
        flash("This discussion does not support native statements", "error")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Get user identifier (authenticated or anonymous)
    identifier = get_user_identifier()

    form = StatementForm()
    
    if form.validate_on_submit():
        # Check rate limits only on POST — the Redis path increments a counter,
        # so calling it on GET would burn slots every time the form page is viewed.
        allowed, remaining, rate_message = check_statement_rate_limit(identifier)
        if not allowed:
            flash(rate_message, "error")
            return redirect(url_for('discussions.view_discussion',
                                  discussion_id=discussion.id,
                                  slug=discussion.slug))
        max_statements = current_app.config.get('MAX_STATEMENTS_PER_DISCUSSION', 5000)
        current_statement_count = Statement.query.filter_by(
            discussion_id=discussion_id,
            is_deleted=False
        ).count()
        if current_statement_count >= max_statements:
            flash(
                "This discussion has reached the statement limit. New submissions are paused while moderation and analysis catch up.",
                "warning"
            )
            return redirect(url_for(
                'discussions.view_discussion',
                discussion_id=discussion.id,
                slug=discussion.slug
            ))

        # Check for duplicate content (pol.is pattern)
        existing = Statement.query.filter_by(
            discussion_id=discussion_id,
            content=form.content.data.strip()
        ).first()
        
        if existing:
            flash("This statement already exists in the discussion", "warning")
            return redirect(url_for('statements.view_statement', statement_id=existing.id))
        
        # Phase 4.4: Semantic deduplication (optional, only for authenticated users with LLM)
        from app.models import UserAPIKey
        has_llm = False
        if current_user.is_authenticated:
            has_llm = UserAPIKey.query.filter_by(
                user_id=current_user.id,
                is_active=True
            ).first() is not None
        
        if has_llm and current_user.is_authenticated:
            try:
                from app.lib.llm_utils import find_duplicate_statements
                
                # Get recent statements for comparison
                recent_statements = Statement.query.filter_by(
                    discussion_id=discussion_id,
                    is_deleted=False
                ).order_by(Statement.created_at.desc()).limit(50).all()
                
                statement_dicts = [{'id': s.id, 'content': s.content} for s in recent_statements]
                
                # Check for semantic duplicates
                similar = find_duplicate_statements(
                    new_statement=form.content.data.strip(),
                    existing_statements=statement_dicts,
                    threshold=0.9,
                    user_id=current_user.id,
                    db=db
                )
                
                if similar and len(similar) > 0:
                    similar_stmt = None
                    for candidate in similar:
                        s = db.session.get(Statement, candidate['id'])
                        if s and not s.is_deleted:
                            similar_stmt = s
                            break
                    if similar_stmt:
                        flash(f"A similar statement already exists: '{similar_stmt.content}'. Consider voting on it instead.", "info")
                        return redirect(url_for('statements.view_statement', statement_id=similar_stmt.id))
            
            except Exception as e:
                # Don't block statement creation if deduplication fails
                current_app.logger.warning(f"Semantic deduplication failed: {e}")
        
        # Create new statement (authenticated or anonymous)
        statement = Statement(
            discussion_id=discussion_id,
            user_id=identifier['user_id'],
            session_fingerprint=identifier['session_fingerprint'],
            content=form.content.data.strip(),
            statement_type=form.statement_type.data,
            source='user_submitted'  # Track origin for §13 AI Attribution
        )
        
        db.session.add(statement)
        db.session.commit()
        from app.api.utils import invalidate_partner_snapshot_cache
        invalidate_partner_snapshot_cache(discussion_id)
        _notify_discussion_owner_about_response_activity(
            discussion,
            actor_user_id=identifier['user_id'],
        )
        
        # Track statement creation with PostHog
        if posthog and getattr(posthog, 'project_api_key', None):
            try:
                distinct_id = str(identifier['user_id']) if identifier['user_id'] else identifier['session_fingerprint']
                posthog.capture(
                    distinct_id=distinct_id,
                    event='statement_created',
                    properties={
                        'discussion_id': discussion_id,
                        'statement_id': statement.id,
                        'statement_type': form.statement_type.data,
                        'is_authenticated': identifier['user_id'] is not None
                    }
                )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")
        
        flash("Statement posted successfully!", "success")
        
        # For anonymous users, show upgrade prompt
        if not current_user.is_authenticated:
            flash("💡 Create a free account to add detailed responses, link evidence, and track your contributions!", "info")
        
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    return render_template('discussions/create_statement.html', 
                         form=form, 
                         discussion=discussion)


@statements_bp.route('/api/embed/discussions/<int:discussion_id>/statements', methods=['POST'])
@csrf.exempt
@limiter.limit("20 per hour", key_func=get_remote_address)
def create_statement_from_embed(discussion_id):
    """Create a reader-submitted statement from embed when the discussion policy allows it."""
    is_embed_request = request.headers.get('X-Embed-Request', '').lower() in ('1', 'true', 'yes')
    if not is_embed_request:
        return jsonify({'success': False, 'error': 'embed_request_required'}), 400

    discussion = db.get_or_404(Discussion, discussion_id)
    _enforce_programme_visibility_for_discussion(discussion)

    if not discussion.has_native_statements:
        return jsonify({'success': False, 'error': 'native_statements_disabled'}), 400
    if discussion.is_closed:
        return jsonify({'success': False, 'error': 'discussion_closed'}), 403
    if not embed_statement_submissions_allowed(discussion):
        return jsonify({'success': False, 'error': 'embed_statement_submissions_disabled'}), 403

    if discussion.partner_fk_id or discussion.partner_id:
        from app.api.utils import is_partner_origin_allowed
        origin = request.headers.get('Origin')
        if origin and not is_partner_origin_allowed(origin, env=discussion.partner_env):
            return jsonify({'success': False, 'error': 'origin_not_allowed'}), 403

    partner_ref = extract_partner_ref_from_request()
    from app.api.utils import partner_ref_is_disabled
    if partner_ref and partner_ref_is_disabled(partner_ref):
        return jsonify({'success': False, 'error': 'partner_disabled'}), 403

    payload = request.get_json(silent=True) if request.is_json else request.form
    content = ((payload or {}).get('content') or '').strip()
    statement_type = ((payload or {}).get('statement_type') or 'claim').strip().lower()
    if statement_type not in ('claim', 'question'):
        statement_type = 'claim'

    if len(content) < 10:
        return jsonify({
            'success': False,
            'error': 'invalid_content',
            'message': 'Statement must be at least 10 characters.',
        }), 400
    if len(content) > 500:
        return jsonify({
            'success': False,
            'error': 'invalid_content',
            'message': 'Statement must be 500 characters or fewer.',
        }), 400

    # Identifier mirrors vote handling so anonymous embeds remain deduplicated/rate-limited.
    if current_user.is_authenticated:
        identifier = {'user_id': current_user.id, 'session_fingerprint': None}
    else:
        embed_fingerprint = extract_embed_fingerprint_from_request() or get_statement_vote_fingerprint()
        identifier = {'user_id': None, 'session_fingerprint': embed_fingerprint}

    allowed, _, rate_message = check_statement_rate_limit(identifier)
    if not allowed:
        return jsonify({
            'success': False,
            'error': 'rate_limited',
            'message': rate_message or 'Rate limit exceeded.',
        }), 429

    max_statements = current_app.config.get('MAX_STATEMENTS_PER_DISCUSSION', 5000)
    current_statement_count = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    ).count()
    if current_statement_count >= max_statements:
        return jsonify({
            'success': False,
            'error': 'statement_limit_reached',
            'message': 'This discussion has reached its statement limit.',
        }), 429

    existing = Statement.query.filter_by(
        discussion_id=discussion_id,
        content=content,
        is_deleted=False
    ).first()
    if existing:
        return jsonify({
            'success': False,
            'error': 'duplicate_statement',
            'statement_id': existing.id,
            'message': 'This statement already exists in the discussion.',
        }), 409

    statement = Statement(
        discussion_id=discussion_id,
        user_id=identifier['user_id'],
        session_fingerprint=identifier['session_fingerprint'],
        content=content,
        statement_type=statement_type,
        source='user_submitted'
    )
    db.session.add(statement)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'duplicate_statement',
            'message': 'This statement already exists in the discussion.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("create_statement_from_embed failed")
        return jsonify({
            'success': False,
            'error': 'statement_create_failed',
            'message': 'Could not submit statement at this time.',
        }), 500

    from app.api.utils import invalidate_partner_snapshot_cache
    invalidate_partner_snapshot_cache(discussion_id)
    _notify_discussion_owner_about_response_activity(
        discussion,
        actor_user_id=identifier['user_id'],
    )

    return jsonify({
        'success': True,
        'statement_id': statement.id,
        'message': 'Statement submitted.',
    }), 201


def get_or_create_statement_client_id():
    """Get the long-lived client ID from cookie, or generate a new one.
    
    Returns a tuple of (client_id, is_new) where is_new indicates if we need to set the cookie.
    """
    client_id = request.cookies.get(STATEMENT_CLIENT_COOKIE_NAME)
    if client_id and len(client_id) == 64:
        return client_id, False
    new_id = secrets.token_hex(32)
    return new_id, True


def get_statement_vote_fingerprint():
    """Generate a unique fingerprint for anonymous statement voters.
    
    Uses a long-lived client ID cookie as the primary identifier to survive session restarts.
    This prevents both:
    1. Fingerprint collisions (multiple users getting the same fingerprint)
    2. Easy vote duplication (clearing session cookies to vote again)
    
    The client ID is stored in a separate long-lived cookie that persists for 1 year.
    """
    client_id, _ = get_or_create_statement_client_id()
    fingerprint = hashlib.sha256(client_id.encode()).hexdigest()
    
    if session.get('statement_vote_fingerprint') != fingerprint:
        session['statement_vote_fingerprint'] = fingerprint
        session.modified = True
    
    return fingerprint


def normalize_embed_fingerprint(value):
    """Normalize and hash an embed-provided fingerprint for anonymous tracking."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > EMBED_FINGERPRINT_MAX_LENGTH:
        cleaned = cleaned[:EMBED_FINGERPRINT_MAX_LENGTH]
    return hashlib.sha256(cleaned.encode()).hexdigest()


def extract_partner_ref_from_request():
    """Extract partner ref from query params, JSON body, or form."""
    ref = request.args.get('ref', '')
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict) and data.get('ref'):
            ref = data.get('ref')
    else:
        form_ref = request.form.get('ref')
        if form_ref:
            ref = form_ref
    from app.api.utils import sanitize_partner_ref
    return sanitize_partner_ref(ref)


def extract_embed_fingerprint_from_request():
    """Extract embed fingerprint from JSON body or form."""
    value = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            value = data.get('embed_fingerprint')
    else:
        value = request.form.get('embed_fingerprint')
    return normalize_embed_fingerprint(value)


def get_vote_rate_limit_key():
    """Rate limit key by IP + ref + optional embed fingerprint."""
    ip = get_remote_address()
    ref = extract_partner_ref_from_request() or 'unknown'
    embed_fp = extract_embed_fingerprint_from_request()
    if embed_fp:
        return f"{ip}:{ref}:{embed_fp[:12]}"
    return f"{ip}:{ref}"


def set_statement_client_id_cookie_if_needed(response):
    """Set the long-lived client ID cookie if it doesn't exist."""
    client_id, is_new = get_or_create_statement_client_id()
    if is_new:
        response.set_cookie(
            STATEMENT_CLIENT_COOKIE_NAME,
            client_id,
            max_age=STATEMENT_CLIENT_COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite='Lax'
        )
    return response


@statements_bp.after_request
def after_request_set_statement_cookie(response):
    """Automatically set the long-lived client ID cookie on all statement blueprint responses."""
    if not current_user.is_authenticated:
        return set_statement_client_id_cookie_if_needed(response)
    return response


_VOTE_RL_CACHE_MISS = '__vote_rl_miss__'


def get_vote_rate_limit():
    """
    Dynamic vote rate limit by route context and partner class.

    Results are cached for 60 seconds so the DB is not queried on every vote request.
    Cache miss sentinel (_VOTE_RL_CACHE_MISS) distinguishes "not found" from None.

    Priority:
    1) Integrity-mode discussions -> strict cap
    2) Partner tier-specific cap (if partner ref resolves to active partner)
    3) Default public cap
    """
    default_limit = current_app.config.get('VOTE_RATE_LIMIT_DEFAULT', '30 per minute')
    integrity_limit = current_app.config.get('VOTE_RATE_LIMIT_INTEGRITY', '10 per minute')
    tier_limits = current_app.config.get('VOTE_RATE_LIMIT_BY_PARTNER_TIER') or {
        'free': '30 per minute',
        'starter': '45 per minute',
        'professional': '60 per minute',
        'enterprise': '90 per minute',
    }

    statement_id = request.view_args.get('statement_id') if request.view_args else None
    if statement_id:
        stmt_cache_key = f"vote_rl_limit:stmt:{statement_id}"
        try:
            cached = cache.get(stmt_cache_key)
            if cached is not None:
                if cached != _VOTE_RL_CACHE_MISS:
                    return cached
            else:
                statement = db.session.get(Statement, statement_id)
                if statement and statement.discussion and statement.discussion.integrity_mode:
                    cache.set(stmt_cache_key, integrity_limit, timeout=60)
                    return integrity_limit
                cache.set(stmt_cache_key, _VOTE_RL_CACHE_MISS, timeout=60)
        except Exception:
            statement = db.session.get(Statement, statement_id)
            if statement and statement.discussion and statement.discussion.integrity_mode:
                return integrity_limit

    ref = extract_partner_ref_from_request()
    if not ref:
        return default_limit

    partner_cache_key = f"vote_rl_limit:partner:{ref}"
    try:
        cached = cache.get(partner_cache_key)
        if cached is not None:
            if cached != _VOTE_RL_CACHE_MISS:
                return cached
        else:
            from app.models import Partner
            partner = Partner.query.filter_by(slug=ref, status='active').first()
            if partner and partner.tier in tier_limits:
                limit = tier_limits[partner.tier]
                cache.set(partner_cache_key, limit, timeout=60)
                return limit
            cache.set(partner_cache_key, _VOTE_RL_CACHE_MISS, timeout=60)
    except Exception as e:
        current_app.logger.debug(f"Could not resolve partner tier for vote rate limit: {e}")

    return default_limit


def _normalize_idempotency_key(value):
    """Normalize optional idempotency key for write dedupe."""
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    # Keep bounded key size to avoid unbounded cache key expansion.
    return normalized[:128]


def _vote_request_hash(vote_value, confidence, partner_ref, cohort_slug):
    payload = json.dumps(
        {
            'vote': vote_value,
            'confidence': confidence,
            'ref': partner_ref or '',
            'cohort': cohort_slug or ''
        },
        sort_keys=True,
        separators=(',', ':')
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _safe_cache_increment(key, timeout=3600):
    """Increment counter using atomic Redis when available."""
    return increment_counter(key, ttl_seconds=timeout, fallback_cache=cache)


def _record_vote_anomaly_signals(discussion_id, session_fingerprint=None):
    """
    Record vote burst/collision telemetry using short-lived cache counters.
    """
    ip = get_remote_address() or 'unknown'
    now = utcnow_naive()
    minute_bucket = now.strftime('%Y%m%d%H%M')
    day_bucket = now.strftime('%Y%m%d')

    ip_threshold = int(current_app.config.get('VOTE_ANOMALY_IP_PER_MINUTE_THRESHOLD', 60))
    collision_threshold = int(current_app.config.get('FINGERPRINT_COLLISION_DISCUSSIONS_PER_DAY_THRESHOLD', 15))

    ip_key = f"vote_anomaly:ip:{minute_bucket}:{ip}"
    ip_count = _safe_cache_increment(ip_key, timeout=120)
    if ip_count and ip_count >= ip_threshold:
        current_app.logger.warning(
            f"Vote anomaly: high IP velocity detected ip={ip} count={ip_count}/min discussion={discussion_id}"
        )

    if not session_fingerprint:
        return

    fp_prefix = session_fingerprint[:16]
    fp_minute_key = f"vote_anomaly:fingerprint:{minute_bucket}:{fp_prefix}"
    fp_count = _safe_cache_increment(fp_minute_key, timeout=120)
    if fp_count and fp_count >= ip_threshold:
        current_app.logger.warning(
            f"Vote anomaly: high fingerprint velocity detected fp={fp_prefix} count={fp_count}/min discussion={discussion_id}"
        )

    # Collision telemetry: approximate "distinct discussions per fingerprint/day"
    marker_key = f"vote_collision:marker:{day_bucket}:{fp_prefix}:{discussion_id}"
    try:
        already_seen = cache.get(marker_key)
        if not already_seen:
            cache.set(marker_key, 1, timeout=2 * 24 * 3600)
            distinct_key = f"vote_collision:distinct_discussions:{day_bucket}:{fp_prefix}"
            distinct_count = _safe_cache_increment(distinct_key, timeout=2 * 24 * 3600)
            if distinct_count and distinct_count >= collision_threshold:
                current_app.logger.warning(
                    f"Fingerprint collision anomaly: fp={fp_prefix} touched {distinct_count} discussions/day"
                )
    except Exception:
        pass


def check_integrity_rate_limit(discussion, user_identifier):
    """
    Check stricter rate limits for discussions with integrity_mode enabled.

    Primary path: Redis INCR with 61-second TTL — one atomic operation, no DB query.
    Fallback path: DB COUNT (original behaviour) if Redis is unavailable.

    Returns: (allowed: bool, message: str or None)
    """
    if not discussion.integrity_mode:
        return True, None

    integrity_limit = int(current_app.config.get('INTEGRITY_VOTES_PER_MINUTE', 10))

    actor_key = (
        f"u:{user_identifier['user_id']}"
        if user_identifier['user_id']
        else f"a:{(user_identifier['session_fingerprint'] or '')[:16]}"
    )
    minute_bucket = utcnow_naive().strftime('%Y%m%d%H%M')
    redis_key = f"integrity_rl:{discussion.id}:{actor_key}:{minute_bucket}"

    try:
        count = increment_counter(redis_key, ttl_seconds=61, fallback_cache=cache)
        if count is not None:
            if count > integrity_limit:
                current_app.logger.warning(
                    f"Integrity rate limit triggered (Redis): discussion={discussion.id}, "
                    f"actor={actor_key}, count={count}"
                )
                return False, "Rate limit exceeded for this discussion. Please slow down."
            return True, None
    except Exception:
        pass

    # Fallback: DB COUNT when Redis is unavailable
    one_minute_ago = utcnow_naive() - timedelta(minutes=1)
    if user_identifier['user_id']:
        recent_votes = StatementVote.query.filter(
            StatementVote.user_id == user_identifier['user_id'],
            StatementVote.discussion_id == discussion.id,
            StatementVote.created_at > one_minute_ago
        ).count()
    else:
        recent_votes = StatementVote.query.filter(
            StatementVote.session_fingerprint == user_identifier['session_fingerprint'],
            StatementVote.discussion_id == discussion.id,
            StatementVote.created_at > one_minute_ago
        ).count()

    if recent_votes >= integrity_limit:
        current_app.logger.warning(
            f"Integrity rate limit triggered (DB fallback): discussion={discussion.id}, "
            f"user_id={user_identifier['user_id']}, fingerprint={user_identifier['session_fingerprint'][:8] if user_identifier['session_fingerprint'] else None}"
        )
        return False, "Rate limit exceeded for this discussion. Please slow down."

    return True, None


@statements_bp.route('/statements/<int:statement_id>/vote', methods=['POST'])
@csrf.exempt
@limiter.limit(get_vote_rate_limit, key_func=get_vote_rate_limit_key)
def vote_statement(statement_id):
    """
    Vote on a statement (agree/disagree/unsure)

    Supports both authenticated and anonymous voting (like pol.is):
    - Authenticated users: votes stored in DB with user_id
    - Anonymous users: votes stored in DB with session_fingerprint (can be merged to account later)

    Includes integrity controls for sensitive discussions (stricter rate limits).
    """
    is_form_post = not request.is_json and request.headers.get('X-Requested-With') != 'XMLHttpRequest'
    is_embed_request = request.headers.get('X-Embed-Request', '').lower() in ('1', 'true', 'yes')

    # Manual CSRF validation (embed requests are exempt)
    if not is_embed_request:
        csrf_token = (
            request.form.get('csrf_token') or
            request.headers.get('X-CSRFToken') or
            request.headers.get('X-CSRF-Token')
        )
        try:
            validate_csrf(csrf_token)
        except (CSRFError, WTFormsValidationError):
            if is_form_post:
                flash('Your session has expired. Please refresh and try again.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'csrf_failed'}), 400

    user_agent = request.headers.get('User-Agent', '').lower()
    bot_indicators = ['bot', 'crawler', 'spider', 'preview', 'fetch', 'slurp', 'mediapartners']
    if any(indicator in user_agent for indicator in bot_indicators):
        if is_form_post:
            flash('Automated requests are not allowed.', 'error')
            return redirect(url_for('statements.view_statement', statement_id=statement_id))
        return jsonify({'error': 'Automated requests not allowed'}), 403

    statement = db.get_or_404(Statement, statement_id)
    discussion = statement.discussion
    if discussion and discussion.is_closed:
        if is_form_post:
            flash('This discussion is closed and no longer accepts votes.', 'error')
            return redirect(url_for('statements.view_statement', statement_id=statement_id))
        return jsonify({'error': 'discussion_closed'}), 403
    if discussion and discussion.programme and not can_view_programme(discussion.programme, current_user):
        if is_form_post:
            flash('You do not have access to this programme discussion.', 'error')
            return redirect(url_for('main.index'))
        return jsonify({'error': 'forbidden'}), 403

    # Check integrity mode rate limits
    embed_fingerprint = extract_embed_fingerprint_from_request()
    if current_user.is_authenticated:
        user_identifier = {'user_id': current_user.id, 'session_fingerprint': None}
    else:
        user_identifier = {'user_id': None, 'session_fingerprint': embed_fingerprint or get_statement_vote_fingerprint()}
    allowed, rate_message = check_integrity_rate_limit(discussion, user_identifier)
    if not allowed:
        if is_form_post:
            flash(rate_message, 'error')
            return redirect(url_for('statements.view_statement', statement_id=statement_id))
        from app.api.errors import _retry_after_seconds
        retry_after = _retry_after_seconds(None, 60)
        resp = jsonify({'error': 'rate_limited', 'message': rate_message})
        resp.status_code = 429
        resp.headers['Retry-After'] = str(retry_after)
        return resp

    # Partner ref for attribution (from embed or query param)
    partner_ref = request.args.get('ref', '')
    cohort_slug = (request.args.get('cohort') or '').strip() or None

    if request.is_json:
        data = request.get_json()
        if data is None or 'vote' not in data:
            if is_form_post:
                flash('Vote value is required.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'bad_request', 'message': 'Vote value is required'}), 400
        try:
            vote_value = int(data.get('vote'))
        except (ValueError, TypeError):
            if is_form_post:
                flash('Invalid vote value.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'bad_request', 'message': 'Invalid vote value format'}), 400
        confidence = data.get('confidence', 3)
        try:
            confidence = int(confidence) if confidence is not None else 3
            if confidence < 1 or confidence > 5:
                confidence = 3
        except (ValueError, TypeError):
            confidence = 3
        # Override ref from JSON body if provided
        if data.get('ref'):
            partner_ref = data.get('ref')
        if data.get('embed_fingerprint'):
            embed_fingerprint = normalize_embed_fingerprint(data.get('embed_fingerprint'))
        if data.get('cohort'):
            cohort_slug = str(data.get('cohort')).strip() or None
    else:
        vote_raw = request.form.get('vote')
        if vote_raw is None or vote_raw == '':
            if is_form_post:
                flash('Vote value is required.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'bad_request', 'message': 'Vote value is required'}), 400
        try:
            vote_value = int(vote_raw)
        except (ValueError, TypeError):
            if is_form_post:
                flash('Invalid vote value.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'bad_request', 'message': 'Invalid vote value format'}), 400
        confidence_raw = request.form.get('confidence', 3)
        try:
            confidence = int(confidence_raw) if confidence_raw else 3
            if confidence < 1 or confidence > 5:
                confidence = 3
        except (ValueError, TypeError):
            confidence = 3
        # Check form for ref if not in query params
        if not partner_ref and request.form.get('ref'):
            partner_ref = request.form.get('ref')
        if request.form.get('embed_fingerprint'):
            embed_fingerprint = normalize_embed_fingerprint(request.form.get('embed_fingerprint'))
        if request.form.get('cohort'):
            cohort_slug = request.form.get('cohort').strip() or None

    # Reject votes from disabled partner refs (kill switch: env + Partner.embed_disabled)
    from app.api.utils import sanitize_partner_ref, partner_ref_is_disabled
    partner_ref = sanitize_partner_ref(
        partner_ref if isinstance(partner_ref, str) else str(partner_ref or '')
    )
    if partner_ref and partner_ref_is_disabled(partner_ref):
        if is_form_post:
            flash('Voting from this partner is currently unavailable.', 'error')
            return redirect(url_for('statements.view_statement', statement_id=statement_id))
        return jsonify({'error': 'Embed and API access has been revoked for this partner.'}), 403

    if vote_value not in [-1, 0, 1]:
        if is_form_post:
            flash('Invalid vote value. Must be Agree, Disagree, or Unsure.', 'error')
            return redirect(url_for('statements.view_statement', statement_id=statement_id))
        return jsonify({'error': 'Invalid vote value. Must be -1, 0, or 1'}), 400

    cohort_slug = validate_cohort_for_discussion(discussion, cohort_slug)

    user_id = current_user.id if current_user.is_authenticated else None
    session_fingerprint = None if user_id else (embed_fingerprint or get_statement_vote_fingerprint())
    idempotency_key = _normalize_idempotency_key(
        request.headers.get('Idempotency-Key') or request.headers.get('X-Idempotency-Key')
    )
    idempotency_cache_key = None
    request_hash = None
    if idempotency_key and not is_form_post:
        actor_key = f"user:{user_id}" if user_id else f"anon:{(session_fingerprint or '')[:16]}"
        request_hash = _vote_request_hash(vote_value, confidence, partner_ref, cohort_slug)
        idempotency_cache_key = f"vote-idempotency:{statement_id}:{actor_key}:{idempotency_key}"
        prior = None
        try:
            prior = cache.get(idempotency_cache_key)
        except Exception:
            prior = None

        if prior:
            if prior.get('request_hash') != request_hash:
                return jsonify({
                    'error': 'idempotency_key_reused',
                    'message': 'This Idempotency-Key was already used with a different payload.'
                }), 409
            response_payload = dict(prior.get('response', {}) or {})
            # Refresh volatile consensus progress fields so duplicate requests
            # do not serve stale unlock/progress state.
            if response_payload.get('success'):
                try:
                    from app.discussions.consensus import build_consensus_ui_state
                    ui_state = build_consensus_ui_state(discussion)
                    response_payload.update({
                        'user_vote_count': ui_state['user_vote_count'],
                        'participation_threshold': ui_state['participation_threshold'],
                        'is_consensus_unlocked': ui_state['is_consensus_unlocked'],
                        'consensus_progress': ui_state['consensus_progress'],
                    })
                except Exception:
                    # Keep idempotency guarantees even if best-effort UI refresh fails.
                    pass
            return jsonify(response_payload), int(prior.get('status_code', 200))

    try:
        _persist_vote_with_upsert(
            statement=statement,
            vote_value=vote_value,
            confidence=confidence,
            partner_ref=partner_ref,
            cohort_slug=cohort_slug,
            user_id=user_id,
            session_fingerprint=session_fingerprint
        )
    except IntegrityError:
        db.session.rollback()
        try:
            _persist_vote_with_upsert(
                statement=statement,
                vote_value=vote_value,
                confidence=confidence,
                partner_ref=partner_ref,
                cohort_slug=cohort_slug,
                user_id=user_id,
                session_fingerprint=session_fingerprint
            )
        except IntegrityError:
            db.session.rollback()
            if is_form_post:
                flash('Vote could not be recorded due to a temporary conflict. Please try again.', 'error')
                return redirect(url_for('statements.view_statement', statement_id=statement_id))
            return jsonify({'error': 'vote_conflict', 'message': 'Temporary conflict while saving vote'}), 409

    _record_vote_anomaly_signals(statement.discussion_id, session_fingerprint=session_fingerprint)
    from app.api.utils import invalidate_partner_snapshot_cache
    invalidate_partner_snapshot_cache(statement.discussion_id)
    try:
        cache.delete(f"statement-votes:{statement.id}")
    except Exception:
        pass

    # Track vote with PostHog (background thread — does not block response)
    if posthog and getattr(posthog, 'project_api_key', None):
        try:
            referer = request.headers.get('Referer', '') if hasattr(request, 'headers') else ''
            request_url = request.url if hasattr(request, 'url') else ''
            is_social = any(domain in referer for domain in ['twitter.com', 'x.com', 'bsky.social', 'bluesky.social']) or 'utm_source' in request_url

            if current_user.is_authenticated:
                distinct_id = str(current_user.id)
            else:
                distinct_id = get_statement_vote_fingerprint()

            vote_label = {1: 'agree', -1: 'disagree', 0: 'unsure'}.get(vote_value, 'unknown')
            properties = {
                'statement_id': statement_id,
                'discussion_id': statement.discussion_id,
                'vote': vote_label,
                'is_authenticated': current_user.is_authenticated
            }

            if is_social:
                properties['source'] = 'social'
                properties['referer'] = referer
                posthog.capture(distinct_id=distinct_id, event='discussion_participated_from_social', properties=properties)

            posthog.capture(distinct_id=distinct_id, event='statement_voted', properties=properties)
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")

    # Consolidate participant tracking + analytics event into a single commit
    try:
        discussion = statement.discussion
        uid = current_user.id if current_user.is_authenticated else None
        fp = embed_fingerprint if not uid else None
        if not fp and not uid:
            fp = get_statement_vote_fingerprint()

        participant, is_new = DiscussionParticipant.track_participant(
            discussion_id=discussion.id,
            user_id=uid,
            participant_identifier=fp,
            commit=False,
            return_is_new=True
        )
        if cohort_slug:
            participant.cohort_slug = cohort_slug

        record_event(
            'statement_voted',
            commit=False,
            user_id=uid,
            discussion_id=statement.discussion_id,
            programme_id=discussion.programme_id,
            statement_id=statement.id,
            cohort_slug=cohort_slug,
            country=discussion.country,
            source='embed' if is_embed_request else 'web',
            event_metadata={'vote_value': vote_value, 'confidence': confidence}
        )

        db.session.commit()  # single commit for participant + analytics event

        if cohort_slug:
            record_event(
                'cohort_assigned',
                user_id=uid,
                discussion_id=discussion.id,
                programme_id=discussion.programme_id,
                cohort_slug=cohort_slug,
                country=discussion.country,
                source='vote_flow'
            )

        if is_new and discussion.creator_id and discussion.creator_id != uid:
            create_discussion_notification(
                user_id=discussion.creator_id,
                discussion_id=discussion.id,
                notification_type='new_participant',
                additional_data={'participant_count': discussion.participant_count}
            )
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(f"Post-vote tracking error: {e}")

    # Form POST from view_statement page: redirect back so user sees updated page
    if is_form_post:
        flash('Vote recorded.', 'success')
        return redirect(url_for('statements.view_statement', statement_id=statement_id))

    # Include fresh consensus-gate metrics so the voting UI can update
    # unlock/progress state without requiring a page refresh.
    from app.discussions.consensus import build_consensus_ui_state
    consensus_ui_state = build_consensus_ui_state(discussion)

    response_payload = {
        'success': True,
        'vote': vote_value,
        'vote_count_agree': statement.vote_count_agree,
        'vote_count_disagree': statement.vote_count_disagree,
        'vote_count_unsure': statement.vote_count_unsure,
        'total_votes': statement.total_votes,
        'agreement_rate': statement.agreement_rate,
        'controversy_score': statement.controversy_score,
        'user_vote_count': consensus_ui_state['user_vote_count'],
        'participation_threshold': consensus_ui_state['participation_threshold'],
        'is_consensus_unlocked': consensus_ui_state['is_consensus_unlocked'],
        'consensus_progress': consensus_ui_state['consensus_progress'],
    }

    if idempotency_cache_key and request_hash:
        try:
            cache.set(
                idempotency_cache_key,
                {'request_hash': request_hash, 'response': response_payload, 'status_code': 200},
                timeout=300
            )
        except Exception:
            pass

    return jsonify(response_payload)


@statements_bp.route('/statements/<int:statement_id>')
@with_db_retry()
def view_statement(statement_id):
    """View a single statement with its responses and votes"""
    statement = db.get_or_404(Statement, statement_id)
    discussion = statement.discussion
    _enforce_programme_visibility_for_discussion(discussion)
    
    # Get user's vote if logged in
    user_vote = None
    if current_user.is_authenticated:
        user_vote = StatementVote.query.filter_by(
            statement_id=statement_id,
            user_id=current_user.id
        ).first()
    
    # Get responses with eager loading to prevent N+1 queries
    from sqlalchemy.orm import joinedload
    responses = Response.query.options(
        joinedload(Response.user)
    ).filter_by(
        statement_id=statement_id,
        is_deleted=False
    ).order_by(Response.created_at.desc()).all()
    
    return render_template('discussions/view_statement.html',
                         statement=statement,
                         discussion=discussion,
                         user_vote=user_vote,
                         responses=responses)


@statements_bp.route('/statements/<int:statement_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_statement(statement_id):
    """Edit own statement (within 10 minute window)"""
    statement = db.get_or_404(Statement, statement_id)
    _enforce_programme_visibility_for_discussion(statement.discussion)
    
    # Check ownership
    if statement.user_id != current_user.id:
        flash("You can only edit your own statements", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    # Check edit window (10 minutes like pol.is)
    if utcnow_naive() - statement.created_at > timedelta(minutes=10):
        flash("Edit window expired (10 minutes)", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    form = StatementForm(obj=statement)
    
    if form.validate_on_submit():
        statement.content = form.content.data.strip()
        statement.statement_type = form.statement_type.data
        statement.updated_at = utcnow_naive()
        db.session.commit()
        
        flash("Statement updated successfully", "success")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    return render_template('discussions/edit_statement.html', 
                         form=form, 
                         statement=statement)


@statements_bp.route('/statements/<int:statement_id>/delete', methods=['POST'])
@login_required
def delete_statement(statement_id):
    """Soft delete own statement"""
    statement = db.get_or_404(Statement, statement_id)
    _enforce_programme_visibility_for_discussion(statement.discussion)
    
    # Check ownership or admin
    if statement.user_id != current_user.id and not current_user.is_admin:
        flash("You can only delete your own statements", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    statement.is_deleted = True
    db.session.commit()
    from app.api.utils import invalidate_partner_snapshot_cache
    invalidate_partner_snapshot_cache(statement.discussion_id)
    
    flash("Statement deleted", "success")
    return redirect(url_for('discussions.view_discussion', 
                          discussion_id=statement.discussion_id, 
                          slug=statement.discussion.slug))


@statements_bp.route('/statements/<int:statement_id>/flag', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute")
def flag_statement(statement_id):
    """Flag a statement for moderation"""
    statement = db.get_or_404(Statement, statement_id)
    _enforce_programme_visibility_for_discussion(statement.discussion)

    # Check if user already flagged this statement
    existing_flag = StatementFlag.query.filter_by(
        statement_id=statement_id,
        flagger_user_id=current_user.id
    ).first()
    
    if existing_flag:
        flash("You've already flagged this statement", "warning")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    form = FlagStatementForm()
    
    if form.validate_on_submit():
        flag = StatementFlag(
            statement_id=statement_id,
            flagger_user_id=current_user.id,
            flag_reason=form.flag_reason.data,
            additional_context=form.additional_context.data
        )
        db.session.add(flag)
        db.session.commit()
        
        flash("Statement flagged for review", "success")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    return render_template('discussions/flag_statement.html', 
                         form=form, 
                         statement=statement)


@statements_bp.route('/discussions/<int:discussion_id>/statements')
def list_statements(discussion_id):
    """
    List statements for a discussion with sorting options
    Progressive disclosure: prioritize statements with fewer votes
    """
    discussion = db.get_or_404(Discussion, discussion_id)
    _enforce_programme_visibility_for_discussion(discussion)

    if not discussion.has_native_statements:
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Get sort parameter
    sort = request.args.get('sort', 'best')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Base query
    query = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    )
    
    # Apply moderation filter
    if not (current_user.is_authenticated and 
            (current_user.id == discussion.creator_id or current_user.is_admin)):
        # Non-owners only see approved statements
        query = query.filter(Statement.mod_status >= 0)
    
    # Apply sorting
    # Keep one canonical sorter shared with discussion routes for all sort modes,
    # including controversial, to avoid full-table loads in Python.
    query = apply_statement_sort(query, sort, discussion_id, db.session)
    
    # Paginate
    statements = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('discussions/list_statements.html',
                         discussion=discussion,
                         statements=statements,
                         sort=sort)


# API endpoints for AJAX voting

@statements_bp.route('/api/statements/<int:statement_id>/votes')
def get_statement_votes(statement_id):
    """Get vote breakdown for a statement (API endpoint)"""
    cache_key = f"statement-votes:{statement_id}"
    try:
        cached = cache.get(cache_key)
        if cached:
            _safe_cache_increment("cache_metrics:statement_votes:hit", timeout=24 * 3600)
            return jsonify(cached)
    except Exception:
        pass

    _safe_cache_increment("cache_metrics:statement_votes:miss", timeout=24 * 3600)
    statement = db.get_or_404(Statement, statement_id)
    discussion = statement.discussion
    if discussion and discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    payload = {
        'statement_id': statement.id,
        'counts': {
            'agree': statement.vote_count_agree,
            'disagree': statement.vote_count_disagree,
            'unsure': statement.vote_count_unsure,
            'total': statement.total_votes
        },
        'stats': {
            'agreement_rate': statement.agreement_rate,
            'controversy_score': statement.controversy_score
        }
    }
    try:
        cache.set(cache_key, payload, timeout=60)
    except Exception:
        pass
    return jsonify(payload)


# =============================================================================
# PHASE 2: RESPONSE ROUTES (Threaded Pro/Con Arguments)
# =============================================================================

@statements_bp.route('/statements/<int:statement_id>/quick-response', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def quick_response(statement_id):
    """
    Quick inline response from voting UI.
    Creates a brief response without full form validation.
    """
    statement = db.get_or_404(Statement, statement_id)
    discussion = statement.discussion

    # Defensive check for orphaned statement
    if not discussion:
        flash("Discussion not found", "error")
        return redirect(url_for('discussions.search_discussions'))

    _enforce_programme_visibility_for_discussion(discussion)

    content = request.form.get('content', '').strip()
    position = request.form.get('position', 'neutral')

    # Validate position (same validation as create_response for DRY)
    valid_positions = ['pro', 'con', 'neutral']
    if position not in valid_positions:
        position = 'neutral'

    # Only create response if content meets minimum length
    min_length = 5
    if content and len(content) >= min_length:
        try:
            response = Response(
                statement_id=statement.id,
                user_id=current_user.id,
                parent_response_id=None,
                position=position,
                content=content[:500]  # Limit to 500 chars for quick responses
            )
            db.session.add(response)
            db.session.commit()
            response_count = Response.query.filter_by(
                statement_id=statement.id,
                is_deleted=False,
            ).count()
            record_event(
                'response_created',
                user_id=current_user.id,
                discussion_id=statement.discussion_id,
                programme_id=statement.discussion.programme_id if statement.discussion else None,
                statement_id=statement.id,
                country=statement.discussion.country if statement.discussion else None,
                source='quick_response'
            )
            _notify_discussion_owner_about_response_activity(
                discussion,
                actor_user_id=current_user.id,
                response_count=response_count,
            )
            flash("Your thought has been added!", "success")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating quick response: {e}")
            flash("Couldn't save your response. Try again?", "warning")
    elif content and len(content) < min_length:
        flash(f"Response must be at least {min_length} characters", "info")

    # Redirect back to discussion with anchor to statement
    return redirect(url_for('discussions.view_discussion',
                          discussion_id=discussion.id,
                          slug=discussion.slug) + f'#statement-{statement_id}')


@statements_bp.route('/statements/<int:statement_id>/responses/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("20 per minute")
def create_response(statement_id):
    """
    Create a threaded response to a statement or another response
    Supports pro/con/neutral positioning
    """
    statement = db.get_or_404(Statement, statement_id)

    _enforce_programme_visibility_for_discussion(statement.discussion)

    form = ResponseForm()
    # Pre-fill position from query param when coming from inline "write a detailed argument" link
    if request.method == 'GET':
        position_param = request.args.get('position')
        if position_param in ('pro', 'con', 'neutral'):
            form.position.data = position_param

    if form.validate_on_submit():
        try:
            response = Response(
                statement_id=statement.id,
                user_id=current_user.id,
                parent_response_id=None,  # Top-level response
                position=form.position.data,
                content=form.content.data
            )
            db.session.add(response)
            db.session.commit()
            response_count = Response.query.filter_by(
                statement_id=statement.id,
                is_deleted=False,
            ).count()
            record_event(
                'response_created',
                user_id=current_user.id,
                discussion_id=statement.discussion_id,
                programme_id=statement.discussion.programme_id if statement.discussion else None,
                statement_id=statement.id,
                country=statement.discussion.country if statement.discussion else None,
                source='response_form'
            )
            _notify_discussion_owner_about_response_activity(
                statement.discussion,
                actor_user_id=current_user.id,
                response_count=response_count,
            )
            
            flash("Response posted successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=statement.id))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error creating response: {e}")
            flash("An error occurred while posting your response", "danger")
    
    return render_template('discussions/create_response.html', 
                         statement=statement, 
                         form=form)


@statements_bp.route('/responses/<int:response_id>')
def view_response(response_id):
    """View a specific response with its thread"""
    response = db.get_or_404(Response, response_id)
    _enforce_programme_visibility_for_discussion(response.statement.discussion)
    
    if response.is_deleted:
        flash("This response has been deleted", "info")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Get the full thread (parent responses up to the root)
    thread = []
    current_response = response
    while current_response:
        thread.insert(0, current_response)
        current_response = current_response.parent_response if current_response.parent_response_id else None
    
    # Get child responses
    children = Response.query.filter_by(
        parent_response_id=response.id,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    return render_template('discussions/view_response.html', 
                         response=response,
                         thread=thread,
                         children=children)


@statements_bp.route('/responses/<int:response_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_response(response_id):
    """
    Edit a response (within 10-minute window)
    Only the author can edit
    """
    response = db.get_or_404(Response, response_id)
    _enforce_programme_visibility_for_discussion(response.statement.discussion)
    
    # Check ownership
    if response.user_id != current_user.id:
        flash("You can only edit your own responses", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Check if deleted
    if response.is_deleted:
        flash("Cannot edit a deleted response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Check 10-minute edit window
    edit_deadline = response.created_at + timedelta(minutes=10)
    if utcnow_naive() > edit_deadline:
        flash("Edit window has expired (10 minutes)", "warning")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    form = ResponseForm(obj=response)
    
    if form.validate_on_submit():
        try:
            response.content = form.content.data
            response.position = form.position.data
            response.updated_at = utcnow_naive()
            db.session.commit()
            
            flash("Response updated successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
        except ValueError as e:
            flash(str(e), "danger")
    
    return render_template('discussions/edit_response.html', form=form, response=response)


@statements_bp.route('/responses/<int:response_id>/delete', methods=['POST'])
@login_required
def delete_response(response_id):
    """
    Soft-delete a response
    Only the author or discussion owner can delete
    """
    response = db.get_or_404(Response, response_id)
    discussion = response.statement.discussion
    _enforce_programme_visibility_for_discussion(discussion)
    
    # Check permissions
    if response.user_id != current_user.id and discussion.creator_id != current_user.id:
        flash("You don't have permission to delete this response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    response.is_deleted = True
    db.session.commit()
    
    flash("Response deleted successfully", "success")
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/statements/<int:statement_id>/responses')
def list_responses(statement_id):
    """
    List all responses for a statement (threaded structure)
    Returns JSON for AJAX or HTML for direct access
    
    Uses a single query with eager loading to prevent N+1 queries.
    """
    from sqlalchemy.orm import joinedload, selectinload
    
    statement = db.get_or_404(Statement, statement_id)
    _enforce_programme_visibility_for_discussion(statement.discussion)
    
    # Fetch ALL responses for this statement with eager loading of users
    # This prevents N+1 queries when building the tree
    all_responses = Response.query.options(
        joinedload(Response.user)
    ).filter_by(
        statement_id=statement_id,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    # Build a lookup dict for efficient child finding
    response_by_id = {r.id: r for r in all_responses}
    children_by_parent = {}
    top_level = []
    
    for response in all_responses:
        if response.parent_response_id is None:
            top_level.append(response)
        else:
            if response.parent_response_id not in children_by_parent:
                children_by_parent[response.parent_response_id] = []
            children_by_parent[response.parent_response_id].append(response)
    
    def build_response_tree(response):
        """Build response tree from pre-loaded data (no additional queries)"""
        children = children_by_parent.get(response.id, [])
        return {
            'id': response.id,
            'content': response.content,
            'position': response.position,
            'user': response.user.name if response.user else 'Unknown',
            'created_at': response.created_at.isoformat(),
            'children': [build_response_tree(child) for child in children]
        }
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'statement_id': statement.id,
            'response_count': len(all_responses),
            'responses': [build_response_tree(r) for r in top_level]
        })
    
    # Return HTML for direct access
    return render_template('discussions/list_responses.html',
                         statement=statement,
                         responses=top_level)


@statements_bp.route('/api/responses/<int:response_id>/children')
def get_response_children(response_id):
    """
    Get child responses for lazy loading in threaded view
    Used for expanding/collapsing threads
    
    Uses eager loading and subquery for has_children to prevent N+1 queries.
    """
    from sqlalchemy.orm import joinedload
    from sqlalchemy import exists, and_
    
    response = db.get_or_404(Response, response_id)
    _enforce_programme_visibility_for_discussion(response.statement.discussion)
    
    # Eager load user relationship to prevent N+1
    children = Response.query.options(
        joinedload(Response.user)
    ).filter_by(
        parent_response_id=response_id,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    # Get all child IDs that have children (single query instead of N queries)
    child_ids = [c.id for c in children]
    has_children_set = set()
    if child_ids:
        subquery = db.session.query(Response.parent_response_id).filter(
            Response.parent_response_id.in_(child_ids),
            Response.is_deleted == False
        ).distinct().all()
        has_children_set = {row[0] for row in subquery}
    
    return jsonify({
        'response_id': response_id,
        'children': [{
            'id': child.id,
            'content': child.content,
            'position': child.position,
            'user': child.user.name if child.user else 'Unknown',
            'created_at': child.created_at.isoformat(),
            'has_children': child.id in has_children_set
        } for child in children]
    })


# =============================================================================
# PHASE 2: EVIDENCE ROUTES (Citations & File Uploads)
# =============================================================================

@statements_bp.route('/responses/<int:response_id>/evidence/add', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def add_evidence(response_id):
    """
    Add evidence to a response (citation, URL, or file upload)
    Uses Replit Object Storage for file uploads
    """
    from app.discussions.statement_forms import EvidenceForm
    from app.models import Evidence
    import os
    
    response = db.get_or_404(Response, response_id)
    _enforce_programme_visibility_for_discussion(response.statement.discussion)
    
    # Check if user can add evidence (response author or discussion owner)
    if response.user_id != current_user.id and response.statement.discussion.creator_id != current_user.id:
        flash("You don't have permission to add evidence to this response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    form = EvidenceForm()
    
    if form.validate_on_submit():
        try:
            evidence = Evidence(
                response_id=response.id,
                source_title=form.source_title.data,
                source_url=form.source_url.data,
                citation=form.citation.data,
                added_by_user_id=current_user.id
            )
            
            # Handle file upload to Replit Object Storage
            if 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                
                # Validate file size (max 10MB)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 10 * 1024 * 1024:  # 10MB
                    flash("File size must be under 10MB", "danger")
                    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
                
                # Upload to Replit Object Storage
                try:
                    from replit.object_storage import Client
                    storage_client = Client()
                    
                    # Generate unique key
                    import uuid
                    file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    storage_key = f"evidence/{response.statement.discussion_id}/{response.id}/{uuid.uuid4()}.{file_extension}"
                    
                    # Upload file
                    file_content = file.read()
                    storage_client.upload_from_bytes(storage_key, file_content)
                    
                    # Get public URL
                    evidence.storage_key = storage_key
                    evidence.storage_url = None  # Files are served via /api/evidence/<id>/download using the SDK key
                    
                except Exception as e:
                    current_app.logger.error(f"Error uploading to Replit storage: {e}")
                    flash("Error uploading file. Please try again.", "danger")
                    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
            
            db.session.add(evidence)
            db.session.commit()
            
            flash("Evidence added successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
            
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error adding evidence: {e}")
            flash("An error occurred while adding evidence", "danger")
    
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/evidence/<int:evidence_id>/delete', methods=['POST'])
@login_required
def delete_evidence(evidence_id):
    """
    Delete evidence (and remove file from Replit Object Storage if applicable)
    Only the user who added it or discussion owner can delete
    """
    from app.models import Evidence
    
    evidence = db.get_or_404(Evidence, evidence_id)
    response = evidence.response
    discussion = response.statement.discussion
    _enforce_programme_visibility_for_discussion(discussion)
    
    # Check permissions
    if evidence.added_by_user_id != current_user.id and discussion.creator_id != current_user.id:
        flash("You don't have permission to delete this evidence", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Delete file from Replit Object Storage if exists
    if evidence.storage_key:
        try:
            from replit.object_storage import Client
            storage_client = Client()
            storage_client.delete(evidence.storage_key)
        except Exception as e:
            current_app.logger.error(f"Error deleting file from storage: {e}")
            # Continue with database deletion even if storage deletion fails
    
    db.session.delete(evidence)
    db.session.commit()
    
    flash("Evidence deleted successfully", "success")
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/evidence/<int:evidence_id>/update-quality', methods=['POST'])
@login_required
def update_evidence_quality(evidence_id):
    """
    Update evidence quality status (pending/verified/disputed)
    Only discussion owner or moderators can update
    """
    from app.models import Evidence
    
    evidence = db.get_or_404(Evidence, evidence_id)
    discussion = evidence.response.statement.discussion
    _enforce_programme_visibility_for_discussion(discussion)
    
    # Check permissions (discussion owner only for now)
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can update evidence quality", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    quality_status = request.form.get('quality_status')
    if quality_status not in ['pending', 'verified', 'disputed']:
        flash("Invalid quality status", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    evidence.quality_status = quality_status
    db.session.commit()
    
    flash(f"Evidence marked as {quality_status}", "success")
    return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))


@statements_bp.route('/api/evidence/<int:evidence_id>/download')
def download_evidence(evidence_id):
    """
    Download evidence file from Replit Object Storage
    """
    from app.models import Evidence
    from flask import send_file
    import io
    
    evidence = db.get_or_404(Evidence, evidence_id)
    _enforce_programme_visibility_for_discussion(evidence.response.statement.discussion)
    
    if not evidence.storage_key:
        flash("No file attached to this evidence", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    try:
        from replit.object_storage import Client
        storage_client = Client()
        
        # Download file from storage
        file_content = storage_client.download_as_bytes(evidence.storage_key)
        
        # Get original filename
        filename = evidence.storage_key.split('/')[-1]
        
        # Return file
        return send_file(
            io.BytesIO(file_content),
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        current_app.logger.error(f"Error downloading evidence file: {e}")
        flash("Error downloading file", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))

