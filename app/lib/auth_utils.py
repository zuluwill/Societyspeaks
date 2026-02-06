"""
Shared auth utilities to keep validation consistent without coupling flows.
"""
import re
from typing import Optional, Tuple


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # prevent DoS from very large inputs
MAX_EMAIL_LENGTH = 254  # RFC 5321
PARTNER_SIGNUP_RATE_LIMIT = "5 per minute"
PARTNER_LOGIN_RATE_LIMIT = "10 per minute"

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def normalize_email(value: Optional[str]) -> str:
    """Normalize an email address (strip, lowercase). Returns '' if None."""
    return (value or "").strip().lower()


def validate_email_format(email: str) -> Tuple[bool, str]:
    """Basic email format check. Returns (ok, error_message)."""
    if not email:
        return False, "Email is required."
    if len(email) > MAX_EMAIL_LENGTH:
        return False, f"Email must be at most {MAX_EMAIL_LENGTH} characters."
    if not _EMAIL_RE.match(email):
        return False, "Please enter a valid email address."
    return True, ""


def validate_password(password: Optional[str]) -> Tuple[bool, str]:
    """
    Validate password strength for partner portal accounts.

    Requirements:
    - Between 8 and 128 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    """
    if not password:
        return False, "Password is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one digit."
    return True, ""
