"""Shared constants for the Daily Brief product.

Keep scheduling constants here — not inline — so email_client.py and
scheduler.py always agree on publication timing without silent drift.

Operational note: production brief sends (daily + weekly hourly jobs)
require REDIS_URL so distributed send locks can prevent duplicate mail
across multiple app workers. See BriefEmailScheduler in email_client.py.
"""

# Hour (UTC) at which the daily brief is auto-published.
# Morning subscribers (preferred_send_hour < BRIEF_PUBLISH_UTC_HOUR) receive
# yesterday's brief as a catch-up; evening subscribers receive today's fresh content.
# Scheduler `auto_publish_brief` imports this constant for the cron hour.
BRIEF_PUBLISH_UTC_HOUR = 18

# Valid subscriber-facing send hours. Must be kept in sync with the
# brief/routes.py form labels and dashboard.html subscribe form.
VALID_SEND_HOURS = [6, 7, 8, 9, 12, 17, 18, 19, 20]
DEFAULT_SEND_HOUR = 18

WEEKLY_DAY_NAMES = {
    0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday',
    4: 'Friday', 5: 'Saturday', 6: 'Sunday',
}
