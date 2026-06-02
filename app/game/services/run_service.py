"""Game run lifecycle."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app

from app import db
from app.game.analytics import resolve_distinct_id_for_run, track_game_event
from app.game.constants import (
    DEFAULT_SOCIETY_NAME,
    GAME_RUN_STATUS_COMPLETED,
    GAME_RUN_STATUS_IN_PROGRESS,
    STAT_VISIBLE,
)
from app.game.engine.archetype import build_outcome
from app.game.engine.contradiction import detect_contradiction
from app.game.engine.effects import (
    apply_choice,
    apply_delayed_events,
    clone_delayed_queue,
    process_turn_start,
)
from app.game.engine.scenario import (
    choice_by_id,
    load_scenario,
    scenario_turn,
    turn_context_for_player,
)
from app.game.engine.state import SocietyState
from app.game.engine.variant import (
    apply_initial_variation,
    daily_variant_seed,
    random_variant_seed,
    variation_descriptor,
)
from app.game.services.daily_service import utc_game_date
from app.lib.time import utcnow_naive
from app.models.game import GameRun, GameRunOutcome


class GameRunError(Exception):
    """Base game run error."""


class GameRunNotFound(GameRunError):
    pass


class InvalidChoice(GameRunError):
    pass


class RunAlreadyComplete(GameRunError):
    pass


def _initial_state(scenario: Dict[str, Any]) -> SocietyState:
    return SocietyState.from_dict(scenario.get('initial_state'))


def _variation_enabled() -> bool:
    return bool(current_app.config.get('GAME_SCENARIO_VARIATION_ENABLED', True))


def _seeded_initial_state(
    scenario: Dict[str, Any], seed: Optional[int]
) -> SocietyState:
    """Opening state with seeded variation applied (baseline when seed is None)."""
    varied = apply_initial_variation(scenario.get('initial_state') or {}, seed)
    return SocietyState.from_dict(varied)


def run_situation(run: GameRun) -> Optional[Dict[str, str]]:
    """Legible one-liner describing this run's opening drift from baseline."""
    if run.variant_seed is None:
        return None
    scenario = load_scenario(run.scenario_slug)
    base = scenario.get('initial_state') or {}
    varied = apply_initial_variation(base, run.variant_seed)
    return variation_descriptor(base, varied)


def _resolve_has_custom_name(
    *, society_name: str, name_was_custom: Optional[bool]
) -> bool:
    """Whether the player authored the society name (for analytics).

    The hub now pre-fills a suggested name, so a stored name differing from the
    default no longer implies the player chose it. When the caller knows
    (``name_was_custom`` is not None) we trust that signal; otherwise we fall
    back to the legacy heuristic for callers that don't pass the hint.
    """
    if name_was_custom is not None:
        return name_was_custom
    return society_name != DEFAULT_SOCIETY_NAME


