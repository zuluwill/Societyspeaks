# app/storage_utils.py
"""Object storage helpers with S3 / Replit / filesystem providers.

Provider order:
1. S3-compatible (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_S3_BUCKET)
2. Replit Object Storage (when the package and Replit env are available)
3. Local filesystem under ``app/static`` for ``static_assets/images/...`` keys only

Callers keep using the same upload/download helpers; only env vars change.
"""
from __future__ import annotations

import io
import logging
import mimetypes
import os
import time
from typing import Optional

from flask import current_app
from werkzeug.utils import secure_filename

from app.models import Discussion

logger = logging.getLogger(__name__)

# Default base URL for the application
DEFAULT_BASE_URL = 'https://societyspeaks.io'

# Canonical validation rules for profile-image uploads.
ALLOWED_IMAGE_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

_provider: Optional[str] = None
_s3_client = None
_replit_client = None


def get_base_url() -> str:
    """
    Get the application base URL (DRY utility).

    Checks in order:
    1. APP_BASE_URL environment variable
    2. SITE_URL environment variable
    3. Flask app config SITE_URL (when in app context)
    4. Falls back to default (societyspeaks.io)
    """
    base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL')

    if not base_url:
        try:
            base_url = current_app.config.get('SITE_URL')
        except RuntimeError:
            pass

    if not base_url:
        base_url = DEFAULT_BASE_URL

    return base_url.rstrip('/')


def get_recent_activity(user_id):
    """Get recent activity for the dashboard."""
    activity = []

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


