#!/usr/bin/env python3
"""
Activate a batch of dormant imported subscribers (status 'imported' → 'active').

Deliverability ramp: dormant subscribers are flipped to active in small
batches while bounce/complaint rates are watched between batches (OPS.md →
"Subscriber segment sync & staged activation"). Only rows whose status is
exactly 'imported' are ever touched — unsubscribed/bounced/paused rows are
structurally out of reach.

Cadence: one batch of 250 per send-day, after a green morning kill-switch.
Never stack two first-send batches on the same night (that pushes domain
bounce toward 2% and can hurt the existing list).

By default the batch excludes UTC/unknown timezones. Those leftovers still
receive 18:00 UTC; hold them until a real IANA timezone is backfilled.
Pass --include-utc only after that backfill.

Usage:
    DATABASE_URL=postgres://... python3 scripts/activate_imported_subscribers.py \
        --status [--source <label>]
    DATABASE_URL=postgres://... python3 scripts/activate_imported_subscribers.py \
        --batch 250 [--source <label>] [--commit]
"""
import argparse
import os
import re
import subprocess
import sys

SOURCE_RE = re.compile(r'^[a-z0-9_]+$')
MAX_BATCH = 1000
# Refuse --commit when this many never-sent actives are already waiting.
# One 250-batch in tonight's wave is the plan; a second would stack first-send
# bounce (~14%) and can push the domain bounce rate onto the 2% kill-switch.
STACKING_GUARD = 100

# Real IANA zones have a region/city slash. UTC/GMT leftovers are held.
REAL_TZ_SQL = (
    "AND timezone IS NOT NULL "
    "AND btrim(timezone) <> '' "
    "AND timezone NOT IN ('UTC', 'GMT', 'Etc/UTC') "
    "AND timezone LIKE '%/%'"
)

# Never activate an address Resend (or we) already know is undeliverable.
KNOWN_BAD_EMAIL_SQL = """
    AND NOT EXISTS (
        SELECT 1 FROM email_event e
        WHERE lower(e.recipient_email) = lower(daily_brief_subscriber.email)
          AND (
            e.event_type IN ('complained', 'suppressed')
            OR (
                e.event_type = 'bounced'
                AND lower(coalesce(e.bounce_type, '')) IN ('hard', 'permanent')
            )
          )
    )"""


def resolve_database_url():
    """Owner URL required: the dry-run still issues UPDATE inside a rolled-back txn."""
    return os.environ.get('DATABASE_URL') or os.environ.get('NEON_OWNER_DATABASE_URL')


NEVER_SENT_WAITING_SQL = """
SELECT count(*) FROM daily_brief_subscriber
WHERE status = 'active'
  AND last_sent_at IS NULL
  AND coalesce(total_briefs_received, 0) = 0;
"""


def stacking_would_hurt(waiting, guard=STACKING_GUARD):
    return waiting >= guard


def build_status_sql(source=None):
    if source and not SOURCE_RE.fullmatch(source):
        raise ValueError('--source must be a lowercase slug (a-z, 0-9, _)')
    source_filter = f"AND source = '{source}'" if source else ''
    return f"""
\\set ON_ERROR_STOP on
\\echo '--- kill-switch (last full Europe/London send-day):'
SELECT
  (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/London')::date AS london_day,
  count(DISTINCT recipient_email) FILTER (WHERE event_type = 'sent') AS sent_u,
  round(100.0 * count(DISTINCT recipient_email) FILTER (WHERE event_type = 'bounced')
    / nullif(count(DISTINCT recipient_email) FILTER (WHERE event_type = 'sent'), 0), 2) AS bounce_pct,
  round(100.0 * count(DISTINCT recipient_email) FILTER (WHERE event_type = 'complained')
    / nullif(count(DISTINCT recipient_email) FILTER (WHERE event_type = 'delivered'), 0), 3) AS complaint_pct,
  round(100.0 * count(DISTINCT recipient_email) FILTER (WHERE event_type = 'opened')
    / nullif(count(DISTINCT recipient_email) FILTER (WHERE event_type = 'delivered'), 0), 1) AS open_pct
FROM email_event
WHERE email_category = 'daily_brief'
  AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/London')::date
      = (current_date AT TIME ZONE 'Europe/London' - interval '1 day')::date
GROUP BY 1;

\\echo '--- never-sent actives waiting for tonight (do not stack if this is ~250):'
SELECT count(*) AS never_sent_waiting
FROM daily_brief_subscriber
WHERE status = 'active'
  AND last_sent_at IS NULL
  AND coalesce(total_briefs_received, 0) = 0;

\\echo '--- remaining imported:'
SELECT
    count(*) FILTER (
        WHERE timezone IS NOT NULL
          AND btrim(timezone) <> ''
          AND timezone NOT IN ('UTC', 'GMT', 'Etc/UTC')
          AND timezone LIKE '%/%'
    ) AS tz_ready_still_imported,
    count(*) FILTER (
        WHERE timezone IS NULL
           OR btrim(timezone) = ''
           OR timezone IN ('UTC', 'GMT', 'Etc/UTC')
           OR timezone NOT LIKE '%/%'
    ) AS utc_or_unknown_still_imported,
    count(*) AS still_imported
FROM daily_brief_subscriber
WHERE status = 'imported' {source_filter};
"""


def never_sent_waiting_count(db_url):
    result = subprocess.run(
        ['psql', db_url, '-t', '-A', '-v', 'ON_ERROR_STOP=1'],
        input=NEVER_SENT_WAITING_SQL,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'failed to count never-sent actives')
    return int((result.stdout or '0').strip() or '0')