def get_or_start_daily_run(
    *,
    scenario_slug: str,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
    society_name: Optional[str] = None,
    name_was_custom: Optional[bool] = None,
    seed_date: Optional[date] = None,
) -> GameRun:
    """Return in-progress, completed, or fresh daily run for this scenario.

    Plan §3.1: a player completes today's daily once. Subsequent attempts
    return the existing completed run so the caller can redirect to the
    outcome, not a fresh replay.

    ``seed_date`` is the scenario's *scheduled* date and drives opening-state
    variation. It must be the schedule date (not wall-clock today) so that
    everyone who plays a given day's daily — on the day, within the 48h streak
    grace window, or via a daily challenge — inherits the identical opening,
    preserving the shared-daily and cohort/challenge guarantees.
    """
    scenario = load_scenario(scenario_slug)
    total_turns = len(scenario['turns'])

    if not user_id and not session_fingerprint:
        raise GameRunError('Identity required')

    from sqlalchemy import or_

    def _scoped(query):
        """Match runs owned by *either* this user_id or this fingerprint.

        Closes the login/logout bounce: a logged-in user who plays the daily,
        logs out, and visits anon should still be redirected to their existing
        outcome instead of starting a fresh run (plan §3.1).
        """
        clauses = []
        if user_id:
            clauses.append(GameRun.user_id == user_id)
        if session_fingerprint:
            clauses.append(GameRun.session_fingerprint == session_fingerprint)
        if not clauses:
            return query
        return query.filter(or_(*clauses))

    base = GameRun.query.filter_by(scenario_slug=scenario_slug, mode='daily')

    # Same UTC day completed → caller redirects to outcome (no replay grind, plan §3.1).
    # Scenarios recur in the rotation, so scope the lookup to today's UTC window
    # rather than "any completed run with this slug, ever."
    today_utc = utc_game_date()
    day_start = datetime.combine(today_utc, time.min)
    day_end = day_start + timedelta(days=1)
    completed_today = (
        _scoped(base.filter_by(status=GAME_RUN_STATUS_COMPLETED))
        .filter(GameRun.started_at >= day_start, GameRun.started_at < day_end)
        .order_by(GameRun.completed_at.desc())
        .first()
    )
    if completed_today:
        return completed_today

    run = (
        _scoped(base.filter_by(status=GAME_RUN_STATUS_IN_PROGRESS))
        .order_by(GameRun.started_at.desc())
        .first()
    )

    now = utcnow_naive()
    expiry_hours = int(current_app.config.get('GAME_DAILY_RUN_EXPIRY_HOURS', 24))
    cutoff = now - timedelta(hours=expiry_hours)

    if run and run.last_active_at and run.last_active_at < cutoff:
        run.status = 'abandoned'
        db.session.commit()
        run = None

    if run:
        if not run.last_active_at or (now - run.last_active_at) > timedelta(minutes=5):
            run.last_active_at = now
            db.session.commit()
        return run

    name = (society_name or '').strip() or DEFAULT_SOCIETY_NAME
    seed = (
        daily_variant_seed(scenario_slug, seed_date or today_utc)
        if _variation_enabled()
        else None
    )
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=scenario_slug,
        mode='daily',
        user_id=user_id,
        session_fingerprint=session_fingerprint,
        society_name=name[:80],
        emblem_seed=GameRun.generate_uuid(),
        variant_seed=seed,
        state_json=_seeded_initial_state(scenario, seed).to_dict(),
        choice_log_json=[],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=0,
        total_turns=total_turns,
        status=GAME_RUN_STATUS_IN_PROGRESS,
    )
    run.posthog_distinct_id = resolve_distinct_id_for_run(run)
    db.session.add(run)
    db.session.commit()
    track_game_event(
        run,
        'game_run_started',
        properties={
            'has_custom_name': _resolve_has_custom_name(
                society_name=run.society_name, name_was_custom=name_was_custom
            )
        },
    )
    return run


def start_quick_run(
    *,
    scenario_slug: str,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
    society_name: Optional[str] = None,
    name_was_custom: Optional[bool] = None,
) -> GameRun:
    """Fresh Quick Run — plan §3.2: replay anytime, no streak credit.

    Always creates a new run; quick play is explicitly unbounded so a player
    can try multiple paths through the same scenario in one session. The
    ``mode='quick'`` tag keeps these out of the daily streak and outcome-grid
    calculations.
    """
    scenario = load_scenario(scenario_slug)
    total_turns = len(scenario['turns'])

    if not user_id and not session_fingerprint:
        raise GameRunError('Identity required')

    name = (society_name or '').strip() or DEFAULT_SOCIETY_NAME
    seed = random_variant_seed() if _variation_enabled() else None
    run = GameRun(
        uuid=GameRun.generate_uuid(),
        scenario_slug=scenario_slug,
        mode='quick',
        user_id=user_id,
        session_fingerprint=session_fingerprint,
        society_name=name[:80],
        emblem_seed=GameRun.generate_uuid(),
        variant_seed=seed,
        state_json=_seeded_initial_state(scenario, seed).to_dict(),
        choice_log_json=[],
        delayed_queue_json=[],
        headline_log_json=[],
        turn_index=0,
        total_turns=total_turns,
        status=GAME_RUN_STATUS_IN_PROGRESS,
    )
    run.posthog_distinct_id = resolve_distinct_id_for_run(run)
    db.session.add(run)
    db.session.commit()
    track_game_event(
        run,
        'game_run_started',
        properties={
            'mode': 'quick',
            'has_custom_name': _resolve_has_custom_name(
                society_name=run.society_name, name_was_custom=name_was_custom
            ),
        },
    )
    return run


