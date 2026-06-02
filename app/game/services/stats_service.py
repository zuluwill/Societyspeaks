"""Global participation counters for hub social proof.

Cheap, slightly-stale counts ("12,438 societies governed · 320 today") that make
the hub feel alive and lower the activation barrier. Memoised briefly so the
count doesn't run on every single hub load.
"""

from __future__ import annotations

import time as _time
from datetime import datetime, time, timedelta
from typing import Dict

from flask import current_app

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.services.daily_service import utc_game_date
from app.models.game import GameRun

# Don't show "3 societies governed" — wait until the number reads as momentum.
_MIN_TOTAL_TO_SHOW = 50
_CACHE_TTL_SECONDS = 60

_cache: Dict[str, object] = {'at': 0.0, 'value': None}


def participation_stats() -> Dict[str, object]:
    """Return ``{'total', 'today', 'show'}`` for the hub, cached ~60s.

    ``show`` gates rendering so a brand-new deployment doesn't advertise a tiny
    count. Any DB hiccup degrades to ``show=False`` rather than breaking the hub.
    """
    now = _time.monotonic()
    cached = _cache.get('value')
    if cached is not None and (now - float(_cache['at'])) < _CACHE_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    try:
        total = (
            db.session.query(db.func.count(GameRun.id))
            .filter(GameRun.status == GAME_RUN_STATUS_COMPLETED)
            .scalar()
            or 0
        )
        day_start = datetime.combine(utc_game_date(), time.min)
        day_end = day_start + timedelta(days=1)
        today = (
            db.session.query(db.func.count(GameRun.id))
            .filter(
                GameRun.status == GAME_RUN_STATUS_COMPLETED,
                GameRun.started_at >= day_start,
                GameRun.started_at < day_end,
            )
            .scalar()
            or 0
        )
    except Exception:  # noqa: BLE001 — counters must never break the hub
        current_app.logger.exception('participation_stats query failed')
        result = {'total': 0, 'today': 0, 'show': False}
        return result

    result = {
        'total': int(total),
        'today': int(today),
        'show': int(total) >= _MIN_TOTAL_TO_SHOW,
    }
    _cache['at'] = now
    _cache['value'] = result
    return result
