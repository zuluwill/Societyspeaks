#!/usr/bin/env python3
"""One-off cleanup: delete anonymous session keys from Redis.

Context: before app/lib/session_policy.py, every visitor and crawler request
stored a 7-day session key; ~275k of them filled the 250MB instance and forced
volatile-lru evictions. This script removes session keys that contain no
authenticated principal, reclaiming memory immediately instead of waiting up
to 7 days for TTL expiry.

Anonymous sessions carry only CSRF tokens and transient UI state, so deleting
them logs nobody out. Sessions containing '_user_id' (Flask-Login) or
'partner_portal_id' (partner portal) are always kept. Detection is a byte
search on the serialized value (msgpack embeds key names as raw UTF-8), which
avoids deserializing untrusted payloads.

Usage:
    export REDIS_URL='rediss://…'
    python3 scripts/purge_anonymous_sessions.py            # dry run (default)
    python3 scripts/purge_anonymous_sessions.py --execute  # actually delete
"""
import argparse
import os
import sys

try:
    import redis
except ImportError:
    sys.stderr.write("pip install redis\n")
    sys.exit(2)

AUTH_MARKERS = (b'_user_id', b'partner_portal_id')
BATCH = 500


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true',
                        help='Delete anonymous sessions (default: dry run)')
    parser.add_argument('--prefix', default='session:',
                        help='Session key prefix (default: session:)')
    args = parser.parse_args()

    url = os.getenv('REDIS_URL')
    if not url:
        sys.stderr.write("REDIS_URL is not set\n")
        sys.exit(2)

    r = redis.from_url(url, socket_timeout=15,
                       ssl_cert_reqs=None if url.startswith('rediss://') else 'required')
    r.ping()

    scanned = kept = deleted = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match=args.prefix + '*', count=BATCH)
        if keys:
            values = r.mget(keys)
            to_delete = []
            for key, value in zip(keys, values):
                scanned += 1
                if value is None:
                    continue
                if any(marker in value for marker in AUTH_MARKERS):
                    kept += 1
                else:
                    to_delete.append(key)
            if to_delete:
                if args.execute:
                    r.delete(*to_delete)
                deleted += len(to_delete)
            if scanned % 25000 < BATCH:
                print(f"scanned={scanned} authenticated_kept={kept} "
                      f"anonymous_{'deleted' if args.execute else 'would_delete'}={deleted}")
        if cursor == 0:
            break

    mode = 'DELETED' if args.execute else 'DRY RUN — would delete'
    print(f"\nDone. scanned={scanned} authenticated kept={kept} {mode}={deleted}")
    if not args.execute:
        print("Re-run with --execute to delete.")


if __name__ == '__main__':
    main()
