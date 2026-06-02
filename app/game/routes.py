"""Game page routes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user

from flask_babel import gettext as _

from app import csrf, limiter
from app.game import game_bp
from app.game.constants import DEFAULT_SOCIETY_NAME
from app.game.engine.emblem import emblem_for_run, emblem_style
from app.game.engine.scenario import load_scenario
from app.game.services.archive_service import (
    completed_societies_for_visitor,
    count_completed_societies_for_visitor,
)
from app.game.services.bridge_service import find_ss_bridge
from app.game.services.cohort_service import cohort_comparison, cohort_share_line
from app.game.services.daily_results_service import world_today, world_today_share_line
from app.game.services.daily_service import (
    daily_meta,
    ensure_schedule_buffer,
    scheduled_scenario_slug,
    tomorrow_teaser,
    utc_game_date,
)
from app.game.services.identity_service import (
    compute_daily_streak,
    player_has_game_history,
    visitor_owns_run,
)
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
from app.game.services.past_self_service import previous_outcome_for_scenario
from app.game.services.profile_service import compute_player_profile
from app.game.services.reminder_service import (
    has_active_reminder,
    subscribe_to_reminders,
    unsubscribe as unsubscribe_reminder,
)
from app.game.services.share_text_service import build_share_text
from app.game.services.society_name_service import generate_society_names
from app.game.services.stats_service import participation_stats
from app.game.services.run_service import (
    GameRunNotFound,
    build_outcome_view,
    build_turn_view,
    get_or_start_daily_run,
    get_run_by_uuid,
    start_quick_run,
)
from app.models.game import GameChallenge, GameReminderSubscription
from app.lib.url_utils import safe_next_url
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


def _name_was_custom(name_source: str | None) -> bool | None:
    """Map the hub's ``name_source`` hint to an analytics flag.

    The hub pre-fills a suggested society name, so we can no longer infer
    "the player chose a name" from the stored string differing from the
    default. The client tells us explicitly: ``custom`` when the player typed
    their own, ``suggested`` when they accepted/rolled one of ours. Absent
    (older links, deep links) → ``None`` so the service keeps its legacy
    string-comparison behaviour.
    """
    if name_source == 'custom':
        return True
    if name_source == 'suggested':
        return False
    return None


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

    # Pre-fill an evocative society name so the only required action is "Play".
    # Seed by visitor+day so a reload doesn't shuffle the pre-fill mid-decision;
    # the inlined pool still varies per-visitor so reroll feels fresh.
    society_name_suggestions: list = []
    if not in_progress and not completed_today_uuid:
        seed = f"{fingerprint or 'anon'}|{today['schedule_date'].isoformat()}"
        society_name_suggestions = generate_society_names(12, seed=seed)

    # First-timers: a no-spoiler taste of today's actual dilemma (turn 1 only)
    # to convert the curious before they commit.
    dilemma_preview = None
    if is_first_time and not in_progress and not completed_today_uuid:
        dilemma_preview = _dilemma_preview(today['scenario_slug'])

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
            society_name_suggestions=society_name_suggestions,
            participation=participation_stats(),
            dilemma_preview=dilemma_preview,
        )
    )
    return set_voter_client_cookies_if_needed(response)


def _dilemma_preview(scenario_slug: str) -> dict | None:
    """Turn-1 prompt + choice labels for the hub teaser (no effects shown)."""
    try:
        scenario = load_scenario(scenario_slug)
    except Exception:  # noqa: BLE001 — never break the hub on a bad scenario
        return None
    turns = scenario.get('turns') or []
    if not turns:
        return None
    first = turns[0]
    labels = [c.get('label', '') for c in (first.get('choices') or [])[:3] if c.get('label')]
    if not labels:
        return None
    return {'prompt': first.get('prompt', ''), 'choices': labels}


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
    name_was_custom = _name_was_custom(request.args.get('name_source'))

    run = get_or_start_daily_run(
        scenario_slug=scenario_slug,
        user_id=user_id,
        session_fingerprint=fingerprint,
        society_name=society_name,
        name_was_custom=name_was_custom,
        seed_date=play_date,
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
    name_was_custom = _name_was_custom(request.args.get('name_source'))

    run = start_quick_run(
        scenario_slug=scenario_slug,
        user_id=user_id,
        session_fingerprint=fingerprint,
        society_name=society_name,
        name_was_custom=name_was_custom,
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
    emblem = emblem_for_run(run)
    ss_bridge = find_ss_bridge(run.scenario_slug)
    share_url = url_for('game.outcome', run_uuid=run.uuid, _external=True)
    contradiction = view.get('contradiction') or {}

    cohort = cohort_comparison(run)
    world = world_today(run)
    # One social comparison line: prefer the vivid choice-level "you went against
    # the crowd" beat, fall back to outcome rarity. DRY — a single 🌍 line.
    world_line = world_today_share_line(world) or cohort_share_line(cohort)

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
        cohort_line=world_line,
        share_url=share_url,
        challenge_url=challenge_link,
        played_at=run.completed_at or run.started_at,
    )

    user_id, fingerprint = _player_identity()
    owns_run = visitor_owns_run(run, user_id=user_id, session_fingerprint=fingerprint)
    # 'Beat your past self' is first-person reflection — only for the run's owner,
    # never leaked to someone viewing a public shared link.
    past_self = previous_outcome_for_scenario(run) if owns_run else None
    if owns_run:
        signin_return = url_for('game.outcome', run_uuid=run.uuid)
    else:
        # Shared links are public — sign-in should land on the hub, not someone
        # else's outcome card, even though login-merge still claims this browser's runs.
        signin_return = url_for('game.index')

    # Re-engagement opt-in: only on your own daily runs, when enabled, and only
    # if you're not already subscribed (idempotent on the backend regardless).
    reminder_email_prefill = (
        (getattr(current_user, 'email', '') or '') if current_user.is_authenticated else ''
    )
    show_reminder_optin = bool(
        _reminders_enabled()
        and owns_run
        and not view.get('is_quick_run')
        and not has_active_reminder(
            user_id=user_id,
            session_fingerprint=fingerprint,
            email=reminder_email_prefill or None,
        )
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
            cohort=cohort,
            world=world,
            is_authenticated=current_user.is_authenticated,
            signin_return=signin_return,
            show_reminder_optin=show_reminder_optin,
            reminder_email_prefill=reminder_email_prefill,
            past_self=past_self,
        )
    )
    return set_voter_client_cookies_if_needed(response)


_ARCHIVE_PAGE_SIZE = 24


@game_bp.route('/archive')
@limiter.limit('60 per minute')
def archive():
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    user_id, fingerprint = _player_identity()
    page = max(1, request.args.get('page', default=1, type=int) or 1)

    total = count_completed_societies_for_visitor(
        user_id=user_id,
        session_fingerprint=fingerprint,
    )
    total_pages = max(1, -(-total // _ARCHIVE_PAGE_SIZE)) if total else 1
    societies = completed_societies_for_visitor(
        user_id=user_id,
        session_fingerprint=fingerprint,
        limit=_ARCHIVE_PAGE_SIZE,
        offset=(page - 1) * _ARCHIVE_PAGE_SIZE,
    )
    streak = compute_daily_streak(user_id=user_id, session_fingerprint=fingerprint)

    response = make_response(
        render_template(
            'game/archive.html',
            societies=societies,
            streak=streak,
            is_authenticated=bool(user_id),
            page=page,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )
    )
    return set_voter_client_cookies_if_needed(response)


@game_bp.route('/profile')
@limiter.limit('60 per minute')
def profile():
    """Cumulative governing identity across all of this visitor's societies."""
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)

    user_id, fingerprint = _player_identity()
    profile_data = compute_player_profile(
        user_id=user_id, session_fingerprint=fingerprint
    )
    streak = compute_daily_streak(user_id=user_id, session_fingerprint=fingerprint)

    response = make_response(
        render_template(
            'game/profile.html',
            profile=profile_data,
            streak=streak,
            is_authenticated=bool(user_id),
        )
    )
    return set_voter_client_cookies_if_needed(response)


