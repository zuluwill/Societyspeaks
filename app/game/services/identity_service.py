"""Game identity: anonymous-to-account merge + streak computation.

Plan §5.2: cross-session profile data depends on a stable identity. For
anonymous players that's a fingerprint (which can rotate). On login we walk
every fingerprint this browser has ever held and attach the matching runs to
the new account so signing up doesn't lose your societies.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.services.daily_service import utc_game_date
from app.models.game import GameRun


def ownership_clauses(user_id: Optional[int], session_fingerprint: Optional[str]):
    """SQLAlchemy clauses matching runs owned by a visitor (account or browser).

    Single source of truth for the account-OR-fingerprint ownership filter shared
    by the archive, profile, and reminder services. Combine with ``or_(*clauses)``.
    Returns ``[]`` when there's no identity, so callers can short-circuit.
    """
    clauses = []
    if user_id:
        clauses.append(GameRun.user_id == user_id)
    if session_fingerprint:
        clauses.append(GameRun.session_fingerprint == session_fingerprint)
    return clauses


def visitor_owns_run(
    run: GameRun,
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
) -> bool:
    """True when this visitor owns the run via account or browser fingerprint."""
    if user_id is not None and run.user_id == user_id:
        return True
    if session_fingerprint and run.session_fingerprint == session_fingerprint:
        return True
    return False


def merge_anonymous_game_runs(user_id: int, fingerprints: Iterable[str]) -> int:
    """Attach orphaned anonymous game_runs for these fingerprints to ``user_id``.

    Returns the number of rows updated. Idempotent: re-running with the same
    fingerprints is a no-op once they're owned by a user.
    """
    fps = [fp for fp in (fingerprints or []) if fp]
    if not fps:
        return 0
    updated = (
        GameRun.query.filter(
            GameRun.user_id.is_(None),
            GameRun.session_fingerprint.in_(fps),
        )
        .update({GameRun.user_id: user_id}, synchronize_session=False)
    )
    if updated:
        db.session.commit()
    return updated


def compute_daily_streak(
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
) -> Dict[str, Any]:
    """Walk completed daily runs back from today, counting consecutive UTC days.

    Plan §3.1: yesterday's daily is playable for 48h for streak grace; the
    streak counts a UTC day as covered if there's a completed daily run with
    ``started_at`` on that calendar day. Missing today doesn't break the
    streak until today ends — visit on day N+1 without playing N+1's daily and
    the streak resets next visit, not retroactively.
    """
    if not user_id and not session_fingerprint:
        return {'current': 0, 'longest': 0, 'last_played_date': None}

    from sqlalchemy import or_

    query = GameRun.query.filter(
        GameRun.status == GAME_RUN_STATUS_COMPLETED,
        GameRun.mode == 'daily',
    )
    ownership = []
    if user_id:
        ownership.append(GameRun.user_id == user_id)
    if session_fingerprint:
        ownership.append(GameRun.session_fingerprint == session_fingerprint)
    if ownership:
        query = query.filter(or_(*ownership))
    else:
        return {'current': 0, 'longest': 0, 'last_played_date': None}

    runs = query.order_by(GameRun.started_at.desc()).all()
    if not runs:
        return {'current': 0, 'longest': 0, 'last_played_date': None}

    played_dates = sorted({r.started_at.date() for r in runs if r.started_at}, reverse=True)
    if not played_dates:
        return {'current': 0, 'longest': 0, 'last_played_date': None}

    today = utc_game_date()
    last_played = played_dates[0]

    # Current streak: anchor on today if played, else on yesterday (48h grace).
    anchor = today if last_played == today else today - timedelta(days=1)
    if last_played < anchor:
        current = 0
    else:
        current = 0
        expected = last_played
        for day in played_dates:
            if day == expected:
                current += 1
                expected = expected - timedelta(days=1)
            elif day < expected:
                break

    longest = _longest_consecutive_run(played_dates)
    return {
        'current': current,
        'longest': max(longest, current),
        'last_played_date': last_played,
    }


def _longest_consecutive_run(dates_desc: List) -> int:
    """Longest streak of consecutive UTC days across all completed dailies."""
    if not dates_desc:
        return 0
    asc = sorted(dates_desc)
    longest = 1
    current = 1
    for i in range(1, len(asc)):
        if (asc[i] - asc[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def player_has_game_history(
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
) -> bool:
    """True when this identity has any in-progress or completed run (daily or quick)."""
    from app.game.constants import (
        GAME_RUN_STATUS_COMPLETED,
        GAME_RUN_STATUS_IN_PROGRESS,
    )

    if not user_id and not session_fingerprint:
        return False

    from sqlalchemy import or_

    query = GameRun.query.filter(
        GameRun.status.in_([GAME_RUN_STATUS_COMPLETED, GAME_RUN_STATUS_IN_PROGRESS])
    )
    ownership = []
    if user_id:
        ownership.append(GameRun.user_id == user_id)
    if session_fingerprint:
        ownership.append(GameRun.session_fingerprint == session_fingerprint)
    if not ownership:
        return False
    return query.filter(or_(*ownership)).limit(1).first() is not None
