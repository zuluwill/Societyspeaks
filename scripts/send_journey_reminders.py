#!/usr/bin/env python3
"""
Journey Reminder Email Script
==============================

Sends progress-based reminder emails to users who have subscribed to journey
reminders and whose next_send_at is due.

Mirrors the structure of weekly_digest.py and runs as a standalone script or
via the APScheduler job in app/scheduler.py.

Usage:
    python scripts/send_journey_reminders.py

Safe to run manually for testing (respects ALLOW_EMAIL_IN_NON_PROD=1 override).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import JourneyReminderSubscription, Programme
from app.programmes.journey import (
    build_journey_progress,
    is_guided_journey_programme,
    ordered_journey_discussions,
)
from app.resend_client import send_journey_reminder_email
from app.lib.time import utcnow_naive
import logging


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('journey_reminders.log'),
            logging.StreamHandler(sys.stdout),
        ],
    )


def send_due_journey_reminders():
    app = create_app()
    with app.app_context():
        setup_logging()
        logger = logging.getLogger(__name__)

        now = utcnow_naive()
        due = JourneyReminderSubscription.query.filter(
            JourneyReminderSubscription.unsubscribed_at.is_(None),
            JourneyReminderSubscription.next_send_at <= now,
            JourneyReminderSubscription.reminder_count < JourneyReminderSubscription.MAX_REMINDERS,
        ).all()

        logger.info(f"Found {len(due)} journey reminder subscription(s) due")
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
                    logger.info(f"Unsubscribed {sub.email} — journey complete")
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
                    logger.info(f"Reminder sent to {sub.email} ({programme.slug})")
                else:
                    errors += 1
                    logger.error(f"Failed to send reminder to {sub.email}")

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error processing subscription {sub.id}: {e}", exc_info=True)
                errors += 1

        logger.info(
            f"Journey reminders complete — sent: {sent}, skipped: {skipped}, errors: {errors}"
        )
        return {'due': len(due), 'sent': sent, 'skipped': skipped, 'errors': errors}


def main():
    try:
        results = send_due_journey_reminders()
        print(f"\nJourney Reminder Summary:")
        print(f"  Due:     {results['due']}")
        print(f"  Sent:    {results['sent']}")
        print(f"  Skipped: {results['skipped']}")
        print(f"  Errors:  {results['errors']}")
        sys.exit(1 if results['errors'] else 0)
    except Exception as e:
        print(f"Critical error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
