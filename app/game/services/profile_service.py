"""Your governing self — cumulative tendencies across a visitor's runs.

A civic mirror: across every society you've governed, which values do you
consistently protect, and which do you trade away? Aggregates completed runs
(account + browser fingerprint) into a shareable identity, reusing the archive
ownership pattern and cohort_service's axis labels (DRY).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from flask_babel import _
from sqlalchemy import or_

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.services.cohort_service import axis_direction_label
from app.game.services.identity_service import ownership_clauses
from app.models.game import GameRun, GameRunOutcome

# Below this, "tendencies" are noise — show counts but not a confident identity.
MIN_RUNS_FOR_TENDENCIES = 3

_CATEGORY_LABELS = {
    'spectacular_collapse': lambda: _('Spectacular collapse'),
    'accidental_dystopia': lambda: _('Accidental dystopia'),
    'ironic_success': lambda: _('Ironic success'),
    'ironic_failure': lambda: _('Ironic failure'),
    'collapse': lambda: _('Collapse'),
    'unexpected_utopia': lambda: _('Unexpected utopia'),
    'mixed_legacy': lambda: _('Mixed legacy'),
}


def outcome_category_label(category: Optional[str]) -> str:
    fn = _CATEGORY_LABELS.get(category or '')
    return fn() if fn else (category or '').replace('_', ' ').strip().capitalize()


def compute_player_profile(
    *, user_id: Optional[int], session_fingerprint: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Aggregate this visitor's completed runs into a governing profile.

    Returns ``None`` when there's no identity, or a dict (possibly with
    ``has_enough=False`` when the sample is too small to characterise).
    """
    ownership = ownership_clauses(user_id, session_fingerprint)
    if not ownership:
        return None

    rows = (
        db.session.query(
            GameRun.scenario_slug,
            GameRunOutcome.axis_trust_autonomy,
            GameRunOutcome.axis_prosperity_fairness,
            GameRunOutcome.governance_label,
            GameRunOutcome.outcome_category,
            GameRunOutcome.trait_chips_json,
        )
        .join(GameRunOutcome, GameRunOutcome.run_id == GameRun.id)
        .filter(GameRun.status == GAME_RUN_STATUS_COMPLETED, or_(*ownership))
        .all()
    )

    total = len(rows)
    if total == 0:
        return {'total': 0, 'has_enough': False, 'distinct_scenarios': 0}

    distinct_scenarios = len({r[0] for r in rows})
    ta_vals = [float(r[1]) for r in rows if r[1] is not None]
    pf_vals = [float(r[2]) for r in rows if r[2] is not None]

    governance = Counter(r[3] for r in rows if r[3])
    categories = Counter(r[4] for r in rows if r[4])
    traits: Counter = Counter()
    for r in rows:
        for chip in (r[5] or []):
            if chip:
                traits[chip] += 1

    has_enough = total >= MIN_RUNS_FOR_TENDENCIES

    lean = None
    if has_enough and ta_vals and pf_vals:
        avg_ta = sum(ta_vals) / len(ta_vals)
        avg_pf = sum(pf_vals) / len(pf_vals)
        lean = {
            'trust_autonomy': _lean_entry(avg_ta, 'autonomy', 'trust'),
            'prosperity_fairness': _lean_entry(avg_pf, 'fairness', 'prosperity'),
        }

    outcome_breakdown = [
        {
            'category': cat,
            'label': outcome_category_label(cat),
            'count': n,
            'percent': round(100 * n / total),
        }
        for cat, n in categories.most_common(4)
    ]

    return {
        'total': total,
        'distinct_scenarios': distinct_scenarios,
        'has_enough': has_enough,
        'lean': lean,
        'top_governance': governance.most_common(1)[0][0] if governance else None,
        'signature_traits': [t for t, _n in traits.most_common(3)],
        'outcome_breakdown': outcome_breakdown,
    }


def _lean_entry(avg: float, high_dir: str, low_dir: str) -> Dict[str, Any]:
    """Express an average axis value as a leaning toward one endpoint."""
    direction = high_dir if avg >= 50 else low_dir
    # Distance from centre → how pronounced the lean is (0–50 → 0–100%).
    strength = round(min(100, abs(avg - 50) * 2))
    return {
        'value': round(avg, 1),
        'direction': direction,
        'label': axis_direction_label(direction),
        'strength': strength,
    }