def build_activation_sql(batch, source=None, commit=False, include_utc=False):
    if batch <= 0:
        raise ValueError('--batch must be positive')
    if batch > MAX_BATCH:
        raise ValueError(
            '--batch is capped at 1000: the ramp rules (OPS.md) require '
            'checking bounce/complaint rates between batches of 250-500'
        )
    if source and not SOURCE_RE.fullmatch(source):
        raise ValueError('--source must be a lowercase slug (a-z, 0-9, _)')

    source_filter = f"AND source = '{source}'" if source else ''
    tz_filter = '' if include_utc else f'\n    {REAL_TZ_SQL}'
    bad_filter = KNOWN_BAD_EMAIL_SQL
    final = 'COMMIT' if commit else 'ROLLBACK'
    return f"""
\\set ON_ERROR_STOP on
BEGIN;
\\echo '--- activating (oldest imported rows first; real IANA timezone unless --include-utc):'
WITH batch AS (
    SELECT id FROM daily_brief_subscriber
    WHERE status = 'imported' {source_filter}{tz_filter}{bad_filter}
    ORDER BY id
    LIMIT {batch}
),
upd AS (
    UPDATE daily_brief_subscriber s
    SET status = 'active'
    FROM batch b
    WHERE s.id = b.id AND s.status = 'imported'
    RETURNING
        coalesce(nullif(btrim(s.country), ''), '(unknown)') AS country,
        coalesce(nullif(btrim(s.timezone), ''), '(unknown)') AS timezone,
        coalesce(s.cadence, 'daily') AS cadence,
        coalesce(s.preferred_send_hour, 18) AS send_hour
)
SELECT dim, value, n FROM (
    SELECT 'country' AS dim, country AS value, count(*)::int AS n FROM upd GROUP BY 1, 2
    UNION ALL
    SELECT 'timezone', timezone, count(*)::int FROM upd GROUP BY 1, 2
    UNION ALL
    SELECT 'cadence', cadence, count(*)::int FROM upd GROUP BY 1, 2
    UNION ALL
    SELECT 'send_hour', send_hour::text, count(*)::int FROM upd GROUP BY 1, 2
) mix
ORDER BY dim, n DESC, value;

\\echo '--- remaining imported after this batch:'
SELECT
    count(*) FILTER (
        WHERE timezone IS NOT NULL
          AND btrim(timezone) <> ''
          AND timezone NOT IN ('UTC', 'GMT', 'Etc/UTC')
          AND timezone LIKE '%/%'
    ) AS tz_ready_still_imported,
    count(*) FILTER (
        WHERE timezone IS NULL
           OR btrim(timezone) = ''
           OR timezone IN ('UTC', 'GMT', 'Etc/UTC')
           OR timezone NOT LIKE '%/%'
    ) AS utc_or_unknown_still_imported,
    count(*) AS still_imported
FROM daily_brief_subscriber
WHERE status = 'imported' {source_filter};
{final};
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--batch', type=int, default=None, help='number of subscribers to activate')
    ap.add_argument('--source', default=None, help='only activate rows with this source label')
    ap.add_argument('--commit', action='store_true',
                    help='apply changes (default: dry-run, transaction rolled back)')
    ap.add_argument(
        '--include-utc',
        action='store_true',
        help='also activate UTC/unknown-timezone leftovers (default: hold them)',
    )
    ap.add_argument(
        '--status',
        action='store_true',
        help='print kill-switch, waiting first-sends, and remaining imported; do not activate',
    )
    args = ap.parse_args()

    db_url = resolve_database_url()
    if not db_url:
        sys.exit('DATABASE_URL or NEON_OWNER_DATABASE_URL is not set')

    if args.status:
        try:
            sql = build_status_sql(source=args.source)
        except ValueError as exc:
            sys.exit(str(exc))
        result = subprocess.run(['psql', db_url, '-v', 'ON_ERROR_STOP=1'], input=sql, text=True)
        sys.exit(result.returncode)

    if args.batch is None:
        sys.exit('--batch is required unless --status')

    if args.commit:
        try:
            waiting = never_sent_waiting_count(db_url)
        except RuntimeError as exc:
            sys.exit(str(exc))
        if stacking_would_hurt(waiting):
            sys.exit(
                f'Refusing --commit: {waiting} never-sent actives are already '
                f'waiting for tonight\'s send. Stacking another first-send '
                f'batch would push domain bounce toward 2% and can hurt the '
                f'existing list. Wait until after that send, then check the '
                f'kill-switch.'
            )

    try:
        sql = build_activation_sql(
            args.batch,
            source=args.source,
            commit=args.commit,
            include_utc=args.include_utc,
        )
    except ValueError as exc:
        sys.exit(str(exc))

    mode = 'COMMIT' if args.commit else 'DRY-RUN (rolled back)'
    tz_mode = 'including UTC leftovers' if args.include_utc else 'real IANA timezone only'
    print(f"mode: {mode}")
    print(f"timezone: {tz_mode}\n")
    result = subprocess.run(['psql', db_url, '-v', 'ON_ERROR_STOP=1'], input=sql, text=True)
    if result.returncode == 0 and args.commit:
        print(
            "\nNext: one batch of 250 per send-day. Tomorrow morning, run "
            "--status; if bounce <2%, complaints <0.1%, and existing-list "
            "opens have not sagged, activate the next 250. Do not pass "
            "--include-utc until UTC leftovers have a real IANA timezone. "
            "Do not stack two first-send batches on the same night."
        )
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
