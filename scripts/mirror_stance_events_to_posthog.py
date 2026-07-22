#!/usr/bin/env python3
"""Backfill ``email_vote_confirmed`` events from Neon to PostHog via the reconciler.

Live vote POSTs enqueue best-effort events; ``posthog_confirmed_mirrored_at`` is
stamped only by :func:`reconcile_unmirrored_email_votes_to_posthog` (also run
every 15 minutes on the scheduler worker). Idempotent via PostHog ``$insert_id``.

Usage:
  Dry-run (default):
    python3 -m scripts.mirror_stance_events_to_posthog

  Apply:
    python3 -m scripts.mirror_stance_events_to_posthog --apply

  Limit scope:
    python3 -m scripts.mirror_stance_events_to_posthog --apply --days 30 --limit 500
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.daily.vote_analytics import reconcile_unmirrored_email_votes_to_posthog
from app.lib.time import utcnow_naive


def mirror_stance_events(
    *,
    apply: bool = False,
    days: int = 30,
    limit: int = 1000,
) -> None:
    app = create_app()
    with app.app_context():
        cutoff = utcnow_naive() - __import__('datetime').timedelta(days=days)
        if not apply:
            from app.models import DailyQuestionResponse

            pending = (
                DailyQuestionResponse.query.filter(
                    DailyQuestionResponse.voted_via_email.is_(True),
                    DailyQuestionResponse.posthog_confirmed_mirrored_at.is_(None),
                    DailyQuestionResponse.created_at >= cutoff,
                )
                .count()
            )
            print(f'DRY-RUN: up to {min(pending, limit)} unmirrored response(s) since {cutoff.date()}')
            print('Re-run with --apply to reconcile via the scheduled reconciler path.')
            return

        stats = reconcile_unmirrored_email_votes_to_posthog(days=days, limit=limit)
        if stats['candidates'] == 0:
            print('No unmirrored email-confirmed responses in scope.')
            return
        if stats['skipped_no_identity']:
            print(
                f"NOTE: {stats['skipped_no_identity']} row(s) have no stored posthog_distinct_id "
                '(voted before the audit column shipped) and cannot be mirrored — '
                'their identity is unrecoverable, so PostHog will stay below Neon for those.'
            )
        print(
            f"Mirrored {stats['mirrored']}/{stats['candidates']} response(s) to PostHog "
            f"({stats['failed']} failed enqueue)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Send events to PostHog')
    parser.add_argument('--days', type=int, default=30, help='Lookback window (default 30)')
    parser.add_argument('--limit', type=int, default=1000, help='Max rows per run')
    args = parser.parse_args()
    mirror_stance_events(apply=args.apply, days=args.days, limit=args.limit)


if __name__ == '__main__':
    main()
