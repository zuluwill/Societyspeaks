#!/usr/bin/env python3
"""
Production smoke checks for Render (and optional S3).

Usage:
  export RENDER_HEALTH_URL='https://societyspeaks-web.onrender.com'
  python3 scripts/ops_health_check.py

Optional:
  AWS_*  — if set, also HEAD-check a known S3 object
  HEALTH_S3_KEY — default static_assets/images/hero-optimized.jpg
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request


def _check_http(url: str, expect_status: int = 200) -> None:
    print(f'HTTP GET {url}')
    req = urllib.request.Request(url, method='GET', headers={'User-Agent': 'societyspeaks-ops-health/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = getattr(resp, 'status', None) or resp.getcode()
            body_len = len(resp.read(64))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f'FAIL {url}: HTTP {exc.code}') from exc
    except Exception as exc:
        raise SystemExit(f'FAIL {url}: {exc}') from exc
    if status != expect_status:
        raise SystemExit(f'FAIL {url}: expected {expect_status}, got {status}')
    print(f'  OK status={status} (read {body_len} bytes)')


def _check_s3() -> None:
    access = (os.environ.get('AWS_ACCESS_KEY_ID') or '').strip()
    secret = (os.environ.get('AWS_SECRET_ACCESS_KEY') or '').strip()
    bucket = (os.environ.get('AWS_S3_BUCKET') or '').strip()
    if not (access and secret and bucket):
        print('S3 check skipped (AWS_* not fully set)')
        return

    import boto3

    key = (os.environ.get('HEALTH_S3_KEY') or 'static_assets/images/hero-optimized.jpg').strip()
    region = (os.environ.get('AWS_REGION') or 'eu-west-2').strip()
    print(f'S3 HEAD s3://{bucket}/{key}')
    client = boto3.client(
        's3',
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
    )
    client.head_object(Bucket=bucket, Key=key)
    print('  OK')


def main() -> int:
    base = (os.environ.get('RENDER_HEALTH_URL') or '').strip().rstrip('/')
    if not base:
        print('Set RENDER_HEALTH_URL to your Render web URL (https://….onrender.com)', file=sys.stderr)
        return 1

    _check_http(f'{base}/')
    # Favicon is a cheap authenticated-free static check
    _check_http(f'{base}/favicon.ico')
    _check_s3()
    print('All health checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
