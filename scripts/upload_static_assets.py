#!/usr/bin/env python3
"""
Upload static images to S3 (no Flask / DATABASE_URL required).

Example:
  export AWS_ACCESS_KEY_ID='AKIA...'
  export AWS_SECRET_ACCESS_KEY='...'
  export AWS_S3_BUCKET='societyspeaks-assets-uk'
  export AWS_REGION='eu-west-2'
  python3 scripts/upload_static_assets.py
"""
from __future__ import annotations

import mimetypes
import os
import sys

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app',
    'static',
    'images',
)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico'}


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or '').strip()
    if not value:
        print(f"Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    if value.startswith('your-') or value in {'paste-access-key-id', 'paste-secret'}:
        print(
            f"{name} still looks like a placeholder. "
            "Export your real AWS access key / secret from IAM.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def iter_static_images():
    for root, _, files in os.walk(STATIC_DIR):
        for filename in files:
            extension = os.path.splitext(filename)[1].lower()
            if extension not in ALLOWED_EXTENSIONS:
                continue
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, STATIC_DIR).replace(os.sep, '/')
            yield full_path, relative_path


def upload_assets() -> bool:
    try:
        import boto3
    except ImportError:
        print("boto3 is not installed. Run: pip3 install boto3", file=sys.stderr)
        return False

    access_key = _require_env('AWS_ACCESS_KEY_ID')
    secret_key = _require_env('AWS_SECRET_ACCESS_KEY')
    bucket = _require_env('AWS_S3_BUCKET')
    region = (os.environ.get('AWS_REGION') or 'eu-west-2').strip()

    client = boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )

    print(f"Uploading to s3://{bucket}/ (region={region})")

    success = 0
    failed = 0
    assets = list(iter_static_images())
    if not assets:
        print("No static images found to upload.")
        return True

    for full_path, storage_name in assets:
        storage_path = f"static_assets/images/{storage_name}"
        content_type, _ = mimetypes.guess_type(storage_name)
        try:
            with open(full_path, 'rb') as fh:
                body = fh.read()
            client.put_object(
                Bucket=bucket,
                Key=storage_path,
                Body=body,
                ContentType=content_type or 'application/octet-stream',
            )
            print(f"OK: {storage_name} -> {storage_path} ({len(body)} bytes)")
            success += 1
        except Exception as exc:
            print(f"FAIL: {storage_name} - {exc}")
            failed += 1

    print(f"\nDone: {success} uploaded, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if upload_assets() else 1)
