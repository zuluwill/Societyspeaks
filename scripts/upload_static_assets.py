#!/usr/bin/env python3
"""
Upload hero and speaker images to Replit Object Storage.
This enables serving these assets without disk I/O, avoiding OSError [Errno 5].
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from replit.object_storage import Client

client = Client()

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'static', 'images')

ASSETS_TO_UPLOAD = [
    ('hero-optimized.jpg', 'hero-optimized.jpg'),
    ('rod-long-optimized-1200x628.jpg', 'rod-long-optimized-1200x628.jpg'),
    ('speakers/eleanor_roosevelt.jpg', 'speakers/eleanor_roosevelt.jpg'),
    ('speakers/John_Stuart_Mill.jpg', 'speakers/John_Stuart_Mill.jpg'),
    ('speakers/Mahatma-Gandhi.jpg', 'speakers/Mahatma-Gandhi.jpg'),
    ('speakers/Malala_Yousafzai.jpg', 'speakers/Malala_Yousafzai.jpg'),
    ('speakers/Margaret_Mead.jpg', 'speakers/Margaret_Mead.jpg'),
    ('speakers/martin_luther_king_jr.jpeg', 'speakers/martin_luther_king_jr.jpeg'),
    ('speakers/Nelson_Mandela.jpg', 'speakers/Nelson_Mandela.jpg'),
    ('speakers/Noam_Chomsky.jpg', 'speakers/Noam_Chomsky.jpg'),
    ('speakers/Thomas_Jefferson.jpg', 'speakers/Thomas_Jefferson.jpg'),
]


def upload_assets():
    """Upload static assets to object storage."""
    success = 0
    failed = 0
    
    for local_path, storage_name in ASSETS_TO_UPLOAD:
        full_path = os.path.join(STATIC_DIR, local_path)
        storage_path = f"static_assets/{storage_name}"
        
        if not os.path.exists(full_path):
            print(f"SKIP: {local_path} (file not found)")
            failed += 1
            continue
        
        try:
            with open(full_path, 'rb') as f:
                file_data = f.read()
            
            client.upload_from_bytes(storage_path, file_data)
            print(f"OK: {local_path} -> {storage_path} ({len(file_data)} bytes)")
            success += 1
        except Exception as e:
            print(f"FAIL: {local_path} - {e}")
            failed += 1
    
    print(f"\nDone: {success} uploaded, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    upload_assets()
