"""
Journey Reminder Send Logic
============================

Single source of truth for sending due journey reminder emails.
Called by both the APScheduler job (app/scheduler.py) and the
standalone CLI script (scripts/send_journey_reminders.py).

Extracting this here keeps the two entry points DRY and makes the
logic independently testable.
"""

import logging
from app.lib.time import utcnow_naive

logger = logging.getLogger(__name__)


def send_due_journey_reminders(db, app_context=True):
    """
    Query all due journey reminder subscriptions and send each one.

    Args:
        db: SQLAlchemy db instance (passed in to avoid circular imports)
        app_context: unused; retained for call-site compatibility

    Returns:
        dict with keys: due, sent, skipped, errors
    """
    from app.models import JourneyReminderSubscription, Programme
    from app.programmes.journey import (
        build_journey_progress,
        is_guided_journey_programme,
        ordered_journey_discussions,
    )
    from app.resend_client import send_journey_reminder_email

    now = utcnow_naive()
    due = JourneyReminderSubscription.query.filter(
        JourneyReminderSubscription.unsubscribed_at.is_(None),
        JourneyReminderSubscription.next_send_at <= now,
        JourneyReminderSubscription.reminder_count < JourneyReminderSubscription.MAX_REMINDERS,
    ).all()

    logger.info(f"Journey reminders: {len(due)} subscription(s) due")
    sent = errors = skipped = 0

    for sub in due:
        try:
            programme = db.session.get(Programme, sub.programme_id)
            if not programme or not is_guided_journey_programme(programme):
                sub.unsubscribed_at = now
                db.session.commit()
                skipped += 1
                continue

            ordered = ordered_journey_discussions(programme)
            progress = build_journey_progress(programme, sub.user_id, discussions=ordered)

            if progress.is_journey_complete:
                sub.unsubscribed_at = now
                db.session.commit()
                logger.info(f"Auto-unsubscribed {sub.email} ({programme.slug}) — journey complete")
                skipped += 1
                continue

            if not progress.next_item:
                skipped += 1
                continue

            theme_checklist = [
                {
                    'name': item.discussion.programme_theme or item.discussion.title,
                    'is_complete': item.is_complete,
                }
                for item in progress.theme_items
            ]

            success = send_journey_reminder_email(
                subscription=sub,
                programme=programme,
                next_discussion=progress.next_item.discussion,
                theme_checklist=theme_checklist,
                completed_themes=progress.completed_themes,
                total_themes=progress.total_themes,
            )

            if success:
                sub.last_sent_at = now
                sub.reminder_count = (sub.reminder_count or 0) + 1
                sub.set_next_send_at(from_dt=now)
                db.session.commit()
                sent += 1
                logger.info(f"Journey reminder sent → {sub.email} ({programme.slug})")
            else:
                errors += 1
                logger.error(f"Failed to send journey reminder → {sub.email} ({programme.slug})")

        except Exception as e:
            db.session.rollback()
            logger.error(
                f"Error processing journey reminder subscription {sub.id}: {e}",
                exc_info=True,
            )
            errors += 1

    logger.info(
        f"Journey reminders complete — sent: {sent}, skipped: {skipped}, errors: {errors}"
    )
    return {'due': len(due), 'sent': sent, 'skipped': skipped, 'errors': errors}
