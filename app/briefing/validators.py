"""
Briefing Validators

Validation functions for briefing system inputs.
"""

from typing import Tuple, Optional
import re

from flask_babel import lazy_gettext as _l


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    if not email:
        return False, _l("Email is required")

    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, _l("Invalid email format")

    return True, None


def validate_briefing_name(name: str) -> Tuple[bool, Optional[str]]:
    if not name:
        return False, _l("Briefing name is required")

    if len(name.strip()) < 1:
        return False, _l("Briefing name cannot be empty")

    if len(name) > 200:
        return False, _l("Briefing name must be 200 characters or less")

    return True, None


def validate_rss_url(url: str) -> Tuple[bool, Optional[str]]:
    if not url:
        return False, _l("RSS URL is required")

    url_pattern = r'^https?://.+'
    if not re.match(url_pattern, url):
        return False, _l("Invalid URL format. Must start with http:// or https://")

    return True, None


def validate_file_upload(filename: str, max_size_mb: int = 10) -> Tuple[bool, Optional[str]]:
    if not filename:
        return False, _l("File is required")

    allowed_extensions = ['.pdf', '.docx', '.doc']
    if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
        return False, _l("File must be a PDF or Word document (.pdf, .docx, .doc)")

    return True, None


def validate_timezone(timezone: str) -> Tuple[bool, Optional[str]]:
    import pytz

    if not timezone:
        return False, _l("Timezone is required")

    try:
        pytz.timezone(timezone)
        return True, None
    except pytz.UnknownTimeZoneError:
        return False, _l("Invalid timezone")
    except Exception as e:
        return False, _l("Error validating timezone")


def validate_cadence(cadence: str) -> Tuple[bool, Optional[str]]:
    if cadence not in ['daily', 'weekly']:
        return False, _l("Cadence must be 'daily' or 'weekly'")

    return True, None


def validate_visibility(visibility: str) -> Tuple[bool, Optional[str]]:
    if visibility not in ['private', 'org_only', 'public']:
        return False, _l("Visibility must be 'private', 'org_only', or 'public'")

    return True, None


def validate_mode(mode: str) -> Tuple[bool, Optional[str]]:
    if mode not in ['auto_send', 'approval_required']:
        return False, _l("Mode must be 'auto_send' or 'approval_required'")

    return True, None


def validate_send_hour(hour: int) -> Tuple[bool, Optional[str]]:
    if not isinstance(hour, int):
        return False, _l("Send hour must be an integer")

    if hour < 0 or hour > 23:
        return False, _l("Send hour must be between 0 and 23")

    return True, None


def validate_send_minute(minute: int) -> Tuple[bool, Optional[str]]:
    if not isinstance(minute, int):
        return False, _l("Send minute must be an integer")

    if minute < 0 or minute > 59:
        return False, _l("Send minute must be between 0 and 59")

    return True, None
