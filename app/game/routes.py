"""Game page routes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from flask import (
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user

from flask_babel import gettext as _

from app import limiter
from app.game import game_bp
from app.game.constants import DEFAULT_SOCIETY_NAME
from app.game.engine.emblem import emblem_style
from app.game.engine.scenario import load_scenario
from app.game.services.bridge_service import find_ss_bridge
from app.game.services.daily_service import (
    daily_meta,
    ensure_schedule_buffer,
    scheduled_scenario_slug,
    tomorrow_teaser,
    utc_game_date,
)
from app.game.services.identity_service import compute_daily_streak, player_has_game_history
from app.game.services.quick_run_service import (
    is_quick_run_slug,
    quick_run_entry,
    quick_run_pool,
)
from app.game.services.challenge_service import (
    challenge_play_target,
    challenge_reveal_for_run,
    challenge_url,
    get_or_create_challenge,
)
from app.game.services.share_text_service import build_share_text
from app.game.services.run_service import (
    GameRunNotFound,
    build_outcome_view,
    build_turn_view,
    get_or_start_daily_run,
    get_run_by_uuid,
    start_quick_run,
)
from app.models.game import GameChallenge
from app.lib.vote_identity import (
    get_voter_fingerprint,
    set_voter_client_cookies_if_needed,
)


def _player_identity():
    """Return (user_id, session_fingerprint) for the current visitor.

    We *always* compute the fingerprint, even for logged-in players, so that
    a logged-in run stores both identities. Two reasons:
    1. If the player later logs out, the same-day replay check can still find
       the completed run via the fingerprint — closing the login/logout
       bounce bypass.
    2. The fingerprint is the cross-device-merge anchor used by
       `fingerprints_for_anonymous_merge_on_login()`.
    """
    user_id = current_user.id if current_user.is_authenticated else None
    fingerprint = get_voter_fingerprint()
    return user_id, fingerprint


def _parse_schedule_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@game_bp.route('/')
@limiter.limit('60 per minute')
def index():
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    try:
        ensure_schedule_buffer()
    except Exception:  # noqa: BLE001 — log but don't break the hub on schedule errors.
        current_app.logger.exception('ensure_schedule_buffer failed on hub load')

    today = daily_meta()
    tomorrow = tomorrow_teaser()
    user_id, fingerprint = _player_identity()

    in_progress = None
    completed_today_uuid: str | None = None
    if user_id or fingerprint:
        from sqlalchemy import or_

        from app.game.constants import (
            GAME_RUN_STATUS_COMPLETED,
            GAME_RUN_STATUS_IN_PROGRESS,
        )
        from app.models.game import GameRun

        base = GameRun.query.filter_by(
            scenario_slug=today['scenario_slug'],
            mode='daily',
        )
        # Match either identity so a login/logout bounce doesn't lose the run.
        ownership_clauses = []
        if user_id:
            ownership_clauses.append(GameRun.user_id == user_id)
        if fingerprint:
            ownership_clauses.append(GameRun.session_fingerprint == fingerprint)
        if ownership_clauses:
            base = base.filter(or_(*ownership_clauses))

        run = (
            base.filter_by(status=GAME_RUN_STATUS_IN_PROGRESS)
            .order_by(GameRun.started_at.desc())
            .first()
        )
        if run:
            in_progress = {
                'uuid': run.uuid,
                'turn_index': run.turn_index,
                'total_turns': run.total_turns,
            }
        else:
            day_start = datetime.combine(utc_game_date(), time.min)
            day_end = day_start + timedelta(days=1)
            done = (
                base.filter_by(status=GAME_RUN_STATUS_COMPLETED)
                .filter(
                    GameRun.started_at >= day_start,
                    GameRun.started_at < day_end,
                )
                .order_by(GameRun.completed_at.desc())
                .first()
            )
            if done:
                completed_today_uuid = done.uuid

    streak = compute_daily_streak(user_id=user_id, session_fingerprint=fingerprint)
    quick_pool = quick_run_pool()

    # First-time visitor: no game history at all (daily or quick). Returning
    # players — including Quick Run-only — skip the explainer.
    is_first_time = not player_has_game_history(
        user_id=user_id,
        session_fingerprint=fingerprint,
    )

    response = make_response(
        render_template(
            'game/hub.html',
            today=today,
            tomorrow=tomorrow,
            in_progress=in_progress,
            completed_today_uuid=completed_today_uuid,
            streak=streak,
            quick_pool=quick_pool,
            is_authenticated=bool(user_id),
            is_first_time=is_first_time,
        )
    )
    return set_voter_client_cookies_if_needed(response)


@game_bp.route('/daily')
@game_bp.route('/daily/<schedule_date>')
@limiter.limit('60 per minute')
def daily(schedule_date: str | None = None):
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    today = utc_game_date()
    play_date = _parse_schedule_date(schedule_date) or today
    # Plan §3.1: yesterday's daily playable 48h for streak grace; older redirects to today.
    if play_date > today or (today - play_date).days > 2:
        return redirect(url_for('game.index'))

    scenario_slug = scheduled_scenario_slug(play_date)
    user_id, fingerprint = _player_identity()
    society_name = request.args.get('name', '').strip() or None

    run = get_or_start_daily_run(
        scenario_slug=scenario_slug,
        user_id=user_id,
        session_fingerprint=fingerprint,
        society_name=society_name,
    )

    if run.status == 'completed':
        return redirect(url_for('game.outcome', run_uuid=run.uuid))

    view = build_turn_view(run)
    scenario = load_scenario(scenario_slug)
    emblem = emblem_style(run.emblem_seed or run.uuid)
    meta = daily_meta(play_date)

    response = make_response(
        render_template(
            'game/turn.html',
            run=run,
            scenario=scenario,
            view=view,
            emblem=emblem,
            society_name=run.society_name or DEFAULT_SOCIETY_NAME,
            daily_meta=meta,
        )
    )
    return set_voter_client_cookies_if_needed(response)


@game_bp.route('/run/<scenario_slug>')
@limiter.limit('30 per minute')
def quick_run(scenario_slug: str):
    """Quick Run — play any scenario from the pool anytime; no streak credit."""
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    if not is_quick_run_slug(scenario_slug):
        abort(404)

    user_id, fingerprint = _player_identity()
    society_name = request.args.get('name', '').strip() or None

    run = start_quick_run(
        scenario_slug=scenario_slug,
        user_id=user_id,
        session_fingerprint=fingerprint,
        society_name=society_name,
    )

    view = build_turn_view(run)
    scenario = load_scenario(scenario_slug)
    emblem = emblem_style(run.emblem_seed or run.uuid)
    meta = quick_run_entry(scenario_slug) or {}

    response = make_response(
        render_template(
            'game/turn.html',
            run=run,
            scenario=scenario,
            view=view,
            emblem=emblem,
            society_name=run.society_name or DEFAULT_SOCIETY_NAME,
            daily_meta=meta,
            is_quick_run=True,
        )
    )
    return set_voter_client_cookies_if_needed(response)


@game_bp.route('/challenge/<token>')
@limiter.limit('60 per minute')
def challenge(token: str):
    """Friend challenge entry — plan §6.2."""
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    row = GameChallenge.query.filter_by(token=token).first()
    if not row:
        abort(404)

    session['pending_game_challenge'] = row.token
    target = challenge_play_target(row)
    if target['endpoint'] == 'daily':
        return redirect(url_for('game.daily', schedule_date=target['schedule_date']))
    return redirect(url_for('game.quick_run', scenario_slug=target['scenario_slug']))


@game_bp.route('/outcome/<run_uuid>')
@limiter.limit('120 per minute')
def outcome(run_uuid: str):
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    try:
        run = get_run_by_uuid(run_uuid)
    except GameRunNotFound:
        abort(404)

    if run.status != 'completed' or not run.outcome:
        return redirect(url_for('game.daily'))

    view = build_outcome_view(run)
    emblem = emblem_style(run.emblem_seed or run.uuid)
    ss_bridge = find_ss_bridge(run.scenario_slug)
    share_url = url_for('game.outcome', run_uuid=run.uuid, _external=True)
    contradiction = view.get('contradiction') or {}

    challenge_row = get_or_create_challenge(run)
    challenge_link = challenge_url(challenge_row) if challenge_row else None

    pending_token = session.pop('pending_game_challenge', None)
    challenge_reveal = challenge_reveal_for_run(
        completed_run=run,
        pending_token=pending_token,
    )

    share_text = build_share_text(
        society_name=run.society_name or '',
        headline=view['headline'],
        governance_label=view.get('governance_label'),
        scenario_title=view['scenario'].get('title', run.scenario_slug),
        visible_stats=view['visible_stats'],
        trait_chips=view.get('trait_chips'),
        streak_current=int((view.get('streak') or {}).get('current') or 0),
        contradiction_summary=contradiction.get('summary'),
        share_url=share_url,
        challenge_url=challenge_link,
        played_at=run.completed_at or run.started_at,
    )

    response = make_response(
        render_template(
            'game/outcome.html',
            **view,
            emblem=emblem,
            ss_bridge=ss_bridge,
            share_url=share_url,
            share_text=share_text,
            challenge_link=challenge_link,
            challenge_reveal=challenge_reveal,
            is_authenticated=current_user.is_authenticated,
        )
    )
    return set_voter_client_cookies_if_needed(response)


@game_bp.route('/editorial-principles')
def editorial_principles():
    return render_template('game/editorial_principles.html')


@game_bp.route('/outcome/<run_uuid>/og.png')
@limiter.limit('240 per minute')
def outcome_og_png(run_uuid: str):
    """OG share image as PNG — Twitter/iMessage/Slack/LinkedIn unfurl correctly.

    Cached for 24h in Redis (run UUIDs are immutable post-completion) and
    served with a public 24h HTTP cache so crawlers and CDNs honour it too.
    Falls back to the SVG endpoint if Pillow is unavailable on the host.
    """
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    try:
        run = get_run_by_uuid(run_uuid)
    except GameRunNotFound:
        abort(404)

    if run.status != 'completed' or not run.outcome:
        abort(404)

    from app.game.services import og_image_service

    if not og_image_service.is_available():
        return redirect(url_for('game.outcome_og_svg', run_uuid=run_uuid))

    cache_key = f'game:og:png:{run_uuid}'
    png_bytes = _og_cache_get(cache_key)
    if png_bytes is None:
        view = build_outcome_view(run)
        emblem = emblem_style(run.emblem_seed or run.uuid)
        png_bytes = og_image_service.render_outcome_png(run=run, view=view, emblem=emblem)
        if png_bytes is None:
            return redirect(url_for('game.outcome_og_svg', run_uuid=run_uuid))
        _og_cache_set(cache_key, png_bytes)

    response = make_response(png_bytes)
    response.headers['Content-Type'] = 'image/png'
    response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
    return response


@game_bp.route('/outcome/<run_uuid>/og.svg')
@limiter.limit('240 per minute')
def outcome_og_svg(run_uuid: str):
    """OG share image as SVG — fallback for environments without Pillow, and
    used directly by Discord/Mastodon/Bluesky which render SVG correctly.
    """
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    try:
        run = get_run_by_uuid(run_uuid)
    except GameRunNotFound:
        abort(404)

    if run.status != 'completed' or not run.outcome:
        abort(404)

    view = build_outcome_view(run)
    emblem = emblem_style(run.emblem_seed or run.uuid)
    svg = render_template(
        'game/outcome_og.svg',
        emblem=emblem,
        run=run,
        headline=view['headline'],
        governance_label=view['governance_label'],
        scenario=view['scenario'],
        axis=view['axis'],
    )
    response = make_response(svg)
    response.headers['Content-Type'] = 'image/svg+xml; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


def _og_cache_get(key: str) -> bytes | None:
    """Best-effort Redis read. Failure returns None so render path still works."""
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
        if client is None:
            return None
        return client.get(key)
    except Exception:  # noqa: BLE001 — cache miss is non-fatal
        current_app.logger.warning('og cache read failed', exc_info=True)
        return None


def _og_cache_set(key: str, value: bytes) -> None:
    """Best-effort Redis write with a 7-day TTL."""
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
        if client is None:
            return
        client.setex(key, 7 * 24 * 3600, value)
    except Exception:  # noqa: BLE001 — write failure is non-fatal
        current_app.logger.warning('og cache write failed', exc_info=True)
