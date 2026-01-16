"""
Briefing Validators

Validation utilities for briefing system.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    email = email.strip().lower()
    
    # Basic email regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    # Check length
    if len(email) > 255:
        return False, "Email address is too long (max 255 characters)"
    
    return True, None


def validate_briefing_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate briefing name.
    
    Args:
        name: Briefing name to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Briefing name is required"
    
    name = name.strip()
    
    if len(name) < 3:
        return False, "Briefing name must be at least 3 characters"
    
    if len(name) > 200:
        return False, "Briefing name is too long (max 200 characters)"
    
    return True, None


def validate_rss_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate RSS feed URL.
    
    Args:
        url: URL to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "RSS feed URL is required"
    
    url = url.strip()
    
    # Basic URL validation
    url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    
    if not re.match(url_pattern, url):
        return False, "Invalid URL format"
    
    # Check length
    if len(url) > 500:
        return False, "URL is too long (max 500 characters)"
    
    return True, None


def validate_file_upload(filename: str, file_size: int, max_size_mb: int = 10) -> Tuple[bool, Optional[str]]:
    """
    Validate file upload.
    
    Args:
        filename: Original filename
        file_size: File size in bytes
        max_size_mb: Maximum file size in MB
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filename:
        return False, "No file provided"
    
    # Check extension
    allowed_extensions = {'.pdf', '.docx', '.doc'}
    file_ext = '.' + filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if file_ext not in allowed_extensions:
        return False, f"Only PDF and DOCX files are allowed. Found: {file_ext or 'no extension'}"
    
    # Check size
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        return False, f"File size must be under {max_size_mb}MB"
    
    if file_size == 0:
        return False, "File is empty"
    
    return True, None


def validate_timezone(timezone: str) -> Tuple[bool, Optional[str]]:
    """
    Validate timezone string.
    
    Args:
        timezone: Timezone identifier (e.g., 'America/New_York')
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not timezone:
        return False, "Timezone is required"
    
    # Common timezones (can be expanded)
    valid_timezones = [
        'UTC',
        'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
        'Europe/London', 'Europe/Paris', 'Europe/Berlin',
        'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Dubai',
        'Australia/Sydney', 'Australia/Melbourne'
    ]
    
    if timezone not in valid_timezones:
        # Try to import pytz and validate
        try:
            import pytz
            pytz.timezone(timezone)
            return True, None
        except:
            return False, f"Invalid timezone: {timezone}"
    
    return True, None


def validate_cadence(cadence: str) -> Tuple[bool, Optional[str]]:
    """
    Validate briefing cadence.
    
    Args:
        cadence: Cadence value ('daily' or 'weekly')
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if cadence not in ['daily', 'weekly']:
        return False, "Cadence must be 'daily' or 'weekly'"
    
    return True, None


def validate_visibility(visibility: str) -> Tuple[bool, Optional[str]]:
    """
    Validate briefing visibility.
    
    Args:
        visibility: Visibility value ('private', 'org_only', 'public')
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if visibility not in ['private', 'org_only', 'public']:
        return False, "Visibility must be 'private', 'org_only', or 'public'"
    
    return True, None


def validate_mode(mode: str) -> Tuple[bool, Optional[str]]:
    """
    Validate briefing mode.
    
    Args:
        mode: Mode value ('auto_send' or 'approval_required')
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if mode not in ['auto_send', 'approval_required']:
        return False, "Mode must be 'auto_send' or 'approval_required'"
    
    return True, None
