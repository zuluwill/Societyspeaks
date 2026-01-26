"""
Audio Storage Abstraction

Provides storage-agnostic interface for audio files.
Supports S3, Replit Object Storage, and filesystem with automatic fallback.

Optimized for Replit:
- Uses Replit Object Storage (persistent across restarts)
- Caches S3 client to avoid recreation overhead
- Graceful fallback chain: S3 -> Replit -> Filesystem
"""

import os
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AudioStorage:
    """
    Storage abstraction for audio files.

    Supports:
    - S3-compatible storage (primary, if AWS credentials set)
    - Replit Object Storage (recommended for Replit deployments)
    - Filesystem (development only - ephemeral on Replit!)
    """

    def __init__(self):
        """Initialize storage with automatic provider detection."""
        self._s3_client = None
        self._replit_client = None
        self.provider = self._detect_provider()
        logger.info(f"Audio storage provider: {self.provider}")

    def _detect_provider(self) -> str:
        """Detect available storage provider."""
        # Check for S3 credentials
        if os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY'):
            return 's3'

        # Check for Replit Object Storage (new API)
        if os.environ.get('REPLIT_DB_URL') or os.environ.get('REPL_ID'):
            try:
                from replit.object_storage import Client
                self._replit_client = Client()
                return 'replit'
            except ImportError:
                # Try old replit module
                try:
                    import replit
                    return 'replit_legacy'
                except ImportError:
                    pass

        # Fallback to filesystem (WARNING: ephemeral on Replit!)
        logger.warning("Using filesystem storage - files will be lost on Replit restart!")
        return 'filesystem'
    
    def save(self, audio_data: bytes, filename: str) -> Optional[str]:
        """
        Save audio data to storage.

        Args:
            audio_data: Audio file bytes
            filename: Filename to save as

        Returns:
            URL/path to saved file, or None if save fails
        """
        # Validate filename to prevent path traversal attacks
        if not filename or '..' in filename or '/' in filename or '\\' in filename:
            logger.error(f"Invalid filename detected: {filename}")
            return None
        
        # Validate audio data
        if not audio_data or len(audio_data) == 0:
            logger.error("Empty audio data provided")
            return None
        
        try:
            if self.provider == 's3':
                return self._save_s3(audio_data, filename)
            elif self.provider == 'replit':
                return self._save_replit(audio_data, filename)
            elif self.provider == 'replit_legacy':
                return self._save_replit_legacy(audio_data, filename)
            else:
                return self._save_filesystem(audio_data, filename)
        except Exception as e:
            logger.error(f"Failed to save audio file {filename}: {e}")
            return None

    def get(self, filename: str) -> Optional[bytes]:
        """
        Retrieve audio data from storage.

        Args:
            filename: Filename to retrieve

        Returns:
            Audio file bytes, or None if not found
        """
        try:
            if self.provider == 's3':
                return self._get_s3(filename)
            elif self.provider == 'replit':
                return self._get_replit(filename)
            elif self.provider == 'replit_legacy':
                return self._get_replit_legacy(filename)
            else:
                return self._get_filesystem(filename)
        except Exception as e:
            logger.error(f"Failed to retrieve audio file {filename}: {e}")
            return None

    def delete(self, filename: str) -> bool:
        """
        Delete audio file from storage.

        Args:
            filename: Filename to delete

        Returns:
            True if deleted, False otherwise
        """
        try:
            if self.provider == 's3':
                return self._delete_s3(filename)
            elif self.provider == 'replit':
                return self._delete_replit(filename)
            elif self.provider == 'replit_legacy':
                return self._delete_replit_legacy(filename)
            else:
                return self._delete_filesystem(filename)
        except Exception as e:
            logger.error(f"Failed to delete audio file {filename}: {e}")
            return False

    def _get_s3_client(self):
        """Get cached S3 client."""
        if self._s3_client is None:
            try:
                import boto3
                self._s3_client = boto3.client(
                    's3',
                    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                    endpoint_url=os.environ.get('AWS_ENDPOINT_URL'),
                    region_name=os.environ.get('AWS_REGION', 'us-east-1')
                )
            except ImportError:
                logger.error("boto3 not installed")
                return None
        return self._s3_client

    def _save_s3(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save to S3-compatible storage."""
        try:
            s3_client = self._get_s3_client()
            if s3_client is None:
                logger.warning("S3 client not available, falling back to Replit storage")
                return self._save_replit(audio_data, filename)

            bucket = os.environ.get('AWS_S3_BUCKET', 'societyspeaks-audio')

            s3_client.put_object(
                Bucket=bucket,
                Key=f"audio/{filename}",
                Body=audio_data,
                ContentType='audio/wav',
                CacheControl='max-age=31536000'  # Cache for 1 year
            )

            # Return public URL or signed URL
            url = f"https://{bucket}.s3.amazonaws.com/audio/{filename}"
            return url

        except Exception as e:
            logger.error(f"S3 save failed: {e}")
            return None

    def _get_s3(self, filename: str) -> Optional[bytes]:
        """Retrieve from S3."""
        try:
            s3_client = self._get_s3_client()
            if s3_client is None:
                return None

            bucket = os.environ.get('AWS_S3_BUCKET', 'societyspeaks-audio')
            response = s3_client.get_object(Bucket=bucket, Key=f"audio/{filename}")
            return response['Body'].read()

        except Exception as e:
            logger.error(f"S3 get failed: {e}")
            return None

    def _delete_s3(self, filename: str) -> bool:
        """Delete from S3."""
        try:
            s3_client = self._get_s3_client()
            if s3_client is None:
                return False

            bucket = os.environ.get('AWS_S3_BUCKET', 'societyspeaks-audio')
            s3_client.delete_object(Bucket=bucket, Key=f"audio/{filename}")
            return True

        except Exception as e:
            logger.error(f"S3 delete failed: {e}")
            return False

    def _save_replit(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save to Replit Object Storage (new API)."""
        try:
            if self._replit_client is None:
                from replit.object_storage import Client
                self._replit_client = Client()

            key = f"audio/{filename}"
            self._replit_client.upload_from_bytes(key, audio_data)
            return f"/audio/{filename}"

        except Exception as e:
            logger.error(f"Replit Object Storage save failed: {e}")
            return None

    def _get_replit(self, filename: str) -> Optional[bytes]:
        """Retrieve from Replit Object Storage (new API)."""
        try:
            if self._replit_client is None:
                from replit.object_storage import Client
                self._replit_client = Client()

            key = f"audio/{filename}"
            return self._replit_client.download_as_bytes(key)

        except Exception as e:
            logger.error(f"Replit Object Storage get failed: {e}")
            return None

    def _delete_replit(self, filename: str) -> bool:
        """Delete from Replit Object Storage (new API)."""
        try:
            if self._replit_client is None:
                from replit.object_storage import Client
                self._replit_client = Client()

            key = f"audio/{filename}"
            self._replit_client.delete(key)
            return True

        except Exception as e:
            logger.error(f"Replit Object Storage delete failed: {e}")
            return False

    def _save_replit_legacy(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save to Replit storage (legacy API)."""
        try:
            from replit import db
            # Store as base64 since replit db doesn't handle raw bytes well
            import base64
            db[f"audio:{filename}"] = base64.b64encode(audio_data).decode('utf-8')
            return f"/audio/{filename}"

        except Exception as e:
            logger.error(f"Replit legacy storage save failed: {e}")
            return None

    def _get_replit_legacy(self, filename: str) -> Optional[bytes]:
        """Retrieve from Replit storage (legacy API)."""
        try:
            from replit import db
            import base64
            data = db.get(f"audio:{filename}")
            if data:
                return base64.b64decode(data)
            return None

        except Exception as e:
            logger.error(f"Replit legacy storage get failed: {e}")
            return None

    def _delete_replit_legacy(self, filename: str) -> bool:
        """Delete from Replit storage (legacy API)."""
        try:
            from replit import db
            key = f"audio:{filename}"
            if key in db:
                del db[key]
                return True
            return False

        except Exception as e:
            logger.error(f"Replit legacy storage delete failed: {e}")
            return False
    
    def _save_filesystem(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save to filesystem (development)."""
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
    
    def cleanup_old_files(self, max_files: int = 100):
        """
        Cleanup old audio files using LRU cache strategy.
        
        Args:
            max_files: Maximum number of files to keep
        """
        # Implementation depends on storage provider
        # For now, log a warning that cleanup is needed
        logger.info(f"Audio cleanup: Keeping max {max_files} files (implementation needed per provider)")


# Global storage instance
audio_storage = AudioStorage()