def _reminders_enabled() -> bool:
    return bool(
        current_app.config.get('GAME_ENABLED', True)
        and current_app.config.get('GAME_REMINDERS_ENABLED', True)
    )


def _same_origin_referrer() -> str | None:
    """Path of ``request.referrer`` if it points back to this host, else None.

    Guards against open-redirect via a crafted Referer header.
    """
    from urllib.parse import urlparse

    ref = request.referrer or ''
    if not ref:
        return None
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.host:
        return None
    path = parsed.path or '/'
    if parsed.query:
        path = f'{path}?{parsed.query}'
    return safe_next_url(path)


@game_bp.route('/reminders/subscribe', methods=['POST'])
@limiter.limit('10 per hour')
def reminders_subscribe():
    """Opt in to the 'today's scenario is live / keep your streak' nudge.

    Supports both a JSON fetch (from the outcome page) and a plain form post.
    Logged-in players don't need to type an email — we use their account's.
    """
    if not _reminders_enabled():
        abort(404)

    user_id, fingerprint = _player_identity()
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in (request.headers.get('Accept') or '')
    )

    email = (request.form.get('email') or '').strip()
    if not email and current_user.is_authenticated:
        email = (getattr(current_user, 'email', '') or '').strip()

    timezone_name = (request.form.get('timezone') or 'UTC').strip() or 'UTC'
    try:
        hour = int(request.form.get('hour', 8))
    except (TypeError, ValueError):
        hour = 8

    sub = subscribe_to_reminders(
        email=email,
        user_id=user_id,
        session_fingerprint=fingerprint,
        timezone_name=timezone_name,
        preferred_hour=hour,
    )

    fallback = _same_origin_referrer() or url_for('game.index')

    if not sub:
        if wants_json:
            return jsonify({'ok': False, 'error': 'invalid_email'}), 400
        flash(_('Please enter a valid email address.'), 'error')
        return redirect(fallback)

    if wants_json:
        return jsonify({'ok': True})
    flash(_("You're set — we'll nudge you when the next scenario is live."), 'success')
    return redirect(fallback)


