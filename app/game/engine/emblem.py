"""Procedural emblem — seed-based while in progress, axis-derived once complete."""

from __future__ import annotations

import hashlib
from typing import Any, Dict


def _accent_pair(hue: int) -> Dict[str, str]:
    return {
        'accent': f'hsl({hue % 360}, 55%, 58%)',
        'accent_soft': f'hsla({hue % 360}, 45%, 48%, 0.35)',
    }


def emblem_style(seed: str) -> Dict[str, Any]:
    """Deterministic colour + shape from seed alone."""
    digest = hashlib.sha256((seed or '').encode()).hexdigest()
    hue = int(digest[:2], 16) % 360
    shape = int(digest[2:3], 16) % 4
    style: Dict[str, Any] = {'shape': shape}
    style.update(_accent_pair(hue))
    return style


def _seed_jitter(seed: str, span: int = 30) -> int:
    digest = hashlib.sha256((seed or '').encode()).hexdigest()
    return (int(digest[:2], 16) % span) - (span // 2)


def emblem_for_run(run: Any) -> Dict[str, Any]:
    """Shape from axis quadrant, hue from precise landing, jittered by seed.

    Falls back to ``emblem_style(seed)`` for runs without an outcome.
    """
    outcome = getattr(run, 'outcome', None)
    seed = getattr(run, 'emblem_seed', None) or getattr(run, 'uuid', '') or ''
    if not outcome:
        return emblem_style(seed)

    ta = float(getattr(outcome, 'axis_trust_autonomy', None) or 50.0)
    pf = float(getattr(outcome, 'axis_prosperity_fairness', None) or 50.0)

    shape = (1 if ta >= 50 else 0) + (2 if pf >= 50 else 0)
    base_hue = ta * 2.4 + pf * 0.9
    hue = int(base_hue + _seed_jitter(seed)) % 360

    style: Dict[str, Any] = {'shape': shape}
    style.update(_accent_pair(hue))
    return style
