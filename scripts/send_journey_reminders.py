#!/usr/bin/env python3
"""
Journey Reminder Email Script
==============================

Sends progress-based reminder emails to users who have subscribed to journey
reminders and whose next_send_at is due.

Entry point for manual / cron runs.  The core logic lives in
app/programmes/journey_reminders.py and is also called by the APScheduler
job in app/scheduler.py — keeping the two entry points DRY.

Usage:
    python scripts/send_journey_reminders.py

Safe to run manually for testing (respects ALLOW_EMAIL_IN_NON_PROD=1 override).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('journey_reminders.log'),
        logging.StreamHandler(sys.stdout),
    ],
)

from app import create_app, db
from app.programmes.journey_reminders import send_due_journey_reminders


def main():
    app = create_app()
    with app.app_context():
        try:
            results = send_due_journey_reminders(db)
            print("\nJourney Reminder Summary:")
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
