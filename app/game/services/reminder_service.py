"""Daily-play re-engagement reminders.

Single source of truth for subscribing players and sending due nudges. Called
by both the APScheduler job (app/scheduler.py) and the standalone CLI script
(scripts/send_game_reminders.py), keeping the two entry points DRY.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import or_

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.services.daily_service import daily_meta, utc_game_date
from app.game.services.identity_service import compute_daily_streak
from app.lib.time import utcnow_naive
from app.models.game import GameReminderSubscription, GameRun

logger = logging.getLogger(__name__)


def _normalise_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    email = email.strip().lower()
    return email or None


def _ownership_clauses(user_id: Optional[int], session_fingerprint: Optional[str]):
    clauses = []
    if user_id:
        clauses.append(GameRun.user_id == user_id)
    if session_fingerprint:
        clauses.append(GameRun.session_fingerprint == session_fingerprint)
    return clauses


def _played_on(day, *, user_id: Optional[int], session_fingerprint: Optional[str]) -> bool:
    """True if this visitor has a completed daily run started on ``day`` (UTC)."""
    ownership = _ownership_clauses(user_id, session_fingerprint)
    if not ownership:
        return False

    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    return (
        GameRun.query.filter(
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            GameRun.mode == 'daily',
            GameRun.started_at >= day_start,
            GameRun.started_at < day_end,
            or_(*ownership),
        )
        .limit(1)
        .first()
        is not None
    )


def _played_since(since: datetime, *, user_id: Optional[int], session_fingerprint: Optional[str]) -> bool:
    """True if this visitor completed a daily run on or after ``since`` (UTC)."""
    ownership = _ownership_clauses(user_id, session_fingerprint)
    if not ownership:
        return False
    return (
        GameRun.query.filter(
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            GameRun.mode == 'daily',
            GameRun.started_at >= since,
            or_(*ownership),
        )
        .limit(1)
        .first()
        is not None
    )


def subscribe_to_reminders(
    *,
    email: str,
    user_id: Optional[int] = None,
    session_fingerprint: Optional[str] = None,
    timezone_name: str = 'UTC',
    preferred_hour: int = 8,
) -> Optional[GameReminderSubscription]:
    """Create or re-activate a daily reminder subscription (idempotent by email).

    Returns the subscription, or ``None`` if no valid email was supplied.
    """
    email = _normalise_email(email)
    if not email or '@' not in email:
        return None

    try:
        hour = max(0, min(23, int(preferred_hour)))
    except (TypeError, ValueError):
        hour = 8

    sub = GameReminderSubscription.query.filter_by(email=email).first()
    if sub is None:
        sub = GameReminderSubscription(email=email)
        db.session.add(sub)

    if user_id:
        sub.user_id = user_id
    if session_fingerprint:
        sub.session_fingerprint = session_fingerprint
    sub.timezone = timezone_name or 'UTC'
    sub.preferred_hour = hour
    # Re-subscribing clears any prior pause/unsubscribe and the miss counter.
    sub.unsubscribed_at = None
    sub.unsubscribe_reason = None
    sub.consecutive_misses = 0
    sub.ensure_unsubscribe_token()
    sub.set_next_send_at()
    db.session.commit()
    return sub


def has_active_reminder(
    *,
    user_id: Optional[int] = None,
    session_fingerprint: Optional[str] = None,
    email: Optional[str] = None,
) -> bool:
    """True if this visitor already has a live reminder subscription."""
    clauses = []
    if user_id:
        clauses.append(GameReminderSubscription.user_id == user_id)
    if session_fingerprint:
        clauses.append(GameReminderSubscription.session_fingerprint == session_fingerprint)
    normalised = _normalise_email(email)
    if normalised:
        clauses.append(GameReminderSubscription.email == normalised)
    if not clauses:
        return False
    return (
        GameReminderSubscription.query.filter(
            GameReminderSubscription.unsubscribed_at.is_(None),
            or_(*clauses),
        )
        .limit(1)
        .first()
        is not None
    )


def unsubscribe(sub: GameReminderSubscription, *, reason: str = 'user') -> None:
    if sub and sub.is_active:
        sub.unsubscribed_at = utcnow_naive()
        sub.unsubscribe_reason = reason
        db.session.commit()


def send_due_game_reminders(db, *, limit: Optional[int] = None) -> Dict[str, int]:
    """Send a nudge to every active subscription whose ``next_send_at`` is due.

    Skips players who already played today (rescheduling silently), counts
    consecutive unopened nudges, and auto-pauses dormant inboxes.

    Returns a dict with keys: due, sent, skipped, paused, errors.
    """
    from app.resend_client import send_game_reminder_email

    now = utcnow_naive()
    query = GameReminderSubscription.query.filter(
        GameReminderSubscription.unsubscribed_at.is_(None),
        GameReminderSubscription.next_send_at.isnot(None),
        GameReminderSubscription.next_send_at <= now,
    ).order_by(GameReminderSubscription.next_send_at.asc())
    if limit:
        query = query.limit(limit)
    due = query.all()

    logger.info("Game reminders: %d subscription(s) due", len(due))
    sent = skipped = paused = errors = 0

    today = utc_game_date(now)
    meta = daily_meta(today)

    for sub in due:
        try:
            already_played = _played_on(
                today, user_id=sub.user_id, session_fingerprint=sub.session_fingerprint
            )
            if already_played:
                # Don't nag — they already showed up today.
                sub.consecutive_misses = 0
                sub.set_next_send_at(from_dt=now)
                db.session.commit()
                skipped += 1
                continue

            # "Engaged" = played at least once since the previous nudge fired.
            # Anchoring miss-counting to last_sent_at (instead of "played today")
            # avoids auto-pausing daily players whose play time is after the
            # nudge fires in their local timezone.
            engaged_since_last = bool(sub.last_sent_at) and _played_since(
                sub.last_sent_at,
                user_id=sub.user_id,
                session_fingerprint=sub.session_fingerprint,
            )

            streak = compute_daily_streak(
                user_id=sub.user_id, session_fingerprint=sub.session_fingerprint
            )

            success = send_game_reminder_email(sub, scenario_meta=meta, streak=streak)
            if not success:
                errors += 1
                logger.error("Failed to send game reminder → %s", sub.email)
                # Reschedule so a transient failure doesn't hot-loop.
                sub.set_next_send_at(from_dt=now)
                db.session.commit()
                continue

            sub.last_sent_at = now
            sub.reminder_count = (sub.reminder_count or 0) + 1
            if engaged_since_last:
                sub.consecutive_misses = 0
            else:
                sub.consecutive_misses = (sub.consecutive_misses or 0) + 1
            sub.set_next_send_at(from_dt=now)

            if sub.consecutive_misses >= GameReminderSubscription.MAX_CONSECUTIVE_MISSES:
                sub.unsubscribed_at = now
                sub.unsubscribe_reason = 'dormant'
                paused += 1
                logger.info("Auto-paused dormant game reminder → %s", sub.email)

            db.session.commit()
            sent += 1
            logger.info("Game reminder sent → %s (streak=%s)", sub.email, streak.get('current'))

        except Exception as exc:  # noqa: BLE001 — one bad row shouldn't stop the batch
            db.session.rollback()
            logger.error("Error processing game reminder %s: %s", sub.id, exc, exc_info=True)
            errors += 1

    result = {'due': len(due), 'sent': sent, 'skipped': skipped, 'paused': paused, 'errors': errors}
    logger.info("Game reminders complete — %s", result)
    return result
