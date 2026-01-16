"""
Briefing Validators

Validation functions for briefing system inputs.
"""

from typing import Tuple, Optional
import re


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email address format.
    
    Args:
        email: Email address string
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Invalid email format"
    
    return True, None


def validate_briefing_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate briefing name.
    
    Args:
        name: Briefing name string
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Briefing name is required"
    
    if len(name.strip()) < 1:
        return False, "Briefing name cannot be empty"
    
    if len(name) > 200:
        return False, "Briefing name must be 200 characters or less"
    
    return True, None


def validate_rss_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate RSS feed URL.
    
    Args:
        url: RSS feed URL string
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "RSS URL is required"
    
    # Basic URL validation
    url_pattern = r'^https?://.+'
    if not re.match(url_pattern, url):
        return False, "Invalid URL format. Must start with http:// or https://"
    
    return True, None


def validate_file_upload(filename: str, max_size_mb: int = 10) -> Tuple[bool, Optional[str]]:
    """
    Validate file upload.
    
    Args:
        filename: Uploaded file name
        max_size_mb: Maximum file size in MB
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filename:
        return False, "File is required"
    
    # Check extension
    allowed_extensions = ['.pdf', '.docx', '.doc']
    if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
        return False, f"File must be one of: {', '.join(allowed_extensions)}"
    
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
    
    # Validate using pytz - accepts any valid timezone
    try:
        import pytz
        pytz.timezone(timezone)
        return True, None
    except pytz.UnknownTimeZoneError:
        return False, f"Invalid timezone: {timezone}"
    except Exception as e:
        return False, f"Error validating timezone: {str(e)}"


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


def validate_send_hour(hour: int) -> Tuple[bool, Optional[str]]:
    """
    Validate send hour.
    
    Args:
        hour: Hour value (0-23)
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(hour, int):
        return False, "Send hour must be an integer"
    
    if hour < 0 or hour > 23:
        return False, "Send hour must be between 0 and 23"
    
    return True, None


def validate_send_minute(minute: int) -> Tuple[bool, Optional[str]]:
    """
    Validate send minute.
    
    Args:
        minute: Minute value (0-59)
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(minute, int):
        return False, "Send minute must be an integer"
    
    if minute < 0 or minute > 59:
        return False, "Send minute must be between 0 and 59"
    
    return True, None
