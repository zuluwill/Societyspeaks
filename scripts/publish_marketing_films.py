#!/usr/bin/env python3
"""Publish the product films to object storage and record them in the app.

Reads the web export from the video studio (``node production/web-export.mjs`` writes
``deliverables/web/`` with content-hashed files and ``manifest.json``), then:

  1. uploads every file the manifest names to ``marketing_films/<name>`` with a
     one-year immutable Cache-Control (skipping files already there), and
  2. copies the manifest to ``app/lib/marketing_films.json`` (commit it).

Pages show the films once ``MARKETING_FILMS_ENABLED=true``. Upload before you
deploy the manifest, or the posters 404.

    python3 scripts/publish_marketing_films.py --source ../societyspeaks-video-studio/deliverables/web --dry-run
    python3 scripts/publish_marketing_films.py --source ../societyspeaks-video-studio/deliverables/web
    python3 scripts/publish_marketing_films.py --source ... --local     # dev: copy into app/static/films/

S3 credentials come from the usual AWS_* variables (see app/storage_utils.py). Every film in the
manifest needs a title and description in app/lib/marketing_films.py FILMS first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MANIFEST_PATH = os.path.join(ROOT, 'app', 'lib', 'marketing_films.json')
# Must match app/lib/marketing_films.py (tests/test_marketing_films.py checks). Kept here so the
# script runs without the app's configuration (no DATABASE_URL needed to upload files).
STORAGE_PREFIX = 'marketing_films/'
FILM_CACHE_CONTROL = 'public, max-age=31536000, immutable'
CONTENT_TYPES = {'.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.vtt': 'text/vtt'}


def _names(manifest: dict) -> list[str]:
    return [f['name'] for film in manifest['films'].values() for f in film['files'].values()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', required=True, help='the studio web export directory (contains manifest.json)')
    parser.add_argument('--dry-run', action='store_true', help='list what would be uploaded; change nothing')
    parser.add_argument('--local', action='store_true', help='copy into app/static/films/ for local development')
    args = parser.parse_args()

    with open(os.path.join(args.source, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    names = _names(manifest)
    missing = [n for n in names if not os.path.isfile(os.path.join(args.source, n))]
    if missing:
        print('Missing from the export: ' + ', '.join(missing))
        return 1

    if args.local:
        dest = os.path.join(ROOT, 'app', 'static', 'films')
        os.makedirs(dest, exist_ok=True)
        for n in names:
            shutil.copy2(os.path.join(args.source, n), os.path.join(dest, n))
        print(f'Copied {len(names)} files to {dest}')
    else:
        bucket = (os.environ.get('AWS_S3_BUCKET') or '').strip()
        if not (bucket and os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY')):
            print('S3 is not configured (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET).')
            return 1
        import boto3
        client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'eu-west-2'),
                              **({'endpoint_url': os.environ['AWS_ENDPOINT_URL']} if os.environ.get('AWS_ENDPOINT_URL') else {}))
        total = 0
        for n in names:
            key = STORAGE_PREFIX + n
            try:
                client.head_object(Bucket=bucket, Key=key)
                print(f'  exists   {key}')
                continue
            except client.exceptions.ClientError:
                pass
            size = os.path.getsize(os.path.join(args.source, n))
            total += size
            print(f'  {"would upload" if args.dry_run else "upload"}   {key}  ({size / 1e6:.1f} MB)')
            if not args.dry_run:
                client.upload_file(
                    os.path.join(args.source, n), bucket, key,
                    ExtraArgs={'ContentType': CONTENT_TYPES[os.path.splitext(n)[1]], 'CacheControl': FILM_CACHE_CONTROL},
                )
        print(f'{"Would upload" if args.dry_run else "Uploaded"} {total / 1e6:.1f} MB to s3://{bucket}/{STORAGE_PREFIX}')

    if not args.dry_run:
        shutil.copyfile(os.path.join(args.source, 'manifest.json'), MANIFEST_PATH)
        print(f'Manifest -> {os.path.relpath(MANIFEST_PATH, ROOT)} (commit it)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
