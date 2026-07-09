#!/usr/bin/env python3
"""
One-time S3 bucket hardening for societyspeaks-assets-uk.

Enables:
  - Bucket versioning (protects against accidental overwrite/delete)
  - Lifecycle rule: expire noncurrent versions after 90 days
  - Lifecycle rule: expire db-backups/ objects after BACKUP_RETENTION_DAYS (default 30)

Usage:
  export AWS_ACCESS_KEY_ID=...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_S3_BUCKET=societyspeaks-assets-uk
  export AWS_REGION=eu-west-2
  python3 scripts/enable_s3_bucket_best_practice.py
"""
from __future__ import annotations

import os
import sys


def _require(name: str) -> str:
    value = (os.environ.get(name) or '').strip()
    if not value:
        print(f'Missing {name}', file=sys.stderr)
        sys.exit(1)
    return value


def main() -> int:
    import boto3

    bucket = _require('AWS_S3_BUCKET')
    region = (os.environ.get('AWS_REGION') or 'eu-west-2').strip()
    retention = int((os.environ.get('BACKUP_RETENTION_DAYS') or '30').strip() or '30')

    client = boto3.client(
        's3',
        aws_access_key_id=_require('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=_require('AWS_SECRET_ACCESS_KEY'),
        region_name=region,
    )

    print(f'Enabling versioning on s3://{bucket}')
    client.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={'Status': 'Enabled'},
    )

    print('Applying lifecycle configuration')
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            'Rules': [
                {
                    'ID': 'expire-noncurrent-versions-90d',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': ''},
                    'NoncurrentVersionExpiration': {'NoncurrentDays': 90},
                },
                {
                    'ID': f'expire-db-backups-{retention}d',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': 'db-backups/'},
                    'Expiration': {'Days': retention},
                },
            ]
        },
    )

    print('Done. Versioning + lifecycle rules are active.')
    print('Note: IAM user needs s3:PutBucketVersioning and s3:PutLifecycleConfiguration')
    print('on the bucket (or run this once with an admin user).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
