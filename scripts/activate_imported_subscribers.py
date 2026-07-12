#!/usr/bin/env python3
"""
Activate a batch of dormant imported subscribers (status 'imported' → 'active').

Deliverability ramp: dormant subscribers are flipped to active in small
batches while bounce/complaint rates are watched between batches (OPS.md →
"Subscriber segment sync & staged activation"). Only rows whose status is
exactly 'imported' are ever touched — unsubscribed/bounced/paused rows are
structurally out of reach.

Usage:
    DATABASE_URL=postgres://... python3 scripts/activate_imported_subscribers.py \
        --batch 250 [--source <label>] [--commit]
"""
import argparse
import os
import re
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--batch', type=int, required=True, help='number of subscribers to activate')
    ap.add_argument('--source', default=None, help='only activate rows with this source label')
    ap.add_argument('--commit', action='store_true',
                    help='apply changes (default: dry-run, transaction rolled back)')
    args = ap.parse_args()

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        sys.exit('DATABASE_URL is not set')
    if args.batch <= 0:
        sys.exit('--batch must be positive')
    if args.batch > 1000:
        sys.exit('--batch is capped at 1000: the ramp rules (OPS.md) require '
                 'checking bounce/complaint rates between batches of 250-500')
    if args.source and not re.fullmatch(r'[a-z0-9_]+', args.source):
        sys.exit('--source must be a lowercase slug (a-z, 0-9, _)')

    source_filter = f"AND source = '{args.source}'" if args.source else ''
    final = 'COMMIT' if args.commit else 'ROLLBACK'
    sql = f"""
\\set ON_ERROR_STOP on
BEGIN;
\\echo '--- activating (oldest imported rows first):'
WITH batch AS (
    SELECT id FROM daily_brief_subscriber
    WHERE status = 'imported' {source_filter}
    ORDER BY id
    LIMIT {args.batch}
),
upd AS (
    UPDATE daily_brief_subscriber s
    SET status = 'active'
    FROM batch b
    WHERE s.id = b.id AND s.status = 'imported'
    RETURNING s.country
)
SELECT coalesce(country, '(unknown)') AS country, count(*) FROM upd GROUP BY 1 ORDER BY 2 DESC;

\\echo '--- remaining dormant after this batch:'
SELECT count(*) AS still_imported FROM daily_brief_subscriber WHERE status = 'imported' {source_filter};
{final};
"""
    print(f"mode: {'COMMIT' if args.commit else 'DRY-RUN (rolled back)'}\n")
    result = subprocess.run(['psql', db_url, '-v', 'ON_ERROR_STOP=1'], input=sql, text=True)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
