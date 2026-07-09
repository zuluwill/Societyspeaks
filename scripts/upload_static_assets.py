#!/usr/bin/env python3
"""
Upload static images to object storage (S3 or Replit).

Uses the same provider detection as app.storage_utils:
  - S3 when AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_S3_BUCKET are set
  - Replit Object Storage when running on Replit

Example (S3 London):
  export AWS_ACCESS_KEY_ID=...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_S3_BUCKET=societyspeaks-assets
  export AWS_REGION=eu-west-2
  python3 scripts/upload_static_assets.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage_utils import upload_bytes_to_object_storage, _detect_provider

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app',
    'static',
    'images',
)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico'}


def iter_static_images():
    """Yield (full_path, relative_path) for static images."""
    for root, _, files in os.walk(STATIC_DIR):
        for filename in files:
            extension = os.path.splitext(filename)[1].lower()
            if extension not in ALLOWED_EXTENSIONS:
                continue
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, STATIC_DIR).replace(os.sep, '/')
            yield full_path, relative_path


def upload_assets():
    """Upload static assets to object storage."""
    provider = _detect_provider()
    print(f"Using storage provider: {provider}")

    success = 0
    failed = 0

    assets = list(iter_static_images())
    if not assets:
        print("No static images found to upload.")
        return True

    for full_path, storage_name in assets:
        storage_path = f"static_assets/images/{storage_name}"

        try:
            with open(full_path, 'rb') as f:
                file_data = f.read()

            if not upload_bytes_to_object_storage(storage_path, file_data):
                raise RuntimeError("upload_bytes_to_object_storage returned False")

            print(f"OK: {storage_name} -> {storage_path} ({len(file_data)} bytes)")
            success += 1
        except Exception as e:
            print(f"FAIL: {storage_name} - {e}")
            failed += 1

    print(f"\nDone: {success} uploaded, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    ok = upload_assets()
    sys.exit(0 if ok else 1)
