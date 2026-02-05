#!/usr/bin/env python3
"""
Upload static images to Replit Object Storage.
This enables serving these assets without disk I/O, avoiding OSError [Errno 5].
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from replit.object_storage import Client

client = Client()

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app',
    'static',
    'images'
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
            
            client.upload_from_bytes(storage_path, file_data)
            print(f"OK: {storage_name} -> {storage_path} ({len(file_data)} bytes)")
            success += 1
        except Exception as e:
            print(f"FAIL: {storage_name} - {e}")
            failed += 1
    
    print(f"\nDone: {success} uploaded, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    upload_assets()
