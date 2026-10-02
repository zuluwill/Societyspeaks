"""Create an account from an email address alone.

Used by flows that start with a magic link instead of a registration form
(the briefing trial, self-serve consultations). The account gets a random
password and an unverified email; consuming the magic link verifies it.
"""
import re
import secrets

from werkzeug.security import generate_password_hash

from app import db
from app.models import User


def derive_unique_username(email: str) -> str:
    """Derive a non-colliding username from the local part of ``email``.

    These users don't pick a username; we synthesise one and let them edit it
    later from the profile screen. Falls back to a random suffix on collision.
    """
    local = (email or '').split('@', 1)[0] or 'user'
    base = re.sub(r'[^a-z0-9]+', '-', local.lower()).strip('-') or 'user'
    candidate = base[:30]
    if not User.query.filter_by(username=candidate).first():
        return candidate
    for _attempt in range(5):
        suffix = secrets.token_hex(3)
        candidate = f"{base[:24]}-{suffix}"
        if not User.query.filter_by(username=candidate).first():
            return candidate
    # Extremely unlikely; final fallback is fully random.
    return f"user-{secrets.token_hex(6)}"


def create_passwordless_user(canonical_email: str) -> User:
    """Create and commit a user who will sign in by magic link."""
    user = User(
        username=derive_unique_username(canonical_email),
        email=canonical_email,
        password=generate_password_hash(secrets.token_urlsafe(48)),
        email_verified=False,  # magic-link consume sets this
    )
    db.session.add(user)
    db.session.commit()
    return user
