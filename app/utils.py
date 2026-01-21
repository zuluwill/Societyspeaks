# app/utils.py
import os
from flask import current_app
from replit.object_storage import Client
import io
import time
from werkzeug.utils import secure_filename
from app.models import Discussion


client = Client()

# Default base URL for the application
DEFAULT_BASE_URL = 'https://societyspeaks.io'


def get_base_url() -> str:
    """
    Get the application base URL (DRY utility).

    Checks in order:
    1. APP_BASE_URL environment variable
    2. SITE_URL environment variable
    3. Falls back to default (societyspeaks.io)

    Returns:
        str: Base URL without trailing slash
    """
    base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL', DEFAULT_BASE_URL)
    return base_url.rstrip('/')

def get_recent_activity(user_id):
    """
    Get recent activity for the dashboard
    Returns a list of activity items with type, content, and timestamp
    """
    activity = []

    # Get recent discussions
    recent_discussions = Discussion.query\
        .filter_by(creator_id=user_id)\
        .order_by(Discussion.created_at.desc())\
        .limit(5)\
        .all()

    for discussion in recent_discussions:
        activity.append({
            'type': 'discussion_created',
            'content': f"Created discussion: {discussion.title}",
            'timestamp': discussion.created_at
        })

    return activity


def upload_to_object_storage(file_data, filename, user_id=None):
    """Upload file to Replit's object storage"""
    try:
        if user_id and not filename.startswith(f"{user_id}_"):
            filename = f"{user_id}_{int(time.time())}_{filename}"
        storage_path = f"profile_images/{filename}"

        file_content = file_data.read()
        client.upload_from_bytes(storage_path, file_content)

        current_app.logger.info(f"Successfully uploaded {filename} to object storage")
        return filename
    except Exception as e:
        current_app.logger.error(f"Error uploading file: {str(e)}")
        return None

def delete_from_object_storage(filename):
    """Delete a file from Replit's object storage"""
    try:
        storage_path = f"profile_images/{filename}"
        client.delete(storage_path)
        current_app.logger.info(f"Successfully deleted {filename} from object storage")
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting {filename}: {str(e)}")
        return False

def get_image_from_storage(filename):
    """Retrieve image from Replit's object storage"""
    try:
        storage_path = f"profile_images/{filename}"
        file_data = client.download_as_bytes(storage_path)

        if file_data:
            file_like = io.BytesIO(file_data)
            mime_type = 'image/jpeg'
            if filename.lower().endswith('.png'):
                mime_type = 'image/png'
            elif filename.lower().endswith('.gif'):
                mime_type = 'image/gif'
            return file_like, mime_type
        return None, None
    except Exception as e:
        current_app.logger.error(f"Error retrieving image {filename}: {str(e)}")
        return None, None