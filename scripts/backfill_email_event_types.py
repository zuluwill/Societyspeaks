#!/usr/bin/env python3
"""
Backfill legacy email event types to normalized values.

Legacy rows may contain values like "email.opened". Current analytics expects
"opened" (without prefix). This script normalizes historical data in-place.

Usage:
  Dry-run (safe default):
    python -m scripts.backfill_email_event_types

  Apply changes:
    python -m scripts.backfill_email_event_types --apply

  Apply with custom batching:
    python -m scripts.backfill_email_event_types --apply --batch-size 2000
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import EmailEvent


def backfill_email_event_types(apply: bool = False, batch_size: int = 1000) -> None:
    """
    Normalize EmailEvent.event_type values.

    Args:
        apply: If True, persists changes. Otherwise prints a dry-run report.
        batch_size: Number of updates to commit per transaction when applying.
    """
    app = create_app()

    with app.app_context():
        total_rows = EmailEvent.query.count()
        if total_rows == 0:
            print("No EmailEvent rows found. Nothing to backfill.")
            return

        updated = 0
        scanned = 0
        pending_since_commit = 0
        mappings = defaultdict(int)

        print(f"Scanning {total_rows} email events...")

        query = EmailEvent.query.order_by(EmailEvent.id.asc()).yield_per(batch_size)
        for event in query:
            scanned += 1
            original = event.event_type or ""
            normalized = EmailEvent.normalize_event_type(original)

            if original != normalized:
                mappings[(original, normalized)] += 1
                updated += 1

                if apply:
                    event.event_type = normalized
                    pending_since_commit += 1

                    if pending_since_commit >= batch_size:
                        db.session.commit()
                        print(f"Committed {updated} updates (scanned {scanned}/{total_rows})")
                        pending_since_commit = 0

        if apply:
            if pending_since_commit > 0:
                db.session.commit()
            print(f"\nBackfill complete. Updated {updated} rows out of {total_rows}.")
        else:
            db.session.rollback()
            print(f"\nDry-run complete. Would update {updated} rows out of {total_rows}.")

        if mappings:
            print("\nNormalization mappings:")
            for (old_value, new_value), count in sorted(mappings.items(), key=lambda x: x[1], reverse=True):
                print(f"  {old_value!r} -> {new_value!r}: {count}")
        else:
            print("\nNo rows require normalization.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize legacy email event types in EmailEvent.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes to the database (default is dry-run).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Rows per transaction when --apply is set (default: 1000).",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    backfill_email_event_types(apply=args.apply, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