def _has_allowed_extension(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _within_max_size(file_data):
    file_data.seek(0, os.SEEK_END)
    size = file_data.tell()
    file_data.seek(0)
    return size <= MAX_IMAGE_SIZE


def _s3_configured() -> bool:
    return bool(
        (os.environ.get('AWS_ACCESS_KEY_ID') or '').strip()
        and (os.environ.get('AWS_SECRET_ACCESS_KEY') or '').strip()
        and (os.environ.get('AWS_S3_BUCKET') or '').strip()
    )


def _detect_provider() -> str:
    global _provider
    if _provider is not None:
        return _provider

    if _s3_configured():
        _provider = 's3'
    else:
        try:
            from replit.object_storage import Client  # noqa: F401
            # Prefer Replit only when we appear to be on Replit.
            if os.environ.get('REPL_ID') or os.environ.get('REPLIT_DB_URL'):
                _provider = 'replit'
            else:
                _provider = 'filesystem'
        except (ImportError, ModuleNotFoundError, AttributeError):
            _provider = 'filesystem'

    logger.info("Object storage provider: %s", _provider)
    return _provider


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        kwargs = {
            'aws_access_key_id': os.environ.get('AWS_ACCESS_KEY_ID'),
            'aws_secret_access_key': os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'region_name': os.environ.get('AWS_REGION', 'eu-west-2'),
        }
        endpoint = (os.environ.get('AWS_ENDPOINT_URL') or '').strip()
        if endpoint:
            kwargs['endpoint_url'] = endpoint
        _s3_client = boto3.client('s3', **kwargs)
    return _s3_client


def _get_replit_client():
    global _replit_client
    if _replit_client is None:
        from replit.object_storage import Client
        _replit_client = Client()
    return _replit_client


def _s3_bucket() -> str:
    return (os.environ.get('AWS_S3_BUCKET') or '').strip()


def _static_root() -> str:
    """Absolute path to ``app/static``."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')


def _filesystem_path_for_key(storage_path: str) -> Optional[str]:
    """Map object-storage keys under ``static_assets/images/`` to repo static files."""
    prefix = 'static_assets/images/'
    if not storage_path.startswith(prefix):
        return None
    rel = storage_path[len(prefix):]
    if not rel or '..' in rel or rel.startswith('/'):
        return None
    full = os.path.normpath(os.path.join(_static_root(), 'images', rel))
    static_images = os.path.normpath(os.path.join(_static_root(), 'images'))
    if not full.startswith(static_images + os.sep) and full != static_images:
        return None
    return full


def upload_bytes_to_object_storage(storage_path: str, content_bytes: bytes) -> bool:
    """Upload raw bytes to object storage at an explicit key."""
    provider = _detect_provider()
    try:
        if provider == 's3':
            content_type, _ = mimetypes.guess_type(storage_path)
            _get_s3_client().put_object(
                Bucket=_s3_bucket(),
                Key=storage_path,
                Body=content_bytes,
                ContentType=content_type or 'application/octet-stream',
            )
            return True

        if provider == 'replit':
            _get_replit_client().upload_from_bytes(storage_path, content_bytes)
            return True

        # Filesystem: only support writing under static_assets/images for local/dev.
        path = _filesystem_path_for_key(storage_path)
        if path is None:
            logger.error("Filesystem provider cannot write key %s", storage_path)
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(content_bytes)
        return True
    except Exception as e:
        logger.error("Error uploading bytes to %s: %s", storage_path, e)
        try:
            current_app.logger.error("Error uploading bytes to %s: %s", storage_path, e)
        except RuntimeError:
            pass
        return False


def download_bytes_from_object_storage(storage_path: str) -> Optional[bytes]:
    """Download raw bytes from object storage by key.

    Always tries the configured provider first, then falls back to the local
    static tree for ``static_assets/images/...`` keys so marketing assets that
    ship in the repo still work before S3 is configured.
    """
    provider = _detect_provider()
    try:
        if provider == 's3':
            response = _get_s3_client().get_object(Bucket=_s3_bucket(), Key=storage_path)
            return response['Body'].read()

        if provider == 'replit':
            return _get_replit_client().download_as_bytes(storage_path)
    except Exception as e:
        msg = str(e).lower()
        if 'nosuchkey' in msg or 'not found' in msg or '404' in msg:
            logger.info("Object not found at %s via %s", storage_path, provider)
        else:
            logger.error("Error downloading bytes from %s: %s", storage_path, e)
            try:
                current_app.logger.error(
                    "Error downloading bytes from %s: %s", storage_path, e
                )
            except RuntimeError:
                pass

    path = _filesystem_path_for_key(storage_path)
    if path and os.path.isfile(path):
        with open(path, 'rb') as fh:
            return fh.read()
    return None


def delete_bytes_from_object_storage(storage_path: str) -> bool:
    """Delete an object by key."""
    provider = _detect_provider()
    try:
        if provider == 's3':
            _get_s3_client().delete_object(Bucket=_s3_bucket(), Key=storage_path)
            return True
        if provider == 'replit':
            _get_replit_client().delete(storage_path)
            return True
        path = _filesystem_path_for_key(storage_path)
        if path and os.path.isfile(path):
            os.remove(path)
            return True
        return False
    except Exception as e:
        logger.error("Error deleting %s: %s", storage_path, e)
        try:
            current_app.logger.error("Error deleting %s: %s", storage_path, e)
        except RuntimeError:
            pass
        return False


def upload_to_object_storage(file_data, filename, user_id=None):
    """Upload an image to object storage, returning the stored filename.

    Returns ``None`` if validation fails or the upload itself raises.
    """
    if file_data is None:
        return None
    try:
        if not _has_allowed_extension(filename):
            current_app.logger.warning("Blocked upload of disallowed file type: %s", filename)
            return None
        if not _within_max_size(file_data):
            current_app.logger.warning("Blocked upload of oversized file: %s", filename)
            return None
        safe_name = secure_filename(filename) or filename
        if user_id is not None and not safe_name.startswith(f"{user_id}_"):
            safe_name = f"{user_id}_{int(time.time())}_{safe_name}"
        storage_path = f"profile_images/{safe_name}"

        file_content = file_data.read()
        if not upload_bytes_to_object_storage(storage_path, file_content):
            return None

        current_app.logger.info("Successfully uploaded %s to object storage", safe_name)
        return safe_name
    except Exception as e:
        current_app.logger.error("Error uploading file: %s", e)
        return None


def delete_from_object_storage(filename):
    """Delete a profile image from object storage."""
    try:
        storage_path = f"profile_images/{filename}"
        ok = delete_bytes_from_object_storage(storage_path)
        if ok:
            current_app.logger.info("Successfully deleted %s from object storage", filename)
        return ok
    except Exception as e:
        current_app.logger.error("Error deleting %s: %s", filename, e)
        return False


def get_image_from_storage(filename):
    """Retrieve a profile image from object storage as ``(BytesIO, mime)``."""
    try:
        storage_path = f"profile_images/{filename}"
        file_data = download_bytes_from_object_storage(storage_path)
        if not file_data:
            return None, None

        file_like = io.BytesIO(file_data)
        mime_type = 'image/jpeg'
        lower = filename.lower()
        if lower.endswith('.png'):
            mime_type = 'image/png'
        elif lower.endswith('.gif'):
            mime_type = 'image/gif'
        elif lower.endswith('.svg'):
            mime_type = 'image/svg+xml'
        elif lower.endswith('.webp'):
            mime_type = 'image/webp'
        return file_like, mime_type
    except Exception as e:
        current_app.logger.error("Error retrieving image %s: %s", filename, e)
        return None, None