def get_or_start_slice_run(
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
    society_name: Optional[str] = None,
) -> GameRun:
    """Back-compat wrapper — uses today's scheduled scenario."""
    from app.game.services.daily_service import scheduled_scenario_slug

    return get_or_start_daily_run(
        scenario_slug=scheduled_scenario_slug(),
        user_id=user_id,
        session_fingerprint=session_fingerprint,
        society_name=society_name,
    )


def get_run_by_uuid(run_uuid: str) -> GameRun:
    run = GameRun.query.filter_by(uuid=run_uuid).first()
    if not run:
        raise GameRunNotFound('Run not found')
    return run


def build_turn_view(run: GameRun) -> Dict[str, Any]:
    scenario = load_scenario(run.scenario_slug)
    if run.status == GAME_RUN_STATUS_COMPLETED:
        return {'complete': True, 'run': run, 'scenario': scenario}

    turn = scenario_turn(scenario, run.turn_index)
    if not turn:
        return {'complete': True, 'run': run, 'scenario': scenario}

    state = SocietyState.from_dict(run.state_json)
    choice_log = list(run.choice_log_json or [])
    prompt = turn_context_for_player(turn, choice_log)

    choices_public = []
    for choice in turn.get('choices', []):
        immediate = (choice.get('effects') or {}).get('immediate') or {}
        preview: Dict[str, str] = {}
        for stat in STAT_VISIBLE:
            delta = immediate.get(stat)
            if delta is None:
                continue
            preview[stat] = 'up' if int(delta) > 0 else 'down' if int(delta) < 0 else 'flat'
        choices_public.append(
            {
                'id': choice['id'],
                'label': choice['label'],
                'flavour': choice.get('flavour', ''),
                'preview': preview,
            }
        )

    state_dict = state.to_dict()
    return {
        'complete': False,
        'run': run,
        'scenario': scenario,
        'turn': turn,
        'turn_index': run.turn_index,
        'total_turns': run.total_turns,
        'prompt': prompt,
        'beat': turn.get('beat'),
        'choices': choices_public,
        'state': state_dict,
        'visible_stats': {k: state_dict[k] for k in STAT_VISIBLE},
        'mood_level': state.mood_level(),
        'pressure_level': state.pressure_level(),
        'headlines': list(run.headline_log_json or [])[-3:],
        'situation': run_situation(run) if run.turn_index == 0 else None,
    }


def next_turn_payload(run: GameRun) -> Optional[Dict[str, Any]]:
    """Minimal JSON for client-side rendering of the next turn after a choice."""
    view = build_turn_view(run)
    if view.get('complete'):
        return None
    return {
        'turn_index': view['turn_index'],
        'total_turns': view['total_turns'],
        'beat': view['beat'],
        'prompt': view['prompt'],
        'choices': view['choices'],
        'headlines': view['headlines'],
        'mood_level': view['mood_level'],
        'pressure_level': view['pressure_level'],
    }


