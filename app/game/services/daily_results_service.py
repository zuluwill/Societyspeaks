"""How the world governed today — per-turn choice distribution for a daily scenario.

Powers the social-proof moment on the outcome page ("62% bailed out the banks —
you didn't"). Because the daily is shared and seeded identically for everyone on
a given UTC day, every player faced the same turns and choices, so the
distribution is a fair, like-for-like comparison.

Privacy: gated by the same ``GAME_COHORT_MIN_N`` floor as cohort_service, so
nothing renders from a tiny sample.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.engine.scenario import load_scenario
from app.game.services.cohort_service import cohort_min_n
from app.models.game import GameRun

logger = logging.getLogger(__name__)

# The tally is player-independent (same for everyone on the day), so it caches
# cleanly. Short TTL keeps "today" feeling live without re-scanning every run's
# choice_log on each outcome render — the hot-path cost the HTML page used to pay.
_TALLY_CACHE_TTL_SECONDS = 60


def _day_window(day):
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def _player_choice_by_turn(run: GameRun) -> Dict[int, str]:
    """Map of turn_index → choice_id for this run (to highlight 'your' pick)."""
    out: Dict[int, str] = {}
    for entry in run.choice_log_json or []:
        try:
            out[int(entry.get('turn_index'))] = entry.get('choice_id')
        except (TypeError, ValueError):
            continue
    return out


def _compute_tally(scenario_slug: str, day: date) -> Dict[str, Any]:
    """Player-independent distribution for (scenario, UTC day).

    Returns ``{'sample_size': N, 'turns': [{turn_index, beat, choices:[{choice_id,
    label, percent}]}]}`` — percentages only, no per-player marks, so it's safe to
    share across every visitor (and to cache).
    """
    start, end = _day_window(day)
    rows = (
        db.session.query(GameRun.choice_log_json)
        .filter(
            GameRun.scenario_slug == scenario_slug,
            GameRun.mode == 'daily',
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            GameRun.started_at >= start,
            GameRun.started_at < end,
        )
        .all()
    )

    counts: Dict[int, Dict[str, int]] = {}
    for (log,) in rows:
        for entry in log or []:
            try:
                tidx = int(entry.get('turn_index'))
            except (TypeError, ValueError):
                continue
            cid = entry.get('choice_id')
            if cid is None:
                continue
            counts.setdefault(tidx, {}).setdefault(cid, 0)
            counts[tidx][cid] += 1

    scenario = load_scenario(scenario_slug)
    turns: List[Dict[str, Any]] = []
    for tidx, turn in enumerate(scenario.get('turns', [])):
        turn_counts = counts.get(tidx, {})
        answered = sum(turn_counts.values())
        if not answered:
            continue
        choices = [
            {
                'choice_id': choice.get('id'),
                'label': choice.get('label', ''),
                'percent': round(100 * turn_counts.get(choice.get('id'), 0) / answered),
            }
            for choice in turn.get('choices', [])
        ]
        # Most-popular first so the bars read as a ranking.
        choices.sort(key=lambda c: c['percent'], reverse=True)
        turns.append({'turn_index': tidx, 'beat': turn.get('beat'), 'choices': choices})

    return {'sample_size': len(rows), 'turns': turns}


def _tally_cache_key(scenario_slug: str, day: date) -> str:
    return f'game:world:tally:{scenario_slug}:{day.isoformat()}'


def _cached_tally(scenario_slug: str, day: date) -> Dict[str, Any]:
    """``_compute_tally`` behind a short-TTL Redis cache (best-effort).

    Without Redis (e.g. tests) this is a straight pass-through, so behaviour is
    identical — just uncached.
    """
    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
    except Exception:  # noqa: BLE001 — never let cache wiring break the page
        client = None

    key = _tally_cache_key(scenario_slug, day)
    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001 — a cache miss/parse error is non-fatal
            logger.warning('world tally cache read failed', exc_info=True)

    tally = _compute_tally(scenario_slug, day)

    if client is not None:
        try:
            client.setex(key, _TALLY_CACHE_TTL_SECONDS, json.dumps(tally))
        except Exception:  # noqa: BLE001 — write failure is non-fatal
            logger.warning('world tally cache write failed', exc_info=True)
    return tally


def world_today(run: GameRun, *, min_n: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Aggregate how everyone played *this run's* scenario on its UTC day.

    Returns ``None`` for non-daily runs (no shared cohort). Below the privacy
    floor returns ``{'ready': False, 'sample_size': N}`` so the UI can stay quiet.
    The heavy distribution is cached per (scenario, day); only the cheap "is this
    your pick" overlay is computed per request.
    """
    if run.mode != 'daily' or not run.started_at:
        return None

    day = run.started_at.date()
    tally = _cached_tally(run.scenario_slug, day)
    sample_size = tally['sample_size']

    threshold = min_n if min_n is not None else cohort_min_n()
    if sample_size < threshold:
        return {'ready': False, 'sample_size': sample_size, 'scope': 'today'}

    yours = _player_choice_by_turn(run)
    turns: List[Dict[str, Any]] = []
    for turn in tally['turns']:
        tidx = turn['turn_index']
        choices = [
            {**choice, 'is_yours': yours.get(tidx) == choice['choice_id']}
            for choice in turn['choices']
        ]
        turns.append({'turn_index': tidx, 'beat': turn['beat'], 'choices': choices})

    return {
        'ready': True,
        'sample_size': sample_size,
        'scope': 'today',
        'turns': turns,
    }


def world_today_share_line(world: Optional[Dict[str, Any]]) -> Optional[str]:
    """One shareable line for the player's most contrarian moment, or None.

    Picks the turn where the player's own choice was the *least* popular —
    the most boast-worthy 'I went against the crowd' beat.
    """
    if not world or not world.get('ready'):
        return None

    from flask_babel import _

    best = None  # (percent, label)
    for turn in world['turns']:
        for choice in turn['choices']:
            if choice['is_yours']:
                if best is None or choice['percent'] < best[0]:
                    best = (choice['percent'], choice['label'])
    if best is None:
        return None

    percent, label = best
    # Only brag when the player was genuinely in the minority.
    if percent >= 50:
        return None
    return _('Only %(pct)d%% made the call you did: %(label)s', pct=percent, label=label)
