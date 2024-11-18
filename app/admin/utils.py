# app/admin/utils.py
from replit.object_storage import Client
from werkzeug.utils import secure_filename
import uuid
from flask import current_app
import io

client = Client()

def save_profile_image(file, file_type):
    """
    Save a profile image to Replit object storage.

    Args:
        file: FileStorage object from form upload
        file_type: String indicating type ('profile', 'company', 'banner')

    Returns:
        String: filename of saved file or None if save failed
    """
    if not file:
        return None

    try:
        # Generate unique filename
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{file_type}/{name}_{uuid.uuid4().hex[:8]}{ext}"

        # Upload to Replit object storage
        client.upload_from_bytes(unique_filename, file.read())

        return unique_filename
    except Exception as e:
        current_app.logger.error(f"Error saving profile image: {str(e)}")
        return None

def delete_profile_image(filename):
    """
    Delete a profile image from Replit object storage.

    Args:
        filename: String filename to delete (including path)

    Returns:
        Boolean: True if deletion was successful
    """
    if not filename:
        return True

    try:
        client.delete(filename)
        return True
    except Exception as e:
        current_app.logger.error(f"Error deleting profile image: {str(e)}")
        return False

def get_file_url(filename):
    """Get the URL for accessing a file from Replit object storage."""
    try:
        return client.get_url(filename)
    except Exception as e:
        current_app.logger.error(f"Error getting file URL: {str(e)}")
        return None