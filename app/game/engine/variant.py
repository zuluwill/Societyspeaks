"""Seeded per-play variation of a scenario's opening conditions.

A fixed library of authored scenarios still has to feel fresh on a daily loop.
Rather than vary the *narrative* (which would desync the shared-daily and cohort
comparisons), we vary only the **starting state**: the same crisis, inherited in
a different posture (deeper debt, thinner trust, a calmer or more brittle nation).
Because outcomes derive from the final state, a different opening cascades into a
genuinely different run — while every player who plays the *same scenario on the
same day* gets the *same* opening (the seed is date-derived), so daily cohorts
and friend challenges stay perfectly comparable.

Determinism is the contract: the same seed always yields the same opening state,
so a run's posture never shifts between turns or page loads.
"""

from __future__ import annotations

import random
import zlib
from datetime import date
from typing import Any, Dict, Optional

from flask_babel import gettext as _

from app.game.constants import STAT_ALL, STAT_HIDDEN

# How far the opening state may drift from the authored baseline. Conservative
# on purpose: enough to change the run's feel and reachable outcomes, not enough
# to flip a scenario's authored character.
DEFAULT_VISIBLE_BAND = 8
DEFAULT_HIDDEN_BAND = 10

# Below this absolute drift we don't bother telling the player anything changed.
_DESCRIPTOR_MIN_DELTA = 6


def daily_variant_seed(scenario_slug: str, day: date) -> int:
    """Stable per (scenario, UTC day) seed — identical for every player that day.

    Masked to ``0x7FFFFFFF`` so the value fits in a PostgreSQL ``INTEGER``
    column (signed 32-bit, max 2 147 483 647).  Fully deterministic: same
    inputs always produce the same seed.
    """
    key = f'{scenario_slug}:{day.isoformat()}'.encode('utf-8')
    return zlib.adler32(key) & 0x7FFFFFFF


def random_variant_seed() -> int:
    """Fresh seed for unbounded replay (Quick Run).

    Kept within ``[0, 0x7FFFFFFF]`` (PostgreSQL ``INTEGER`` max) so the value
    can be persisted without overflow.
    """
    return random.randint(0, 0x7FFFFFFF)


def apply_initial_variation(
    initial_state: Dict[str, Any],
    seed: Optional[int],
    *,
    visible_band: int = DEFAULT_VISIBLE_BAND,
    hidden_band: int = DEFAULT_HIDDEN_BAND,
) -> Dict[str, int]:
    """Return a deterministically jittered copy of ``initial_state``.

    Iterates ``STAT_ALL`` in fixed order so the RNG draw sequence — and thus the
    result — is identical for a given seed regardless of dict ordering. A ``None``
    seed returns the baseline unchanged (variation disabled / legacy runs).
    """
    base = {k: int(v) for k, v in (initial_state or {}).items()}
    if seed is None:
        return base

    rng = random.Random(seed)
    out = dict(base)
    for key in STAT_ALL:
        if key not in out:
            continue
        band = hidden_band if key in STAT_HIDDEN else visible_band
        jitter = rng.randint(-band, band)
        out[key] = max(0, min(100, out[key] + jitter))
    return out


def variation_descriptor(
    base_state: Dict[str, Any],
    varied_state: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """One legible line describing how this run's opening differs from baseline.

    Picks the single most-shifted stat so the player understands *why* a familiar
    crisis feels different this time. Returns ``None`` when the drift is trivial.
    """
    best_key = None
    best_delta = 0
    for key in STAT_ALL:
        if key not in base_state or key not in varied_state:
            continue
        delta = int(varied_state[key]) - int(base_state[key])
        if abs(delta) > abs(best_delta):
            best_delta = delta
            best_key = key

    if best_key is None or abs(best_delta) < _DESCRIPTOR_MIN_DELTA:
        return None

    direction = 'high' if best_delta > 0 else 'low'
    line = _LINES.get((best_key, direction))
    if not line:
        return None
    return {'stat': best_key, 'direction': direction, 'line': line()}


# Lazy callables so the gettext lookup happens under the request's locale, not at
# import time. Mirrors the pattern in cohort_service.axis_direction_label.
_LINES = {
    ('debt_stress', 'high'): lambda: _('You inherit this crisis already deep in debt.'),
    ('debt_stress', 'low'): lambda: _('The treasury starts in unusually good health.'),
    ('trust', 'high'): lambda: _('You begin with rare public goodwill.'),
    ('trust', 'low'): lambda: _('Public trust is thin before you even begin.'),
    ('stability', 'high'): lambda: _('You inherit a calm, stable nation.'),
    ('stability', 'low'): lambda: _('The country is volatile from day one.'),
    ('prosperity', 'high'): lambda: _('You begin with a strong economy.'),
    ('prosperity', 'low'): lambda: _('The economy is weak at the outset.'),
    ('fairness', 'high'): lambda: _('You inherit an unusually fair society.'),
    ('fairness', 'low'): lambda: _('Deep inequality greets you on arrival.'),
    ('autonomy', 'high'): lambda: _('Citizens begin with broad freedoms.'),
    ('autonomy', 'low'): lambda: _('Civil liberties are already constrained.'),
    ('future', 'high'): lambda: _('Past leaders invested well in the long term.'),
    ('future', 'low'): lambda: _('Little has been set aside for the long term.'),
    ('fragility', 'high'): lambda: _('The system is brittle before the first decision.'),
    ('fragility', 'low'): lambda: _('The system starts more resilient than usual.'),
}
