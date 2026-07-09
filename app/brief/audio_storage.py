"""
Audio Storage Abstraction

Thin wrapper over app.storage_utils (S3 in production) for audio files,
stored under the ``audio/`` object-storage prefix. Development machines
without S3 credentials fall back to a local ``audio_files/`` directory —
never in production, where the provider is S3 and a failed S3 call is an
error, not a reason to write to the ephemeral container disk.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AudioStorage:
    """Storage abstraction for audio files."""

    @staticmethod
    def _is_valid_filename(filename: str) -> bool:
        """Reject empty names and path traversal."""
        return bool(filename) and '..' not in filename and '/' not in filename and '\\' not in filename

    @staticmethod
    def _object_storage_backed() -> bool:
        from app.storage_utils import storage_provider
        return storage_provider() == 's3'

    def save(self, audio_data: bytes, filename: str) -> Optional[str]:
        """
        Save audio data to storage.

        Returns the serving path (``/audio/<filename>``), or None on failure.
        """
        if not self._is_valid_filename(filename):
            logger.error(f"Invalid filename detected: {filename}")
            return None
        if not audio_data:
            logger.error("Empty audio data provided")
            return None

        if self._object_storage_backed():
            from app.storage_utils import upload_bytes_to_object_storage
            if upload_bytes_to_object_storage(f"audio/{filename}", audio_data):
                return f"/audio/{filename}"
            return None
        return self._save_filesystem(audio_data, filename)

    def get(self, filename: str) -> Optional[bytes]:
        """Retrieve audio data, or None if not found."""
        if not self._is_valid_filename(filename):
            logger.error(f"Invalid filename detected: {filename}")
            return None

        if self._object_storage_backed():
            from app.storage_utils import download_bytes_from_object_storage
            return download_bytes_from_object_storage(f"audio/{filename}")
        return self._get_filesystem(filename)

    def delete(self, filename: str) -> bool:
        """Delete an audio file. Returns True on success."""
        if not self._is_valid_filename(filename):
            logger.error(f"Invalid filename detected: {filename}")
            return False

        if self._object_storage_backed():
            from app.storage_utils import delete_bytes_from_object_storage
            return delete_bytes_from_object_storage(f"audio/{filename}")
        return self._delete_filesystem(filename)

    def _save_filesystem(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save to filesystem (development only)."""
        try:
            audio_dir = os.path.join(os.getcwd(), 'audio_files')
            os.makedirs(audio_dir, exist_ok=True)

            filepath = os.path.join(audio_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(audio_data)

            return f"/audio/{filename}"

        except Exception as e:
            logger.error(f"Filesystem save failed: {e}")
            return None

    def _get_filesystem(self, filename: str) -> Optional[bytes]:
        """Retrieve from filesystem."""
        try:
            audio_dir = os.path.join(os.getcwd(), 'audio_files')
            filepath = os.path.join(audio_dir, filename)

            with open(filepath, 'rb') as f:
                return f.read()

        except FileNotFoundError:
            logger.warning(f"Audio file not found: {filename}")
            return None
        except Exception as e:
            logger.error(f"Filesystem get failed: {e}")
            return None

    def _delete_filesystem(self, filename: str) -> bool:
        """Delete from filesystem."""
        try:
            audio_dir = os.path.join(os.getcwd(), 'audio_files')
            filepath = os.path.join(audio_dir, filename)

            if os.path.exists(filepath):
                os.remove(filepath)
                return True
            return False

        except Exception as e:
            logger.error(f"Filesystem delete failed: {e}")
            return False


# Global storage instance
audio_storage = AudioStorage()