@game_bp.route('/reminders/unsubscribe', methods=['GET', 'POST'])
@csrf.exempt  # RFC 8058 one-click POSTs originate from mail clients without a token.
def reminders_unsubscribe():
    """One-click unsubscribe (RFC 8058) and human GET — token never expires."""
    token = request.args.get('token') or request.form.get('token')
    sub = GameReminderSubscription.find_by_unsubscribe_token(token)

    is_one_click = (
        request.method == 'POST'
        and request.form.get('List-Unsubscribe') == 'One-Click'
    )

    if not sub:
        if request.method == 'POST':
            return '', 200  # RFC 8058: never error to a mail client
        flash(_('That unsubscribe link is no longer valid.'), 'error')
        return redirect(url_for('game.index'))

    if not sub.is_active:
        if request.method == 'POST':
            return '', 200
        return render_template('game/reminders_unsubscribed.html', email=sub.email)

    unsubscribe_reminder(sub, reason='one_click' if is_one_click else 'user')

    if is_one_click:
        return '', 200
    return render_template('game/reminders_unsubscribed.html', email=sub.email)


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

    # Social-proof badge ("Only X% made your call"). Keyed into the cache so an
    # early, pre-threshold render doesn't freeze a badge-less card for 24h — once
    # the cohort grows, the ready variant caches under a distinct key.
    world_badge = world_today_share_line(world_today(run))
    cache_key = f'game:og:png:{run_uuid}:{"w1" if world_badge else "w0"}'
    png_bytes = _og_cache_get(cache_key)
    if png_bytes is None:
        view = build_outcome_view(run)
        emblem = emblem_for_run(run)
        png_bytes = og_image_service.render_outcome_png(
            run=run, view=view, emblem=emblem, world_badge=world_badge
        )
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
    emblem = emblem_for_run(run)
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
