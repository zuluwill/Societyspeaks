#!/usr/bin/env python3
"""
One-time PostHog cleanup: merge legacy prefixed game distinct_ids into the
canonical identity.

Historically, server-side game events used distinct_id ``user:<id>`` for
logged-in players, while the JS SDK (and every other server event) used the
plain ``<id>`` from ``identify('<id>')``. Those never stitched. The code now
emits the plain id; this script retroactively merges the old prefixed profile
into the canonical one via ``alias`` so historical game events join the right
person.

Only logged-in players are aliased — anonymous ``anon:<fingerprint>`` events
have no matching JS profile (JS uses random UUIDs), so they are intentionally
left alone (see the conversation / PostHog guidance).

Candidate user ids are discovered from ``GameRun.user_id`` (the rows that
produced ``user:<id>`` events). You may also pass explicit ids.

Usage:
  Dry-run (safe default) — prints the alias pairs it *would* send:
    python -m scripts.posthog_alias_legacy_game_ids

  Apply (sends alias events to PostHog and flushes):
    python -m scripts.posthog_alias_legacy_game_ids --apply

  Restrict to specific user ids:
    python -m scripts.posthog_alias_legacy_game_ids --apply --ids 14 21 37

Requires POSTHOG_API_KEY (and optionally POSTHOG_HOST) in the environment.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.game import GameRun


def _candidate_user_ids() -> list[int]:
    """User ids that have at least one game run (i.e. emitted user:<id> events)."""
    rows = (
        db.session.query(GameRun.user_id)
        .filter(GameRun.user_id.isnot(None))
        .distinct()
        .all()
    )
    return sorted(uid for (uid,) in rows)


def alias_legacy_game_ids(apply: bool = False, ids: list[int] | None = None) -> None:
    app = create_app()
    with app.app_context():
        user_ids = ids if ids else _candidate_user_ids()
        if not user_ids:
            print("No logged-in game players found. Nothing to alias.")
            return

        print(f"{'APPLYING' if apply else 'DRY-RUN'}: {len(user_ids)} user id(s)")
        for uid in user_ids:
            previous_id = f"user:{uid}"
            canonical_id = str(uid)
            print(f"  alias previous_id={previous_id!r} -> distinct_id={canonical_id!r}")

        if not apply:
            print("\nDry-run only. Re-run with --apply to send these aliases.")
            return

        import posthog

        api_key = os.getenv("POSTHOG_API_KEY")
        if not api_key:
            print("ERROR: POSTHOG_API_KEY is not set; cannot send aliases.")
            sys.exit(1)
        posthog.api_key = api_key
        posthog.project_api_key = api_key
        posthog.host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")

        for uid in user_ids:
            # NB: argument order matters. The canonical id we want to KEEP goes
            # in distinct_id; the legacy id to absorb goes in previous_id.
            posthog.alias(previous_id=f"user:{uid}", distinct_id=str(uid))
        posthog.flush()
        print(f"\nSent and flushed {len(user_ids)} alias event(s) to PostHog.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually send alias events (default is a dry-run).",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        type=int,
        default=None,
        help="Explicit user ids to alias (default: all users with game runs).",
    )
    args = parser.parse_args()
    alias_legacy_game_ids(apply=args.apply, ids=args.ids)


if __name__ == "__main__":
    main()
