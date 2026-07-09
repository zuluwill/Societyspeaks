#!/usr/bin/env python3
"""
Dump Postgres (Neon) and upload the archive to S3.

Designed for Render Cron / one-off jobs. Does not import Flask.

Required env:
  DATABASE_URL          Neon (or other Postgres) connection string
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_S3_BUCKET

Optional:
  AWS_REGION            default eu-west-2
  BACKUP_S3_PREFIX      default db-backups/
  BACKUP_RETENTION_DAYS default 30 (deletes older objects under the prefix)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def _require(name: str) -> str:
    value = (os.environ.get(name) or '').strip()
    if not value:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _pg_dump_url(database_url: str) -> str:
    """Ensure sslmode=require for Neon / managed Postgres."""
    parsed = urlparse(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault('sslmode', 'require')
    return urlunparse(parsed._replace(query=urlencode(query)))


def _run_pg_dump(database_url: str, out_path: str) -> None:
    env = os.environ.copy()
    # Avoid interactive password prompts; URL carries credentials.
    cmd = [
        'pg_dump',
        _pg_dump_url(database_url),
        '--no-owner',
        '--no-acl',
        '-Fc',
        '-f',
        out_path,
    ]
    print('Running pg_dump…')
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f'pg_dump failed with exit code {result.returncode}')
    size = os.path.getsize(out_path)
    print(f'pg_dump OK ({size} bytes) → {out_path}')


def _s3_client():
    import boto3

    kwargs = {
        'aws_access_key_id': _require('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': _require('AWS_SECRET_ACCESS_KEY'),
        'region_name': (os.environ.get('AWS_REGION') or 'eu-west-2').strip(),
    }
    endpoint = (os.environ.get('AWS_ENDPOINT_URL') or '').strip()
    if endpoint:
        kwargs['endpoint_url'] = endpoint
    return boto3.client('s3', **kwargs)


def _upload(client, bucket: str, key: str, path: str) -> None:
    print(f'Uploading s3://{bucket}/{key}')
    client.upload_file(path, bucket, key)
    print('Upload OK')


def _prune(client, bucket: str, prefix: str, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    print(f'Pruning backups older than {retention_days} days under {prefix}')
    paginator = client.get_paginator('list_objects_v2')
    deleted = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents') or []:
            last_modified = obj['LastModified']
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            if last_modified < cutoff:
                client.delete_object(Bucket=bucket, Key=obj['Key'])
                deleted += 1
                print(f'  deleted {obj["Key"]}')
    print(f'Prune complete ({deleted} objects)')


def main() -> int:
    database_url = _require('DATABASE_URL')
    bucket = _require('AWS_S3_BUCKET')
    prefix = (os.environ.get('BACKUP_S3_PREFIX') or 'db-backups/').strip()
    if not prefix.endswith('/'):
        prefix += '/'
    retention_days = int((os.environ.get('BACKUP_RETENTION_DAYS') or '30').strip() or '30')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    key = f'{prefix}societyspeaks-{stamp}.dump'

    client = _s3_client()
    with tempfile.TemporaryDirectory() as tmp:
        local_path = os.path.join(tmp, 'backup.dump')
        _run_pg_dump(database_url, local_path)
        _upload(client, bucket, key, local_path)

    _prune(client, bucket, prefix, retention_days)
    print(f'Done. Latest backup: s3://{bucket}/{key}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
