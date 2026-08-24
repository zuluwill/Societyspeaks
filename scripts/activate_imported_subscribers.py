#!/usr/bin/env python3
"""
Activate a batch of dormant imported subscribers (status 'imported' → 'active').

Deliverability ramp: dormant subscribers are flipped to active in small
batches while bounce/complaint rates are watched between batches (OPS.md →
"Subscriber segment sync & staged activation"). Only rows whose status is
exactly 'imported' are ever touched — unsubscribed/bounced/paused rows are
structurally out of reach.

By default the batch excludes UTC/unknown timezones. Those leftovers still
receive 18:00 UTC; hold them until a real IANA timezone is backfilled.
Pass --include-utc only after that backfill.

Usage:
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
    ap.add_argument('--batch', type=int, required=True, help='number of subscribers to activate')
    ap.add_argument('--source', default=None, help='only activate rows with this source label')
    ap.add_argument('--commit', action='store_true',
                    help='apply changes (default: dry-run, transaction rolled back)')
    ap.add_argument(
        '--include-utc',
        action='store_true',
        help='also activate UTC/unknown-timezone leftovers (default: hold them)',
    )
    args = ap.parse_args()

    db_url = resolve_database_url()
    if not db_url:
        sys.exit('DATABASE_URL or NEON_OWNER_DATABASE_URL is not set')

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
            "\nNext: wait for two Europe/London send-days, then check bounce "
            "(<2%) and complaints (<0.1%) in email_event before the next "
            "batch of 250. Do not pass --include-utc until UTC leftovers "
            "have a real IANA timezone."
        )
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