def apply_run_choice(run: GameRun, choice_id: str) -> Dict[str, Any]:
    if run.status == GAME_RUN_STATUS_COMPLETED:
        raise RunAlreadyComplete('Run already complete')

    scenario = load_scenario(run.scenario_slug)
    turn = scenario_turn(scenario, run.turn_index)
    if not turn:
        raise InvalidChoice('No turn available')

    choice = choice_by_id(turn, choice_id)
    if not choice:
        raise InvalidChoice('Invalid choice')

    state = SocietyState.from_dict(run.state_json)
    delayed_queue = clone_delayed_queue(run.delayed_queue_json or [])
    choice_log = list(run.choice_log_json or [])
    headlines = list(run.headline_log_json or [])

    consequence = apply_choice(
        state,
        choice,
        run.turn_index,
        run.total_turns,
        delayed_queue,
    )
    if consequence.get('headline'):
        headlines.append(consequence['headline'])

    completed_turn_index = run.turn_index
    choice_log.append(
        {
            'turn_index': completed_turn_index,
            'turn_id': turn.get('id'),
            'choice_id': choice.get('id'),
            'label': choice.get('label'),
            'memory_label': choice.get('memory_label'),
            'tags': list(choice.get('tags') or []),
        }
    )

    run.turn_index += 1
    run.state_json = state.to_dict()
    run.delayed_queue_json = delayed_queue
    run.choice_log_json = choice_log
    run.headline_log_json = headlines[-10:]
    run.last_active_at = utcnow_naive()

    next_consequence = None
    if run.turn_index < run.total_turns:
        delayed_queue, fired = process_turn_start(delayed_queue, run.turn_index)
        if fired:
            next_consequence = apply_delayed_events(state, fired)
            headlines.extend(next_consequence.get('headlines') or [])
            run.headline_log_json = headlines[-10:]
            run.delayed_queue_json = delayed_queue
            run.state_json = state.to_dict()

    game_complete = run.turn_index >= run.total_turns
    outcome_payload = None
    if game_complete:
        outcome_payload = _complete_run(run, scenario, state, choice_log)
        run.status = GAME_RUN_STATUS_COMPLETED
        run.completed_at = utcnow_naive()

    db.session.commit()

    track_game_event(
        run,
        'game_turn_completed',
        properties={
            'choice_id': choice_id,
            'completed_turn_index': completed_turn_index,
            'game_complete': game_complete,
        },
    )
    if game_complete:
        track_game_event(
            run,
            'game_run_completed',
            properties={
                'mode': run.mode,
                'outcome_category': (outcome_payload or {}).get('outcome_category'),
            },
        )
        if run.mode == 'daily':
            from app.game.services.identity_service import compute_daily_streak

            streak = compute_daily_streak(
                user_id=run.user_id,
                session_fingerprint=run.session_fingerprint,
            )
            if streak['current'] > 1:
                track_game_event(
                    run,
                    'game_streak_extended',
                    properties={
                        'current_streak': streak['current'],
                        'longest_streak': streak['longest'],
                    },
                )

    state_dict = state.to_dict()
    result = {
        'consequence': consequence,
        'next_consequence': next_consequence,
        'game_complete': game_complete,
        'state': state_dict,
        'visible_stats': {k: state_dict[k] for k in STAT_VISIBLE},
        'mood_level': state.mood_level(),
        'pressure_level': state.pressure_level(),
        'turn_index': run.turn_index,
        'outcome_url': f'/play/outcome/{run.uuid}' if game_complete else None,
        'next_turn': next_turn_payload(run) if not game_complete else None,
    }
    if outcome_payload:
        result['outcome'] = outcome_payload
    return result


def _complete_run(
    run: GameRun,
    scenario: Dict[str, Any],
    state: SocietyState,
    choice_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    outcome_data = build_outcome(state, choice_log, scenario)
    contradiction = detect_contradiction(choice_log)

    existing = GameRunOutcome.query.filter_by(run_id=run.id).first()
    if existing:
        db.session.delete(existing)

    outcome = GameRunOutcome(
        run_id=run.id,
        headline=outcome_data['headline'],
        governance_label=outcome_data['governance_label'],
        outcome_category=outcome_data['outcome_category'],
        axis_trust_autonomy=outcome_data['axis_trust_autonomy'],
        axis_prosperity_fairness=outcome_data['axis_prosperity_fairness'],
        stat_finals_json=outcome_data['stat_finals'],
        trait_chips_json=outcome_data['trait_chips'],
        contradiction_json=contradiction,
    )
    db.session.add(outcome)
    outcome_data['contradiction'] = contradiction
    return outcome_data


def build_outcome_view(run: GameRun) -> Dict[str, Any]:
    scenario = load_scenario(run.scenario_slug)
    outcome = run.outcome
    if not outcome:
        raise GameRunError('Outcome not ready')

    stats = outcome.stat_finals_json or {}

    streak: Dict[str, Any] = {'current': 0, 'longest': 0, 'last_played_date': None}
    if run.mode == 'daily':
        from app.game.services.identity_service import compute_daily_streak

        streak = compute_daily_streak(
            user_id=run.user_id,
            session_fingerprint=run.session_fingerprint,
        )

    return {
        'run': run,
        'scenario': scenario,
        'outcome': outcome,
        'headline': outcome.headline,
        'governance_label': outcome.governance_label,
        'trait_chips': outcome.trait_chips_json or [],
        'contradiction': outcome.contradiction_json,
        'stats': stats,
        'visible_stats': {k: stats.get(k, 0) for k in STAT_VISIBLE},
        'axis': {
            'trust_autonomy': float(outcome.axis_trust_autonomy or 50.0),
            'prosperity_fairness': float(outcome.axis_prosperity_fairness or 50.0),
        },
        'streak': streak,
        'is_quick_run': run.mode == 'quick',
    }
