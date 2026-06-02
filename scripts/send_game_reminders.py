#!/usr/bin/env python3
"""
Game Reminder Email Script
==========================

Sends daily "today's scenario is live / keep your streak" nudges to players
whose next_send_at is due and who haven't yet played today's scenario.

Entry point for manual / cron runs. The core logic lives in
app/game/services/reminder_service.py and is also called by the APScheduler
job in app/scheduler.py — keeping the two entry points DRY.

Usage:
    python scripts/send_game_reminders.py

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
        logging.FileHandler('game_reminders.log'),
        logging.StreamHandler(sys.stdout),
    ],
)

from app import create_app, db
from app.game.services.reminder_service import send_due_game_reminders


def main():
    app = create_app()
    with app.app_context():
        try:
            results = send_due_game_reminders(db)
            print("\nGame Reminder Summary:")
            print(f"  Due:     {results['due']}")
            print(f"  Sent:    {results['sent']}")
            print(f"  Skipped: {results['skipped']}")
            print(f"  Paused:  {results['paused']}")
            print(f"  Errors:  {results['errors']}")
            sys.exit(1 if results['errors'] else 0)
        except Exception as e:
            print(f"Critical error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == '__main__':
    main()
