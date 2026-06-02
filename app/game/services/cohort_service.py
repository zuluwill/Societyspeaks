"""Aggregate percentiles of completed runs for the same scenario.

Returns axis-lean and outcome-rarity comparisons. Gated by
``GAME_COHORT_MIN_N`` so percentiles never leak from a small sample.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from flask_babel import _

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.models.game import GameRun, GameRunOutcome

_DEFAULT_MIN_N = 20

# Axis endpoints. trust_autonomy: 0 = Trust-led, 100 = Autonomy-led.
# prosperity_fairness: 0 = Prosperity-led, 100 = Fairness-led.
_AXIS_HIGH = {'trust_autonomy': 'autonomy', 'prosperity_fairness': 'fairness'}
_AXIS_LOW = {'trust_autonomy': 'trust', 'prosperity_fairness': 'prosperity'}


def cohort_min_n() -> int:
    """Privacy floor for any per-day aggregate (shared by daily_results_service)."""
    try:
        return int(current_app.config.get('GAME_COHORT_MIN_N', _DEFAULT_MIN_N))
    except Exception:  # noqa: BLE001 — config misconfig shouldn't break outcomes
        return _DEFAULT_MIN_N


# Back-compat private alias (kept so existing call sites stay untouched).
_min_n = cohort_min_n


def _pct_strictly_less(values: List[float], pivot: float) -> int:
    """Percent of ``values`` strictly less than ``pivot`` (0–100, rounded)."""
    if not values:
        return 0
    below = sum(1 for v in values if v < pivot)
    return round(100 * below / len(values))


def _pct_strictly_greater(values: List[float], pivot: float) -> int:
    if not values:
        return 0
    above = sum(1 for v in values if v > pivot)
    return round(100 * above / len(values))


def _scope_for(run: GameRun) -> str:
    """'today' for a dated daily run, else 'all' (broader sample)."""
    if run.mode == 'daily' and run.started_at:
        return 'today'
    return 'all'


def _cohort_rows(run: GameRun, scope: str) -> List[Tuple[Optional[float], Optional[float], Optional[str]]]:
    query = (
        db.session.query(
            GameRunOutcome.axis_trust_autonomy,
            GameRunOutcome.axis_prosperity_fairness,
            GameRunOutcome.outcome_category,
        )
        .join(GameRun, GameRunOutcome.run_id == GameRun.id)
        .filter(
            GameRun.scenario_slug == run.scenario_slug,
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
        )
    )
    if scope == 'today' and run.started_at:
        day = run.started_at.date()
        day_start = datetime.combine(day, time.min)
        day_end = day_start + timedelta(days=1)
        query = query.filter(
            GameRun.mode == 'daily',
            GameRun.started_at >= day_start,
            GameRun.started_at < day_end,
        )
    return query.all()


def _axis_line(
    rows: List[Tuple[Optional[float], Optional[float], Optional[str]]],
    ta: float,
    pf: float,
) -> Optional[Dict[str, Any]]:
    """Pick the more distinctive axis and express it as a percentile."""
    ta_vals = [r[0] for r in rows if r[0] is not None]
    pf_vals = [r[1] for r in rows if r[1] is not None]

    candidates: List[Tuple[float, str, float, List[float]]] = []
    if ta_vals:
        candidates.append((abs(ta - 50), 'trust_autonomy', ta, ta_vals))
    if pf_vals:
        candidates.append((abs(pf - 50), 'prosperity_fairness', pf, pf_vals))
    if not candidates:
        return None

    _deviation, axis_key, value, values = max(candidates, key=lambda c: c[0])
    if value >= 50:
        direction = _AXIS_HIGH[axis_key]
        percent = _pct_strictly_less(values, value)
    else:
        direction = _AXIS_LOW[axis_key]
        percent = _pct_strictly_greater(values, value)

    return {'direction': direction, 'more_than_percent': percent}


def cohort_comparison(run: GameRun, *, min_n: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Return aggregate comparison for a completed run, or ``None`` if no outcome.

    Below ``min_n`` returns ``{'ready': False, 'sample_size': N, 'scope': …}``
    so the UI can render a placeholder instead of a misleading percentile.
    """
    outcome = getattr(run, 'outcome', None)
    if not outcome:
        return None

    scope = _scope_for(run)
    rows = _cohort_rows(run, scope)
    sample_size = len(rows)
    threshold = min_n if min_n is not None else _min_n()

    if sample_size < threshold:
        return {'ready': False, 'sample_size': sample_size, 'scope': scope}

    ta = float(outcome.axis_trust_autonomy or 50.0)
    pf = float(outcome.axis_prosperity_fairness or 50.0)

    axis = _axis_line(rows, ta, pf)
    if axis:
        # Localise once here so the template and share line share one source.
        axis['label'] = axis_direction_label(axis['direction'])

    rarity = None
    if outcome.outcome_category:
        same = sum(1 for r in rows if r[2] == outcome.outcome_category)
        rarity = {
            'category': outcome.outcome_category,
            'percent': round(100 * same / sample_size),
        }

    return {
        'ready': True,
        'sample_size': sample_size,
        'scope': scope,
        'axis': axis,
        'rarity': rarity,
    }


def axis_direction_label(direction: Optional[str]) -> str:
    """Localised endpoint name for an axis direction."""
    labels = {
        'autonomy': _('Autonomy'),
        'trust': _('Trust'),
        'fairness': _('Fairness'),
        'prosperity': _('Prosperity'),
    }
    return labels.get(direction or '', direction or '')


def cohort_share_line(cohort: Optional[Dict[str, Any]]) -> Optional[str]:
    """One concise, shareable comparison line (or ``None`` when not ready)."""
    if not cohort or not cohort.get('ready'):
        return None
    rarity = cohort.get('rarity')
    if rarity and rarity.get('percent') is not None:
        return _('Only %(pct)d%% of leaders ended like you.', pct=rarity['percent'])
    axis = cohort.get('axis')
    if axis and axis.get('more_than_percent') is not None:
        return _(
            'More %(dir)s-led than %(pct)d%% of leaders.',
            dir=axis_direction_label(axis['direction']),
            pct=axis['more_than_percent'],
        )
    return None
