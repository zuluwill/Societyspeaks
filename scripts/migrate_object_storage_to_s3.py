#!/usr/bin/env python3
"""
One-off migration: Replit Object Storage → AWS S3

Copies every object from this Repl's Object Storage to the target S3 bucket,
preserving the exact object key so all existing DB filenames keep working.
Idempotent: objects already present on S3 are skipped (--force to re-upload).

Usage
-----
    # Dry run — lists what would be migrated, touches nothing
    python3 scripts/migrate_object_storage_to_s3.py --dry-run

    # Full migration (all prefixes)
    python3 scripts/migrate_object_storage_to_s3.py

    # Single prefix only
    python3 scripts/migrate_object_storage_to_s3.py --prefix profile_images/

    # Re-upload even if key already exists on S3
    python3 scripts/migrate_object_storage_to_s3.py --force

Required env vars
-----------------
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_S3_BUCKET     (default: societyspeaks-assets-uk)
    AWS_REGION        (default: eu-west-2)

Do NOT commit these values — set them temporarily in the Replit Secrets panel
or export them in your shell before running the script.

Prefixes this app uses
----------------------
    profile_images/              User profile photos, banner images, org logos
    static_assets/images/        Repo static images uploaded via upload_static_assets.py
    audio/                       Briefing TTS audio files
    briefing_uploads/{user_id}/  User-uploaded PDFs/DOCXs for briefing ingestion
    programme_exports/           Programme export archives (PDF/ZIP)
    evidence/                    Evidence files attached to statement responses
"""

import argparse
import mimetypes
import os
import sys
import time

# Allow running from repo root or scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args():
    p = argparse.ArgumentParser(
        description='Migrate Replit Object Storage → AWS S3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        '--dry-run', action='store_true',
        help='List objects and check S3 status; upload nothing.',
    )
    p.add_argument(
        '--prefix', default='',
        metavar='PREFIX',
        help='Only migrate objects whose key starts with PREFIX '
             '(e.g. "profile_images/"). Default: migrate everything.',
    )
    p.add_argument(
        '--force', action='store_true',
        help='Re-upload even if the key already exists on S3.',
    )
    return p.parse_args()


