#!/usr/bin/env python3
"""Purge Cloudflare edge cache for the dynamic OG PNG routes.

The OG cards (``/discussions/<id>/og.png``, ``/daily/<date>/og.png``,
``/brief/<date>/og.png``, ``/profile/.../og.png``, ``/play/outcome/<uuid>/og.png``)
are edge-cached by Cloudflare (``max-age=300`` on most routes, ``3600`` on
profiles). They self-heal on that TTL, so a purge is only needed for an
*immediate* refresh after a redesign or an ``OG_CACHE_VERSION`` bump.

Cloudflare "purge by prefix" and "purge by tag" are **Enterprise-only**, so this
script uses the two methods available on every plan:

    --everything          Purge the whole zone. Reliable after a font/layout
                          change that affects every card. Briefly evicts other
                          cached assets too, which re-fetch from origin once.
    --files URL [URL ...] Purge specific card URLs. Surgical, no collateral —
                          the right choice when you only touched a few cards.

Requires ``CF_API_TOKEN`` (or ``CLOUDFLARE_API_TOKEN``) and ``CF_ZONE_ID``
(or ``CLOUDFLARE_ZONE_ID``).

Examples:
    export CF_API_TOKEN='…'; export CF_ZONE_ID='…'
    python3 scripts/purge_og_cloudflare.py --everything
    python3 scripts/purge_og_cloudflare.py --files \\
        https://societyspeaks.io/discussions/9639/og.png \\
        https://societyspeaks.io/daily/2026-07-21/og.png
    python3 scripts/purge_og_cloudflare.py --everything --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CF_API = 'https://api.cloudflare.com/client/v4'


def _api_token() -> str | None:
    return os.getenv('CF_API_TOKEN') or os.getenv('CLOUDFLARE_API_TOKEN')


def _zone_id() -> str | None:
    return os.getenv('CF_ZONE_ID') or os.getenv('CLOUDFLARE_ZONE_ID')


def purge_cache(*, everything: bool = False, files: tuple[str, ...] | None = None,
                dry_run: bool = False) -> dict:
    if everything:
        payload = {'purge_everything': True}
    elif files:
        payload = {'files': list(files)}
    else:
        raise SystemExit('Nothing to purge: pass --everything or --files URL [URL ...]')

    if dry_run:
        print(json.dumps(payload, indent=2))
        return {'success': True, 'dry_run': True}

    token = _api_token()
    zone = _zone_id()
    if not token:
        raise SystemExit('CF_API_TOKEN (or CLOUDFLARE_API_TOKEN) is not set')
    if not zone:
        raise SystemExit('CF_ZONE_ID (or CLOUDFLARE_ZONE_ID) is not set')

    req = urllib.request.Request(
        f'{CF_API}/zones/{zone}/purge_cache',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise SystemExit(f'Cloudflare API HTTP {exc.code}: {detail}') from exc

    if not body.get('success'):
        raise SystemExit(f'Cloudflare purge failed: {body}')
    return body


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--everything', action='store_true',
                      help='Purge the entire zone cache (all-plan; use after a redesign)')
    mode.add_argument('--files', nargs='+', metavar='URL',
                      help='Purge specific absolute card URLs (all-plan; surgical)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print the purge payload without calling the API')
    args = parser.parse_args()

    result = purge_cache(
        everything=args.everything,
        files=tuple(args.files) if args.files else None,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        target = 'entire zone' if args.everything else f'{len(args.files)} URL(s)'
        print(f'Cloudflare cache purge succeeded ({target}).')
        errors = result.get('errors') or []
        if errors:
            print('Warnings:', json.dumps(errors, indent=2), file=sys.stderr)


if __name__ == '__main__':
    main()
