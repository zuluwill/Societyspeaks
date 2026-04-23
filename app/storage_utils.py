# app/utils.py
import os
from flask import current_app
import io
import time
from werkzeug.utils import secure_filename
from app.models import Discussion


# Lazy client — only instantiated on first call so that importing this module
# outside of Replit (local dev, CI, non-Replit hosting) does not crash.
_storage_client = None


def _get_client():
    global _storage_client
    if _storage_client is None:
        from replit.object_storage import Client
        _storage_client = Client()
    return _storage_client

# Default base URL for the application
DEFAULT_BASE_URL = 'https://societyspeaks.io'


def get_base_url() -> str:
    """
    Get the application base URL (DRY utility).

    Checks in order:
    1. APP_BASE_URL environment variable
    2. SITE_URL environment variable
    3. Flask app config SITE_URL (when in app context)
    4. Falls back to default (societyspeaks.io)

    Returns:
        str: Base URL without trailing slash
    """
    # Check environment variables first
    base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL')
    
    # Fall back to Flask config if available
    if not base_url:
        try:
            base_url = current_app.config.get('SITE_URL')
        except RuntimeError:
            # Outside of app context
            pass
    
    # Final fallback to default
    if not base_url:
        base_url = DEFAULT_BASE_URL
    
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


# Canonical validation rules for profile-image uploads. Anything hitting
# object storage should pass through these — including admin-side uploads.
ALLOWED_IMAGE_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def _has_allowed_extension(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _within_max_size(file_data):
    file_data.seek(0, os.SEEK_END)
    size = file_data.tell()
    file_data.seek(0)
    return size <= MAX_IMAGE_SIZE


def upload_to_object_storage(file_data, filename, user_id=None):
    """Upload an image to object storage, returning the stored filename.

    Returns ``None`` if validation fails (bad extension, oversized) or if
    the upload itself raises. Callers MUST check the return value before
    persisting it — storing a non-None filename implies the bytes are in
    storage. Passing ``user_id`` prefixes the stored filename so two
    users who upload identically-named files don't clobber each other.
    """
    if file_data is None:
        return None
    try:
        if not _has_allowed_extension(filename):
            current_app.logger.warning(f"Blocked upload of disallowed file type: {filename}")
            return None
        if not _within_max_size(file_data):
            current_app.logger.warning(f"Blocked upload of oversized file: {filename}")
            return None
        if user_id is not None and not filename.startswith(f"{user_id}_"):
            filename = f"{user_id}_{int(time.time())}_{filename}"
        storage_path = f"profile_images/{filename}"

        file_content = file_data.read()
        _get_client().upload_from_bytes(storage_path, file_content)

        current_app.logger.info(f"Successfully uploaded {filename} to object storage")
        return filename
    except Exception as e:
        current_app.logger.error(f"Error uploading file: {str(e)}")
        return None

def delete_from_object_storage(filename):
    """Delete a file from Replit's object storage"""
    try:
        storage_path = f"profile_images/{filename}"
        _get_client().delete(storage_path)
        current_app.logger.info(f"Successfully deleted {filename} from object storage")
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting {filename}: {str(e)}")
        return False

def get_image_from_storage(filename):
    """Retrieve image from Replit's object storage"""
    try:
        storage_path = f"profile_images/{filename}"
        file_data = _get_client().download_as_bytes(storage_path)

        if file_data:
            file_like = io.BytesIO(file_data)
            mime_type = 'image/jpeg'
            if filename.lower().endswith('.png'):
                mime_type = 'image/png'
            elif filename.lower().endswith('.gif'):
                mime_type = 'image/gif'
            elif filename.lower().endswith('.svg'):
                mime_type = 'image/svg+xml'
            elif filename.lower().endswith('.webp'):
                mime_type = 'image/webp'
            return file_like, mime_type
        return None, None
    except Exception as e:
        current_app.logger.error(f"Error retrieving image {filename}: {str(e)}")
        return None, None


def upload_bytes_to_object_storage(storage_path, content_bytes):
    """Upload raw bytes to object storage at an explicit key."""
    try:
        _get_client().upload_from_bytes(storage_path, content_bytes)
        return True
    except Exception as e:
        current_app.logger.error(f"Error uploading bytes to {storage_path}: {str(e)}")
        return False


def download_bytes_from_object_storage(storage_path):
    """Download raw bytes from object storage by key."""
    try:
        return _get_client().download_as_bytes(storage_path)
    except Exception as e:
        current_app.logger.error(f"Error downloading bytes from {storage_path}: {str(e)}")
        return None