def _connect_replit():
    """Return an initialised Replit Object Storage client."""
    try:
        from replit.object_storage import Client
        client = Client()
        print("✓ Connected to Replit Object Storage.")
        return client
    except ImportError:
        print("ERROR: 'replit' package not installed. Run: pip install replit", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not connect to Replit Object Storage: {e}", file=sys.stderr)
        sys.exit(1)


def _connect_s3(bucket, region):
    """Return (s3_client, ClientError_class) or exit on failure."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("ERROR: boto3 not installed. Run: pip install boto3", file=sys.stderr)
        sys.exit(1)

    s3 = boto3.client(
        's3',
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
        region_name=region,
    )
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"✓ Connected to S3 bucket '{bucket}' ({region}).")
    except ClientError as e:
        code = e.response['Error']['Code']
        if code in ('403', 'AccessDenied'):
            print(f"ERROR: Access denied to bucket '{bucket}'. Check IAM permissions.", file=sys.stderr)
        elif code in ('404', 'NoSuchBucket'):
            print(f"ERROR: Bucket '{bucket}' does not exist in region {region}.", file=sys.stderr)
        else:
            print(f"ERROR: S3 head_bucket failed ({code}): {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not connect to S3: {e}", file=sys.stderr)
        sys.exit(1)

    return s3, ClientError


def _list_replit_objects(client, prefix):
    """
    Return a sorted list of all object key strings.

    Handles both SDK versions that return plain strings and those that return
    objects with a .name or .key attribute.
    """
    try:
        raw = client.list(prefix=prefix)
    except TypeError:
        # Older SDK: list() may not accept keyword args
        raw = client.list()
        if prefix:
            raw = [item for item in raw if _key_of(item).startswith(prefix)]

    keys = []
    for item in raw:
        keys.append(_key_of(item))
    return sorted(keys)


def _key_of(item):
    """Extract the string key from whatever the SDK list() returns."""
    if isinstance(item, str):
        return item
    for attr in ('name', 'key', 'object_name'):
        if hasattr(item, attr):
            return getattr(item, attr)
    return str(item)


def _content_type(key):
    ct, _ = mimetypes.guess_type(key)
    return ct or 'application/octet-stream'


def _already_on_s3(s3, ClientError, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        # Unexpected error — surface but don't abort the whole run
        print(f"    WARN  head_object({key}): {e}")
        return False


def main():
    args = _parse_args()

    missing_env = [v for v in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY') if not os.environ.get(v)]
    if missing_env:
        print(f"ERROR: Missing env vars: {', '.join(missing_env)}", file=sys.stderr)
        print("Set them in Replit Secrets or: export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...",
              file=sys.stderr)
        sys.exit(1)

    bucket = os.environ.get('AWS_S3_BUCKET', 'societyspeaks-assets-uk')
    region = os.environ.get('AWS_REGION', 'eu-west-2')

    print()
    print("Replit Object Storage → AWS S3 Migration")
    print("─" * 50)
    print(f"  Target bucket : s3://{bucket}  ({region})")
    print(f"  Prefix filter : {args.prefix!r or '(all objects)'}")
    print(f"  Dry run       : {args.dry_run}")
    print(f"  Force re-upload: {args.force}")
    print()

    replit = _connect_replit()
    s3, ClientError = _connect_s3(bucket, region)
    print()

    print(f"Listing objects from Replit Object Storage{f' (prefix={args.prefix!r})' if args.prefix else ''}…")
    keys = _list_replit_objects(replit, args.prefix)

    if not keys:
        print("No objects found. Nothing to migrate.")
        return

    print(f"Found {len(keys)} object(s).\n")

    # ── Summary by prefix ──────────────────────────────────────────────────
    from collections import Counter
    prefix_counts = Counter(k.split('/')[0] for k in keys)
    for pfx, count in sorted(prefix_counts.items()):
        print(f"  {pfx}/  → {count} object(s)")
    print()

    if args.dry_run:
        print("DRY RUN — no data will be transferred.\n")

    # ── Migrate ────────────────────────────────────────────────────────────
    ok = skipped = failed = 0
    t0 = time.time()
    total = len(keys)

    for i, key in enumerate(keys, 1):
        tag = f"[{i:>{len(str(total))}}/{total}]"

        if not args.force and _already_on_s3(s3, ClientError, bucket, key):
            print(f"  {tag} SKIP   {key}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  {tag} DRY    {key}")
            ok += 1
            continue

        # Download from Replit
        try:
            data = replit.download_as_bytes(key)
        except Exception as e:
            print(f"  {tag} FAIL   {key}  ← download error: {e}")
            failed += 1
            continue

        if not data:
            print(f"  {tag} FAIL   {key}  ← empty response from Replit")
            failed += 1
            continue

        # Upload to S3
        ct = _content_type(key)
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=ct,
                CacheControl='max-age=31536000, public',
            )
            size_str = f"{len(data) / 1024:.1f} KB"
            print(f"  {tag} OK     {key}  ({size_str}, {ct})")
            ok += 1
        except Exception as e:
            print(f"  {tag} FAIL   {key}  ← S3 upload error: {e}")
            failed += 1

    elapsed = time.time() - t0
    print()
    print("─" * 50)
    print(f"Finished in {elapsed:.1f}s")
    print(f"  Uploaded : {ok}")
    print(f"  Skipped  : {skipped}  (already on S3; use --force to re-upload)")
    print(f"  Failed   : {failed}")
    print("─" * 50)

    if failed:
        print(f"\n{failed} object(s) failed — re-run the script to retry them (already-uploaded keys will be skipped).")
        sys.exit(1)
    elif not args.dry_run:
        print("\nAll objects migrated successfully.")
        print(f"Verify a sample: aws s3 ls s3://{bucket}/profile_images/ --region {region}")


if __name__ == '__main__':
    main()
